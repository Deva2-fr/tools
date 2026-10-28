"""Choix de la source des mails : serveur IMAP classique (prioritaire) ou Microsoft 365."""

from sqlalchemy.orm import Session

from app.services import integrations, mail_imap, outlook


def provider(db: Session) -> str | None:
    if mail_imap.is_configured(db):
        return "imap"
    if integrations.get(db, "microsoft_refresh_token"):
        return "microsoft"
    return None


def mailbox_address(db: Session) -> str:
    kind = provider(db)
    if kind == "imap":
        return integrations.get(db, "imap_user")
    if kind == "microsoft":
        return integrations.get(db, "microsoft_mailbox")
    return ""


def sync(db: Session) -> int:
    kind = provider(db)
    if kind == "imap":
        return mail_imap.sync_inbox(db)
    if kind == "microsoft":
        return outlook.sync_inbox(db)
    raise mail_imap.ImapError("Aucune boîte mail n'est configurée (Paramètres > Intégrations > Boîte mail).")
