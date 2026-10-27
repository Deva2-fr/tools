import smtplib
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_json
from app.core.db import utcnow
from app.models import Alert, AlertChannel
from app.services import integrations

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
ICONS = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


def create_alert(
    db: Session,
    kind: str,
    severity: str,
    title: str,
    message: str = "",
    project_id: int | None = None,
    dedupe_key: str | None = None,
    cooldown_hours: float = 24,
) -> Alert | None:
    """Crée une alerte et l'envoie. Évite les doublons pendant `cooldown_hours`."""
    if dedupe_key:
        since = utcnow() - timedelta(hours=cooldown_hours)
        existing = db.scalar(
            select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.created_at >= since).limit(1)
        )
        if existing:
            return None
    alert = Alert(
        kind=kind,
        severity=severity,
        title=title,
        message=message,
        project_id=project_id,
        dedupe_key=dedupe_key,
    )
    db.add(alert)
    db.commit()
    dispatch(db, alert)
    return alert


def dispatch(db: Session, alert: Alert) -> None:
    results = []
    channels = db.scalars(select(AlertChannel).where(AlertChannel.enabled.is_(True))).all()
    for ch in channels:
        if SEVERITY_RANK[alert.severity] < SEVERITY_RANK.get(ch.min_severity, 1):
            continue
        try:
            send_to_channel(db, ch, alert.title, alert.message, alert.severity)
            results.append(f"{ch.name}: ok")
        except Exception as exc:  # une panne de canal ne doit jamais bloquer le reste
            results.append(f"{ch.name}: ÉCHEC ({exc.__class__.__name__}: {str(exc)[:120]})")
    alert.delivery = "\n".join(results)
    db.commit()


def send_to_channel(db: Session, ch: AlertChannel, title: str, message: str, severity: str) -> None:
    cfg = decrypt_json(ch.config_enc)
    text = f"{ICONS.get(severity, '')} {title}\n{message}".strip()
    if ch.type == "email":
        _send_email(db, cfg["to"], f"[Deva2 Hub] {title}", message or title)
    elif ch.type == "slack":
        _post(cfg["webhook_url"], {"text": text})
    elif ch.type == "discord":
        _post(cfg["webhook_url"], {"content": text[:1900]})
    elif ch.type == "telegram":
        _post(
            f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
            {"chat_id": cfg["chat_id"], "text": text},
        )
    elif ch.type == "webhook":
        _post(cfg["url"], {"title": title, "message": message, "severity": severity})
    else:
        raise ValueError(f"Type de canal inconnu : {ch.type}")


def _post(url: str, payload: dict) -> None:
    r = httpx.post(url, json=payload, timeout=10)
    r.raise_for_status()


def _send_email(db: Session, to: str, subject: str, body: str) -> None:
    host = integrations.get(db, "smtp_host")
    if not host:
        raise RuntimeError("SMTP non configuré (Paramètres > Intégrations > E-mail)")
    port = int(integrations.get(db, "smtp_port", "587"))
    user = integrations.get(db, "smtp_user")
    password = integrations.get(db, "smtp_password")
    sender = integrations.get(db, "smtp_from") or user
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_cls(host, port, timeout=15) as smtp:
        if port != 465:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
