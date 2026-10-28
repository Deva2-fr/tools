"""Boîtes mail du Hub : plusieurs boîtes IMAP (contact@, compta@…) et, en option, une boîte Microsoft 365."""

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt
from app.models import Mailbox, MailMessage
from app.services import integrations, mail_imap, outlook

log = logging.getLogger("deva2.mail")
LEGACY_KEYS = (
    "imap_host",
    "imap_port",
    "imap_user",
    "imap_password",
    "imap_sent_folder",
    "imap_webmail_url",
)


def boxes(db: Session, active_only: bool = False) -> list[Mailbox]:
    stmt = select(Mailbox).order_by(Mailbox.position, Mailbox.id)
    if active_only:
        stmt = stmt.where(Mailbox.active.is_(True))
    return list(db.scalars(stmt))


def microsoft_connected(db: Session) -> bool:
    return bool(integrations.get(db, "microsoft_refresh_token"))


def migrate_legacy(db: Session) -> None:
    """Reprend l'ancienne boîte unique (réglages « imap_* » des intégrations) comme première boîte."""
    host = integrations.get(db, "imap_host")
    if not host:
        return
    if not db.scalar(select(Mailbox.id).limit(1)):
        user = integrations.get(db, "imap_user")
        try:
            port = int(integrations.get(db, "imap_port", "993") or 993)
        except ValueError:
            port = 993
        password = integrations.get(db, "imap_password")
        box = Mailbox(
            name=(user.split("@")[0].capitalize() if user else "Boîte principale")[:80],
            host=host,
            port=port,
            username=user,
            password_enc=encrypt(password) if password else "",
            sent_folder=integrations.get(db, "imap_sent_folder"),
            webmail_url=integrations.get(db, "imap_webmail_url"),
        )
        db.add(box)
        db.flush()
        # Mails déjà synchronisés : rattachés à cette boîte, avec la nouvelle clé « imap:<boîte>:<id> ».
        for m in db.scalars(select(MailMessage).where(MailMessage.graph_id.like("imap:%"))):
            if m.mailbox_id is None:
                m.mailbox_id = box.id
                m.graph_id = f"imap:{box.id}:{m.graph_id[5:]}"[:400]
        log.info("Ancienne boîte IMAP reprise comme « %s »", box.name)
    for key in LEGACY_KEYS:
        integrations.put(db, key, "")
    db.commit()


def sync_one(db: Session, box: Mailbox) -> int:
    return mail_imap.sync_inbox(db, box)


def sync_all(db: Session) -> dict:
    """Synchronise toutes les boîtes actives. Une boîte en erreur n'empêche pas les autres."""
    migrate_legacy(db)
    created, errors = 0, []
    for box in boxes(db, active_only=True):
        try:
            created += mail_imap.sync_inbox(db, box)
        except Exception as exc:  # noqa: BLE001 - erreur enregistrée sur la boîte, on continue
            errors.append(f"{box.name} : {exc}")
            log.warning("Boîte %s : %s", box.name, exc)
    if microsoft_connected(db):
        try:
            created += outlook.sync_inbox(db)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Microsoft 365 : {exc}")
    return {"new": created, "errors": errors}


def delete_box(db: Session, box: Mailbox) -> None:
    """Supprime la boîte du Hub et ses mails copiés (rien n'est supprimé sur le serveur mail)."""
    db.execute(delete(MailMessage).where(MailMessage.mailbox_id == box.id))
    db.delete(box)
    db.commit()
