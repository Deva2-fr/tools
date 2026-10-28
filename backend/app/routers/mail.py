from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings, public_base_url
from app.core.crypto import encrypt
from app.core.db import get_db, utcnow
from app.core.security import admin_user, current_user
from app.models import Mailbox, MailMessage, User
from app.routers.auth import audit
from app.schemas import MailboxIn, MailOut, MailTagIn
from app.services import integrations, mail_imap, mailbox, outlook

router = APIRouter(prefix="/mail", tags=["mails"])


def _out(m: MailMessage) -> MailOut:
    return MailOut(
        id=m.id,
        mailbox_id=m.mailbox_id,
        subject=m.subject,
        sender_name=m.sender_name,
        sender_email=m.sender_email,
        preview=m.preview,
        web_link=m.web_link,
        received_at=m.received_at,
        is_read=m.is_read,
        tag=outlook.display_tag(m),
    )


TODO_TAGS = ("a_repondre", "urgent")


def _box_out(b: Mailbox, todo: int = 0) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "host": b.host,
        "port": b.port,
        "username": b.username,
        "has_password": bool(b.password_enc),  # le mot de passe n'est jamais renvoyé
        "sent_folder": b.sent_folder,
        "webmail_url": b.webmail_url,
        "position": b.position,
        "active": b.active,
        "last_synced_at": b.last_synced_at,
        "last_error": b.last_error,
        "todo": todo,
    }


@router.get("/status", dependencies=[Depends(current_user)])
def status(request: Request, db: Session = Depends(get_db)):
    mailbox.migrate_legacy(db)
    todo: dict[int | None, int] = {}
    for m in db.scalars(select(MailMessage)):
        if outlook.display_tag(m) in TODO_TAGS:
            todo[m.mailbox_id] = todo.get(m.mailbox_id, 0) + 1
    ms = mailbox.microsoft_connected(db)
    return {
        "mailboxes": [_box_out(b, todo.get(b.id, 0)) for b in mailbox.boxes(db, active_only=True)],
        "connected": bool(ms or mailbox.boxes(db, active_only=True)),
        # Microsoft 365 (optionnel)
        "microsoft": {
            "connected": ms,
            "mailbox": integrations.get(db, "microsoft_mailbox") if ms else "",
            "todo": todo.get(None, 0) if ms else 0,
            "configured": bool(
                integrations.get(db, "microsoft_client_id")
                and integrations.get(db, "microsoft_client_secret")
            ),
            "redirect_uri": outlook.redirect_uri(request),
        },
    }


# ---------- Gestion des boîtes (administrateurs) ----------
def _box(db: Session, box_id: int) -> Mailbox:
    b = db.get(Mailbox, box_id)
    if not b:
        raise HTTPException(404, "Boîte introuvable")
    return b


def _apply(b: Mailbox, body: MailboxIn) -> None:
    for k in ("name", "host", "port", "username", "sent_folder", "webmail_url", "position", "active"):
        v = getattr(body, k)
        setattr(b, k, v.strip() if isinstance(v, str) else v)
    if body.password:
        b.password_enc = encrypt(body.password)


@router.get("/mailboxes", dependencies=[Depends(admin_user)])
def list_mailboxes(db: Session = Depends(get_db)):
    mailbox.migrate_legacy(db)
    return [_box_out(b) for b in mailbox.boxes(db)]


