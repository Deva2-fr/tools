from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_json, encrypt_json
from app.core.db import get_db
from app.core.security import admin_user, current_user, safe_equal
from app.models import Alert, AlertChannel, Project
from app.schemas import AlertOut, ChannelIn, ChannelOut
from app.services.alerts import create_alert, send_to_channel

router = APIRouter(tags=["alertes"])
REQUIRED = {
    "email": ["to"],
    "slack": ["webhook_url"],
    "discord": ["webhook_url"],
    "telegram": ["bot_token", "chat_id"],
    "webhook": ["url"],
}


@router.get("/alerts", response_model=list[AlertOut], dependencies=[Depends(current_user)])
def list_alerts(only_open: bool = False, limit: int = 200, db: Session = Depends(get_db)):
    q = select(Alert).order_by(Alert.id.desc()).limit(min(limit, 500))
    if only_open:
        q = q.where(Alert.acknowledged.is_(False))
    return db.scalars(q).all()


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut, dependencies=[Depends(current_user)])
def ack(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404)
    a.acknowledged = True
    db.commit()
    return a


@router.post("/alerts/ack-all", dependencies=[Depends(current_user)])
def ack_all(db: Session = Depends(get_db)):
    db.execute(update(Alert).where(Alert.acknowledged.is_(False)).values(acknowledged=True))
    db.commit()
    return {"ok": True}


# ----- canaux de notification (réservés aux admins) -----
def _channel_out(c: AlertChannel) -> ChannelOut:
    return ChannelOut(
        id=c.id,
        name=c.name,
        type=c.type,
        min_severity=c.min_severity,
        enabled=c.enabled,
        config_keys=sorted(decrypt_json(c.config_enc).keys()),
    )


def _check_config(body: ChannelIn) -> None:
    missing = [k for k in REQUIRED[body.type] if not body.config.get(k, "").strip()]
    if missing:
        raise HTTPException(422, f"Champs manquants : {', '.join(missing)}")


@router.get("/channels", response_model=list[ChannelOut], dependencies=[Depends(admin_user)])
def list_channels(db: Session = Depends(get_db)):
    return [_channel_out(c) for c in db.scalars(select(AlertChannel).order_by(AlertChannel.id))]


@router.post("/channels", response_model=ChannelOut, status_code=201, dependencies=[Depends(admin_user)])
def create_channel(body: ChannelIn, db: Session = Depends(get_db)):
    _check_config(body)
    c = AlertChannel(
        name=body.name,
        type=body.type,
        min_severity=body.min_severity,
        enabled=body.enabled,
        config_enc=encrypt_json(body.config),
    )
    db.add(c)
    db.commit()
    return _channel_out(c)


@router.put("/channels/{channel_id}", response_model=ChannelOut, dependencies=[Depends(admin_user)])
def update_channel(channel_id: int, body: ChannelIn, db: Session = Depends(get_db)):
    c = db.get(AlertChannel, channel_id)
    if not c:
        raise HTTPException(404)
    # Les valeurs laissées vides conservent l'ancien secret (le front ne les reçoit jamais).
    config = decrypt_json(c.config_enc)
    config.update({k: v for k, v in body.config.items() if v.strip()})
    _check_config(body.model_copy(update={"config": config}))
    c.name, c.type, c.min_severity, c.enabled = body.name, body.type, body.min_severity, body.enabled
    c.config_enc = encrypt_json(config)
    db.commit()
    return _channel_out(c)


@router.delete("/channels/{channel_id}", status_code=204, dependencies=[Depends(admin_user)])
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    c = db.get(AlertChannel, channel_id)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()


@router.post("/channels/{channel_id}/test", dependencies=[Depends(admin_user)])
def test_channel(channel_id: int, db: Session = Depends(get_db)):
    c = db.get(AlertChannel, channel_id)
    if not c:
        raise HTTPException(404)
    try:
        send_to_channel(db, c, "Test Deva2 Hub", "Si vous lisez ceci, ce canal fonctionne 🎉", "info")
    except Exception as exc:
        raise HTTPException(502, f"Échec de l'envoi : {exc}") from exc
    return {"ok": True}


# ----- webhook pour outils externes (Uptime Kuma, CrowdSec, fail2ban, scripts…) -----
class SecurityEvent(BaseModel):
    title: str
    message: str = ""
    severity: str = "warning"
    project: str | None = None  # nom du projet concerné (optionnel)


@router.post("/webhooks/security")
def security_webhook(
    body: SecurityEvent, db: Session = Depends(get_db), x_webhook_token: str = Header(default="")
):
    if not safe_equal(get_settings().webhook_token, x_webhook_token):
        raise HTTPException(401, "Jeton invalide")
    project = db.scalar(select(Project).where(Project.name == body.project)) if body.project else None
    severity = body.severity if body.severity in ("info", "warning", "critical") else "warning"
    alert = create_alert(
        db, "attack", severity, body.title[:300], body.message[:2000], project.id if project else None
    )
    return {"id": alert.id if alert else None}
