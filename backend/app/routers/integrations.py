import smtplib

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import admin_user
from app.models import User
from app.routers.auth import audit
from app.services import google_drive, integrations, outlook, qonto

router = APIRouter(prefix="/integrations", tags=["intégrations"])


class ValueIn(BaseModel):
    value: str


@router.get("")
def list_fields(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    out = []
    for f in integrations.FIELDS:
        if f.internal:
            continue
        current = integrations.get(db, f.key)
        out.append(
            {
                "key": f.key,
                "label": f.label,
                "group": f.group,
                "help": f.help,
                "secret": f.secret,
                "multiline": f.multiline,
                "is_set": bool(current),
                "value": "" if f.secret else current,  # les secrets ne sont JAMAIS renvoyés
            }
        )
    return out


@router.put("/{key}")
def set_field(key: str, body: ValueIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    field = integrations.BY_KEY.get(key)
    if not field or field.internal:
        raise HTTPException(404, "Paramètre inconnu")
    integrations.put(db, key, body.value.strip())
    audit(db, admin.email, "integration_updated", key)
    return {"ok": True}


@router.post("/test/{service}")
def test_service(service: str, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        if service == "google":
            return {"message": google_drive.test_connection(db)}
        if service == "outlook":
            outlook.access_token(db)
            return {"message": f"Connexion OK ({integrations.get(db, 'microsoft_mailbox')})"}
        if service == "smtp":
            host, port = integrations.get(db, "smtp_host"), int(integrations.get(db, "smtp_port", "587"))
            if not host:
                raise RuntimeError("Serveur SMTP non renseigné")
            cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
            with cls(host, port, timeout=15) as s:
                if port != 465:
                    s.starttls()
                if user := integrations.get(db, "smtp_user"):
                    s.login(user, integrations.get(db, "smtp_password"))
            return {"message": "Connexion SMTP OK"}
        if service == "qonto":
            return {"message": qonto.test_connection(db)}
        if service == "nvd":
            headers = {"apiKey": k} if (k := integrations.get(db, "nvd_api_key")) else {}
            r = httpx.get(
                "https://services.nvd.nist.gov/rest/json/cves/2.0",
                params={"resultsPerPage": 1},
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            return {"message": "NVD accessible" + (" avec clé API" if headers else " (sans clé : plus lent)")}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(404, "Service inconnu")
