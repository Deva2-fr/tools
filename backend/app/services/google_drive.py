"""Dépôt des notes de frais (PDF) dans Google Drive via un compte de service.

Dossier cible : Deva2 > Administration > Comptabilité > Note de frais, partagé avec l'e-mail du
compte de service (rôle « Éditeur »). Un compte de service n'a pas d'espace de stockage propre :
le dossier doit se trouver dans un Drive partagé (ou appartenir à un compte Google Workspace qui
autorise ce dépôt).
"""

import json
import time

import httpx
import jwt
from sqlalchemy.orm import Session

from app.services import integrations

SCOPES = "https://www.googleapis.com/auth/drive"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleNotConfigured(RuntimeError):
    pass


class DriveError(RuntimeError):
    """Erreur affichable telle quelle à l'utilisateur."""


def is_configured(db: Session) -> bool:
    return bool(
        integrations.get(db, "google_service_account_json")
        and integrations.get(db, "google_output_folder_id")
    )


def _service_account(db: Session) -> dict:
    raw = integrations.get(db, "google_service_account_json")
    if not raw:
        raise GoogleNotConfigured("Google non configuré (Paramètres > Intégrations > Google Drive)")
    try:
        info = json.loads(raw)
        info["client_email"], info["private_key"], info["token_uri"]  # noqa: B018 - champs requis
    except (KeyError, ValueError, TypeError) as exc:
        raise GoogleNotConfigured("Le JSON du compte de service est invalide") from exc
    return info


def _access_token(db: Session) -> str:
    info = _service_account(db)
    now = int(time.time())
    try:
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
    except ValueError as exc:
        raise GoogleNotConfigured("La clé privée du compte de service est invalide") from exc
    try:
        r = httpx.post(
            info["token_uri"],
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise DriveError("Google est injoignable pour le moment.") from exc
    if r.status_code >= 400:
        raise DriveError(f"Google a refusé l'authentification : {r.text[:200]}")
    return r.json()["access_token"]


def _folder_id(db: Session) -> str:
    folder = integrations.get(db, "google_output_folder_id").strip()
    if not folder:
        raise GoogleNotConfigured(
            "ID du dossier Drive « Note de frais » manquant (Paramètres > Intégrations)"
        )
    # On accepte aussi l'URL complète du dossier.
    if "/folders/" in folder:
        folder = folder.split("/folders/", 1)[1].split("?")[0].split("/")[0]
    return folder


def _explain(r: httpx.Response, email: str) -> DriveError:
    text = r.text
    if r.status_code == 404:
        return DriveError(
            f"Dossier Drive introuvable : partagez « Note de frais » avec {email} (rôle Éditeur)."
        )
    if r.status_code == 403 and "storageQuota" in text:
        return DriveError(
            "Le compte de service n'a pas d'espace de stockage : placez le dossier « Note de frais » "
            "dans un Drive partagé et ajoutez-y le compte de service comme Éditeur (Gestionnaire de contenu)."
        )
    if r.status_code == 403:
        return DriveError(f"Accès refusé au dossier : donnez le rôle Éditeur à {email}.")
    return DriveError(f"Erreur Google Drive ({r.status_code}) : {text[:200]}")


def upload_pdf(db: Session, name: str, content: bytes, file_id: str = "") -> dict:
    """Dépose (ou remplace, si file_id est connu) le PDF dans le dossier. Renvoie {id, webViewLink}."""
    folder = _folder_id(db)
    email = _service_account(db)["client_email"]
    headers = {"Authorization": f"Bearer {_access_token(db)}"}
    params = {"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink"}
    with httpx.Client(headers=headers, timeout=60) as c:
        try:
            if file_id:
                # Nouvelle version du même fichier : le lien partagé reste identique.
                r = c.patch(
                    f"{UPLOAD}/{file_id}",
                    params={**params, "uploadType": "media"},
                    content=content,
                    headers={"Content-Type": "application/pdf"},
                )
                if r.status_code != 404:
                    if r.status_code >= 400:
                        raise _explain(r, email)
                    c.patch(
                        f"{DRIVE}/files/{file_id}",
                        params={"supportsAllDrives": "true"},
                        json={"name": name},
                    )
                    return r.json()
            meta = json.dumps({"name": name, "parents": [folder], "mimeType": "application/pdf"})
            r = c.post(
                UPLOAD,
                params=params,
                files={
                    "metadata": (None, meta, "application/json; charset=UTF-8"),
                    "file": (name, content, "application/pdf"),
                },
            )
        except httpx.HTTPError as exc:
            raise DriveError("Google Drive est injoignable pour le moment.") from exc
    if r.status_code >= 400:
        raise _explain(r, email)
    return r.json()


def test_connection(db: Session) -> str:
    folder = _folder_id(db)
    email = _service_account(db)["client_email"]
    r = httpx.get(
        f"{DRIVE}/files/{folder}",
        params={"fields": "name,mimeType,driveId,capabilities(canAddChildren)", "supportsAllDrives": "true"},
        headers={"Authorization": f"Bearer {_access_token(db)}"},
        timeout=20,
    )
    if r.status_code >= 400:
        raise _explain(r, email)
    f = r.json()
    if f.get("mimeType") != FOLDER_MIME:
        raise DriveError("Cet ID ne correspond pas à un dossier Drive.")
    if not (f.get("capabilities") or {}).get("canAddChildren"):
        raise DriveError(
            f"Dossier « {f['name']} » trouvé, mais en lecture seule : donnez le rôle Éditeur à {email}."
        )
    note = (
        ""
        if f.get("driveId")
        else " Attention : il n'est pas dans un Drive partagé, le dépôt peut être refusé (quota du compte de service)."
    )
    return f"Connexion OK – les notes de frais seront déposées dans « {f['name']} ».{note}"
