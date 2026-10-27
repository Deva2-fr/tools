"""Stockage chiffré des identifiants des services externes (Microsoft, Google, SMTP, NVD…)."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.models import Integration


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    help: str = ""
    secret: bool = False
    multiline: bool = False
    internal: bool = False  # géré par l'application, non affiché dans le formulaire


FIELDS: list[Field] = [
    Field("smtp_host", "Serveur SMTP", "email", "Ex : smtp.office365.com ou smtp.gmail.com"),
    Field("smtp_port", "Port SMTP", "email", "587 (STARTTLS) ou 465 (SSL)"),
    Field("smtp_user", "Utilisateur SMTP", "email", "Souvent votre adresse e-mail"),
    Field(
        "smtp_password", "Mot de passe SMTP", "email", "Mot de passe d'application recommandé", secret=True
    ),
    Field("smtp_from", "Adresse d'expédition", "email", "Ex : hub@deva2.fr"),
    Field(
        "microsoft_tenant_id", "Microsoft – ID de l'annuaire (tenant)", "outlook", "Entra ID > Vue d'ensemble"
    ),
    Field(
        "microsoft_client_id",
        "Microsoft – ID de l'application (client)",
        "outlook",
        "Entra ID > Inscriptions d'applications",
    ),
    Field(
        "microsoft_client_secret",
        "Microsoft – Secret client",
        "outlook",
        "Certificats et secrets > Nouveau secret",
        secret=True,
    ),
    Field("microsoft_refresh_token", "", "outlook", secret=True, internal=True),
    Field("microsoft_mailbox", "", "outlook", internal=True),
    Field(
        "google_service_account_json",
        "Google – Clé du compte de service (JSON)",
        "google",
        "Collez tout le contenu du fichier .json",
        secret=True,
        multiline=True,
    ),
    Field(
        "google_template_doc_id",
        "Google – ID du modèle de note de frais",
        "google",
        "La partie de l'URL du Doc entre /d/ et /edit",
    ),
    Field(
        "google_output_folder_id",
        "Google – ID du dossier de sortie (optionnel)",
        "google",
        "Dossier Drive partagé avec le compte de service",
    ),
    Field(
        "nvd_api_key",
        "Clé API NVD (optionnelle)",
        "security",
        "Gratuite, accélère la veille CVE : nvd.nist.gov/developers/request-an-api-key",
        secret=True,
    ),
    Field(
        "cvss_threshold",
        "Seuil d'alerte CVSS",
        "security",
        "Alerte « grosse faille » à partir de ce score (défaut 9.0)",
    ),
]
BY_KEY = {f.key: f for f in FIELDS}


def get(db: Session, key: str, default: str = "") -> str:
    row = db.get(Integration, key)
    return decrypt(row.value_enc) if row else default


def put(db: Session, key: str, value: str) -> None:
    row = db.get(Integration, key)
    if not value:
        if row:
            db.delete(row)
    elif row:
        row.value_enc = encrypt(value)
    else:
        db.add(Integration(key=key, value_enc=encrypt(value)))
    db.commit()


def cvss_threshold(db: Session) -> float:
    try:
        return float(get(db, "cvss_threshold", "9.0"))
    except ValueError:
        return 9.0
