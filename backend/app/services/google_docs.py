"""Note de frais : copie d'un modèle Google Doc, remplacement des {{champs}}, export en PDF."""

import time
from datetime import date

import httpx
import jwt
from sqlalchemy.orm import Session

from app.models import Expense
from app.services import integrations

SCOPES = "https://www.googleapis.com/auth/documents https://www.googleapis.com/auth/drive"
DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1/documents"


class GoogleNotConfigured(RuntimeError):
    pass


def _access_token(db: Session) -> str:
    import json

    raw = integrations.get(db, "google_service_account_json")
    if not raw:
        raise GoogleNotConfigured("Google non configuré (Paramètres > Intégrations > Google)")
    try:
        info = json.loads(raw)
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": info["client_email"],
                "scope": SCOPES,
                "aud": info["token_uri"],
                "iat": now,
                "exp": now + 3000,
            },
            info["private_key"],
            algorithm="RS256",
        )
    except (KeyError, ValueError) as exc:
        raise GoogleNotConfigured("Le JSON du compte de service est invalide") from exc
    r = httpx.post(
        info["token_uri"],
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google a refusé l'authentification : {r.text[:200]}")
    return r.json()["access_token"]


def fmt_money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " €"


def placeholders(e: Expense) -> dict[str, str]:
    """Champs utilisables dans le modèle Google Doc, sous la forme {{nom}}."""
    return {
        "numero": f"NDF-{e.expense_date:%Y%m}-{e.id:04d}",
        "date": f"{e.expense_date:%d/%m/%Y}",
        "nom": e.employee,
        "motif": e.reason,
        "categorie": e.category,
        "projet": e.project,
        "moyen_paiement": e.payment_method,
        "montant_ttc": fmt_money(e.amount_ttc),
        "montant_ht": fmt_money(e.amount_ht),
        "tva": fmt_money(e.amount_vat),
        "taux_tva": f"{e.vat_rate:g} %",
        "notes": e.notes,
        "date_generation": f"{date.today():%d/%m/%Y}",
    }


def replace_requests(values: dict[str, str]) -> list[dict]:
    return [
        {
            "replaceAllText": {
                "containsText": {"text": "{{" + k + "}}", "matchCase": True},
                "replaceText": v or "—",
            }
        }
        for k, v in values.items()
    ]


def generate_pdf(db: Session, expense: Expense) -> bytes:
    template = integrations.get(db, "google_template_doc_id")
    if not template:
        raise GoogleNotConfigured("ID du modèle Google Doc manquant (Paramètres > Intégrations > Google)")
    folder = integrations.get(db, "google_output_folder_id")
    headers = {"Authorization": f"Bearer {_access_token(db)}"}
    with httpx.Client(headers=headers, timeout=60) as c:
        body: dict = {"name": f"Note de frais {placeholders(expense)['numero']}"}
        if folder:
            body["parents"] = [folder]
        r = c.post(f"{DRIVE}/files/{template}/copy", params={"supportsAllDrives": "true"}, json=body)
        r.raise_for_status()
        doc_id = r.json()["id"]
        try:
            r = c.post(
                f"{DOCS}/{doc_id}:batchUpdate", json={"requests": replace_requests(placeholders(expense))}
            )
            r.raise_for_status()
            r = c.get(f"{DRIVE}/files/{doc_id}/export", params={"mimeType": "application/pdf"})
            r.raise_for_status()
            return r.content
        finally:
            # Le Doc temporaire est supprimé : le PDF est conservé par le Hub.
            c.delete(f"{DRIVE}/files/{doc_id}", params={"supportsAllDrives": "true"})


def test_connection(db: Session) -> str:
    template = integrations.get(db, "google_template_doc_id")
    headers = {"Authorization": f"Bearer {_access_token(db)}"}
    if not template:
        return "Authentification Google OK. Renseignez maintenant l'ID du modèle."
    r = httpx.get(
        f"{DRIVE}/files/{template}",
        params={"fields": "name", "supportsAllDrives": "true"},
        headers=headers,
        timeout=20,
    )
    if r.status_code == 404:
        raise RuntimeError(
            "Modèle introuvable : partagez le Doc avec l'e-mail du compte de service (Lecteur suffit)."
        )
    r.raise_for_status()
    return f"Connexion OK – modèle trouvé : « {r.json()['name']} »"
