import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.security import admin_user, current_user
from app.models import MailMessage, User
from app.schemas import MailOut, MailTagIn
from app.services import integrations, mail_imap, mailbox, outlook

router = APIRouter(prefix="/mail", tags=["mails"])


def _out(m: MailMessage) -> MailOut:
    return MailOut(
        id=m.id,
        subject=m.subject,
        sender_name=m.sender_name,
        sender_email=m.sender_email,
        preview=m.preview,
        web_link=m.web_link,
        received_at=m.received_at,
        is_read=m.is_read,
        tag=outlook.display_tag(m),
    )


@router.get("/status", dependencies=[Depends(current_user)])
def status(db: Session = Depends(get_db)):
    kind = mailbox.provider(db)
    return {
        "provider": kind,
        "connected": kind is not None,
        "mailbox": mailbox.mailbox_address(db),
        "webmail_url": integrations.get(db, "imap_webmail_url") if kind == "imap" else "",
        # Microsoft 365 (optionnel)
        "configured": bool(
            integrations.get(db, "microsoft_client_id") and integrations.get(db, "microsoft_client_secret")
        ),
        "redirect_uri": outlook.redirect_uri(),
    }


@router.get("/connect")
def connect(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not integrations.get(db, "microsoft_client_id"):
        raise HTTPException(400, "Renseignez d'abord l'application Microsoft (Paramètres > Intégrations)")
    state = jwt.encode(
        {"uid": admin.id, "exp": utcnow().timestamp() + 600}, get_settings().secret_key, algorithm="HS256"
    )
    return {"url": outlook.authorize_url(db, state)}


@router.get("/callback")
def callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    base = get_settings().base_url.rstrip("/")
    try:
        data = jwt.decode(state, get_settings().secret_key, algorithms=["HS256"])
        if data["uid"] != user.id:
            raise ValueError("utilisateur différent")
        if error or not code:
            raise ValueError(error or "code manquant")
        outlook.exchange_code(db, code)
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
def sync(db: Session = Depends(get_db)):
    try:
        return {"new": mailbox.sync(db)}
    except mail_imap.ImapError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Synchronisation impossible : {exc}") from exc


@router.get("/messages", response_model=list[MailOut], dependencies=[Depends(current_user)])
def messages(tag: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(MailMessage).order_by(MailMessage.received_at.desc()).limit(min(limit, 500))
    ).all()
    out = [_out(m) for m in rows]
    return [m for m in out if m.tag == tag] if tag else out


@router.put("/messages/{message_id}/tag", response_model=MailOut, dependencies=[Depends(current_user)])
def set_tag(message_id: int, body: MailTagIn, db: Session = Depends(get_db)):
    m = db.get(MailMessage, message_id)
    if not m:
        raise HTTPException(404)
    m.manual_tag = None if body.tag == "auto" else body.tag
    db.commit()
    return _out(m)
