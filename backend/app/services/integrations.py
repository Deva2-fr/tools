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
        "google_output_folder_id",
        "Google Drive – ID du dossier « Note de frais »",
        "google",
        "Deva2 > Administration > Comptabilité > Note de frais : la fin de l'URL du dossier, après /folders/",
    ),
    Field("qonto_billing_synced_at", "", "qonto", internal=True),
    Field(
        "qonto_oauth_client_id",
        "Qonto – ID de l'application (OAuth, pour les devis)",
        "qonto",
        "Portail développeur Qonto > votre application > Client ID",
    ),
    Field(
        "qonto_oauth_client_secret",
        "Qonto – Secret de l'application (OAuth)",
        "qonto",
        "Portail développeur Qonto > votre application > Client secret",
        secret=True,
    ),
    Field("qonto_oauth_refresh_token", "", "qonto", secret=True, internal=True),
    Field(
        "anthropic_api_key",
        "Clé API Anthropic (Claude)",
        "ai",
        "console.anthropic.com > API Keys : copilote du Hub et amélioration des devis",
        secret=True,
    ),
    Field(
        "copilot_monthly_budget",
        "Budget mensuel du copilote (€)",
        "ai",
        "Plafond de dépense estimé par mois (tous utilisateurs). Vide = 50 €. 0 = copilote désactivé.",
    ),
    # Ma société : imprimé sur les devis, factures et notes de frais.
    Field("company_name", "Raison sociale", "company", "Ex : DEVA2"),
    Field("company_legal_form", "Forme juridique et capital", "company", "Ex : SAS au capital de 1 000 €"),
    Field("company_siret", "SIRET", "company", "14 chiffres"),
    Field("company_vat", "N° de TVA intracommunautaire", "company", "Ex : FR12345678901"),
    Field("company_address", "Adresse", "company", "Rue, code postal, ville", multiline=True),
    Field("company_email", "E-mail", "company", "Affiché sur les documents"),
    Field("company_phone", "Téléphone", "company"),
    Field("company_iban", "IBAN", "company", "Pour le paiement des factures"),
    Field("company_bic", "BIC", "company"),
    Field(
        "invoice_terms_days", "Délai de paiement (jours)", "company", "Échéance par défaut des factures : 30"
    ),
    Field(
        "invoice_legal_notes",
        "Mentions légales complémentaires",
        "company",
        "Ex : « TVA non applicable, art. 293 B du CGI »",
        multiline=True,
    ),
    Field("google_calendar_id", "", "google", internal=True),
    Field("google_calendar_name", "", "google", internal=True),
    Field("google_calendar_synced_at", "", "google", internal=True),
    Field("google_calendar_error", "", "google", internal=True),
    # Signataires des notes de frais (id d'utilisateur), réglés dans Paramètres > Intégrations.
    Field("expense_president_user_id", "", "company", internal=True),
    Field("expense_partner_user_id", "", "company", internal=True),
    Field(
        "qonto_login",
        "Qonto – Identifiant",
        "qonto",
        "Qonto > Paramètres > Intégrations et partenariats > Clé API : « Identifiant »",
    ),
    Field(
        "qonto_secret_key",
        "Qonto – Clé secrète",
        "qonto",
        "Même écran : « Clé secrète ». Le Hub ne fait que lire comptes et transactions",
        secret=True,
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


def company_info(db: Session) -> dict[str, str]:
    keys = [
        "company_name",
        "company_legal_form",
        "company_siret",
        "company_vat",
        "company_address",
        "company_email",
        "company_phone",
        "company_iban",
        "company_bic",
        "invoice_legal_notes",
    ]
    return {k: get(db, k) for k in keys}


def terms_days(db: Session) -> int:
    try:
        return max(0, int(get(db, "invoice_terms_days", "30")))
    except ValueError:
        return 30