@router.post("/mailboxes", status_code=201)
def create_mailbox(body: MailboxIn, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    if not body.password:
        raise HTTPException(400, "Le mot de passe de la boîte est requis.")
    b = Mailbox()
    _apply(b, body)
    db.add(b)
    db.commit()
    audit(db, admin.email, "mailbox_created", b.name)
    return _box_out(b)


@router.put("/mailboxes/{box_id}")
def update_mailbox(
    box_id: int, body: MailboxIn, db: Session = Depends(get_db), admin: User = Depends(admin_user)
):
    b = _box(db, box_id)
    _apply(b, body)
    db.commit()
    audit(db, admin.email, "mailbox_updated", b.name)
    return _box_out(b)


@router.delete("/mailboxes/{box_id}", status_code=204)
def delete_mailbox(box_id: int, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    b = _box(db, box_id)
    name = b.name
    mailbox.delete_box(db, b)
    audit(db, admin.email, "mailbox_deleted", name)


@router.post("/mailboxes/{box_id}/test", dependencies=[Depends(admin_user)])
def test_mailbox(box_id: int, db: Session = Depends(get_db)):
    try:
        return {"message": mail_imap.test_connection(_box(db, box_id))}
    except mail_imap.ImapError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/connect")
def connect(request: Request, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not integrations.get(db, "microsoft_client_id"):
        raise HTTPException(400, "Renseignez d'abord l'application Microsoft (Paramètres > Intégrations)")
    state = jwt.encode(
        {"uid": admin.id, "exp": utcnow().timestamp() + 600}, get_settings().secret_key, algorithm="HS256"
    )
    return {"url": outlook.authorize_url(db, state, request)}


@router.get("/callback")
def callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    base = public_base_url(request)
    try:
        data = jwt.decode(state, get_settings().secret_key, algorithms=["HS256"])
        if data["uid"] != user.id:
            raise ValueError("utilisateur différent")
        if error or not code:
            raise ValueError(error or "code manquant")
        outlook.exchange_code(db, code, request)
        outlook.sync_inbox(db)
    except Exception as exc:
        return RedirectResponse(f"{base}/mail?error={str(exc)[:150]}")
    return RedirectResponse(f"{base}/mail?connected=1")


@router.post("/disconnect", dependencies=[Depends(admin_user)])
def disconnect(db: Session = Depends(get_db)):
    integrations.put(db, "microsoft_refresh_token", "")
    integrations.put(db, "microsoft_mailbox", "")
    return {"ok": True}


@router.post("/sync", dependencies=[Depends(current_user)])
def sync(mailbox_id: int | None = None, db: Session = Depends(get_db)):
    """Sans paramètre : toutes les boîtes. Avec ?mailbox_id= : seulement celle-ci."""
    if mailbox_id is not None:
        try:
            return {"new": mailbox.sync_one(db, _box(db, mailbox_id)), "errors": []}
        except mail_imap.ImapError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"Synchronisation impossible : {exc}") from exc
    sources = len(mailbox.boxes(db, active_only=True)) + mailbox.microsoft_connected(db)
    if not sources:
        raise HTTPException(400, "Aucune boîte mail n'est configurée (Paramètres > Boîtes mail).")
    res = mailbox.sync_all(db)
    if len(res["errors"]) >= sources:  # toutes les boîtes ont échoué
        raise HTTPException(400, " · ".join(res["errors"]))
    return res


FILTERS = {
    "todo": ("a_repondre", "urgent"),
    "repondu": ("repondu", "fait"),
    "info": ("info", "ignore"),
}


@router.get("/messages", response_model=list[MailOut], dependencies=[Depends(current_user)])
def messages(
    response: Response,
    tag: str | None = None,
    box: str = Query("", alias="mailbox"),
    filter: str = "all",
    q: str = "",
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """`mailbox` : id d'une boîte, « microsoft », ou vide pour toutes. `filter` : todo | repondu | info | all.
    En-têtes : X-Total-Count (après filtre) et X-Counts (nombre par filtre, pour les boutons)."""
    stmt = select(MailMessage).order_by(MailMessage.received_at.desc())
    if box == "microsoft":
        stmt = stmt.where(MailMessage.mailbox_id.is_(None))
    elif box.isdigit():
        stmt = stmt.where(MailMessage.mailbox_id == int(box))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            MailMessage.subject.ilike(like)
            | MailMessage.sender_email.ilike(like)
            | MailMessage.sender_name.ilike(like)
            | MailMessage.preview.ilike(like)
        )
    out = [_out(m) for m in db.scalars(stmt)]
    counts = {k: sum(m.tag in tags for m in out) for k, tags in FILTERS.items()} | {"all": len(out)}
    if tag:
        out = [m for m in out if m.tag == tag]
    elif filter in FILTERS:
        out = [m for m in out if m.tag in FILTERS[filter]]
    response.headers["X-Total-Count"] = str(len(out))
    response.headers["X-Counts"] = ",".join(f"{k}={v}" for k, v in counts.items())
    return out[max(offset, 0) : max(offset, 0) + min(max(limit, 1), 500)]


def _message(db: Session, message_id: int) -> MailMessage:
    m = db.get(MailMessage, message_id)
    if not m:
        raise HTTPException(404)
    return m


def _raw(db: Session, m: MailMessage) -> bytes:
    box = db.get(Mailbox, m.mailbox_id) if m.mailbox_id else None
    if not box:
        raise HTTPException(404, "Boîte mail supprimée.")
    message_id = m.graph_id.split(":", 2)[-1]
    try:
        uid, raw = mail_imap.fetch_raw(box, m.imap_uid, message_id)
    except mail_imap.ImapError as exc:
        raise HTTPException(400, str(exc)) from exc
    if uid != m.imap_uid:
        m.imap_uid = uid
        db.commit()
    return raw


@router.get("/messages/{message_id}/content", dependencies=[Depends(current_user)])
def content(message_id: int, db: Session = Depends(get_db)):
    """Mail complet, lu à la demande sur le serveur (rien n'est stocké ni marqué comme lu)."""
    m = _message(db, message_id)
    if m.mailbox_id is None:  # Microsoft 365
        try:
            data = outlook.message_content(db, m.graph_id)
        except Exception as exc:
            raise HTTPException(502, f"Lecture impossible : {exc}") from exc
    else:
        data = mail_imap.full_content(_raw(db, m))
    return data | {"id": m.id, "tag": outlook.display_tag(m), "web_link": m.web_link}


@router.get("/messages/{message_id}/attachments/{index}", dependencies=[Depends(current_user)])
def attachment(message_id: int, index: int, db: Session = Depends(get_db)):
    m = _message(db, message_id)
    try:
        name, ctype, data = mail_imap.attachment(_raw(db, m), index)
    except mail_imap.ImapError as exc:
        raise HTTPException(404, str(exc)) from exc
    # Toujours en téléchargement (jamais affiché dans le Hub) : une pièce jointe peut être piégée.
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.put("/messages/{message_id}/tag", response_model=MailOut, dependencies=[Depends(current_user)])
def set_tag(message_id: int, body: MailTagIn, db: Session = Depends(get_db)):
    m = db.get(MailMessage, message_id)
    if not m:
        raise HTTPException(404)
    m.manual_tag = None if body.tag == "auto" else body.tag
    db.commit()
    return _out(m)
