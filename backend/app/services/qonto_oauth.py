"""Connexion OAuth à Qonto : nécessaire pour les devis (lecture et création), que la clé API
simple ne permet pas. Application à déclarer sur le portail développeur Qonto (developers.qonto.com).
"""

from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import integrations

AUTH_URL = "https://oauth.qonto.com/oauth2/auth"
TOKEN_URL = "https://oauth.qonto.com/oauth2/token"
API_URL = "https://thirdparty.qonto.com/v2"
SCOPES = "offline_access organization.read client.read client.write client_invoices.read client_invoice.write"


class QontoOAuthError(RuntimeError):
    """Erreur affichable telle quelle."""


def redirect_uri() -> str:
    return get_settings().base_url.rstrip("/") + "/api/billing/qonto/oauth/callback"


def is_configured(db: Session) -> bool:
    return bool(
        integrations.get(db, "qonto_oauth_client_id") and integrations.get(db, "qonto_oauth_client_secret")
    )


def is_connected(db: Session) -> bool:
    return bool(integrations.get(db, "qonto_oauth_refresh_token"))


def authorize_url(db: Session, state: str) -> str:
    if not is_configured(db):
        raise QontoOAuthError(
            "Renseignez d'abord l'application Qonto (Paramètres > Intégrations > Banque Qonto)."
        )
    q = urlencode(
        {
            "client_id": integrations.get(db, "qonto_oauth_client_id"),
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{q}"


def _token(db: Session, data: dict) -> dict:
    body = {
        "client_id": integrations.get(db, "qonto_oauth_client_id"),
        "client_secret": integrations.get(db, "qonto_oauth_client_secret"),
        **data,
    }
    try:
        r = httpx.post(TOKEN_URL, data=body, timeout=20)
    except httpx.HTTPError as exc:
        raise QontoOAuthError("Qonto est injoignable pour le moment.") from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("error_description") or r.json().get("error") or r.text
        except ValueError:
            detail = r.text
        raise QontoOAuthError(f"Qonto a refusé la connexion : {str(detail)[:200]}")
    tok = r.json()
    # Qonto renouvelle le jeton de rafraîchissement : on garde toujours le dernier.
    if tok.get("refresh_token"):
        integrations.put(db, "qonto_oauth_refresh_token", tok["refresh_token"])
    return tok


def exchange_code(db: Session, code: str) -> None:
    _token(db, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})


def access_token(db: Session) -> str:
    refresh = integrations.get(db, "qonto_oauth_refresh_token")
    if not refresh:
        raise QontoOAuthError(
            "Qonto n'est pas connecté pour les devis : Paramètres > Intégrations > Banque Qonto > Se connecter avec Qonto."
        )
    return _token(db, {"grant_type": "refresh_token", "refresh_token": refresh})["access_token"]


def client(db: Session) -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=30, headers={"Authorization": f"Bearer {access_token(db)}"})


def disconnect(db: Session) -> None:
    integrations.put(db, "qonto_oauth_refresh_token", "")
