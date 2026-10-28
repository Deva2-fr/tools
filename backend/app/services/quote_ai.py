"""Amélioration d'un devis par l'IA (Claude) : intitulés, découpage des lignes, conditions.

La proposition n'est jamais enregistrée directement : l'interface l'affiche, l'utilisateur
l'applique (ou non) puis enregistre lui-même. Les prix ne sont modifiés que si on le demande.
"""

import json

import anthropic
from sqlalchemy.orm import Session

from app.models import BillingDoc, Company
from app.services import integrations

MODEL = "claude-opus-5-5"
VAT_RATES = [20, 10, 5.5, 2.1, 0]

SYSTEM = """Tu aides une agence web française (Deva2) à rédiger des devis clairs et professionnels.
Tu reçois un devis (objet, lignes, notes) et éventuellement une consigne de l'utilisateur.

Règles :
- Français professionnel, vouvoiement, sans jargon inutile. Chaque ligne commence par un intitulé
  court et explicite, suivi si utile d'une précision sur le périmètre (ce qui est inclus).
- Ne change JAMAIS un prix unitaire, une quantité ou un taux de TVA, sauf si la consigne le demande
  explicitement. Tu peux découper une ligne en plusieurs, mais le total HT doit rester identique.
- Si tu ajoutes une prestation qui n'existait pas, mets son prix unitaire à 0 et signale-le dans
  « changes » : c'est à l'utilisateur de fixer le prix.
- Taux de TVA autorisés : 20, 10, 5.5, 2.1 ou 0.
- « notes » : conditions utiles au client (périmètre, exclusions, délais, modalités de paiement,
  validité), en restant cohérent avec le devis. N'invente ni montant ni date précise.
- « changes » : 2 à 6 phrases courtes décrivant ce que tu as modifié, pour l'utilisateur."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "vat_rate": {"type": "number"},
                },
                "required": ["description", "quantity", "unit_price", "vat_rate"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "lines", "notes", "changes"],
    "additionalProperties": False,
}


class AIError(RuntimeError):
    """Erreur affichable telle quelle."""


def is_configured(db: Session) -> bool:
    return bool(integrations.get(db, "anthropic_api_key"))


def _client(db: Session) -> anthropic.Anthropic:
    key = integrations.get(db, "anthropic_api_key")
    if not key:
        raise AIError("Renseignez la clé API Anthropic (Paramètres > Intégrations > Assistant IA).")
    return anthropic.Anthropic(api_key=key, timeout=120, max_retries=2)


def _payload(
    db: Session, doc: BillingDoc, lines: list[dict], title: str, notes: str, instructions: str
) -> str:
    company = db.get(Company, doc.company_id) if doc.company_id else None
    me = integrations.company_info(db).get("company_name") or "Deva2"
    return json.dumps(
        {
            "emetteur": me,
            "client": company.name if company else "",
            "secteur_client": company.sector if company else "",
            "objet": title,
            "lignes": lines,
            "notes": notes,
            "consigne_utilisateur": instructions.strip() or "Améliore la clarté et la présentation du devis.",
        },
        ensure_ascii=False,
    )


def improve(
    db: Session,
    doc: BillingDoc,
    lines: list[dict],
    title: str,
    notes: str,
    instructions: str = "",
    client: anthropic.Anthropic | None = None,
) -> dict:
    """Renvoie {title, lines, notes, changes} : une proposition, non enregistrée."""
    c = client or _client(db)
    try:
        response = c.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            # Si la demande est refusée par un filtre de sécurité, l'API la rejoue sur un autre modèle.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": _payload(db, doc, lines, title, notes, instructions)}],
        )
    except anthropic.AuthenticationError as exc:
        raise AIError(
            "La clé API Anthropic est refusée : vérifiez-la dans Paramètres > Intégrations."
        ) from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIError("La clé API Anthropic n'a pas accès à ce modèle.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Trop de demandes à l'IA pour le moment : réessayez dans une minute.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Le service d'IA est injoignable pour le moment.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Erreur du service d'IA ({exc.status_code}).") from exc

    if response.stop_reason == "refusal":
        raise AIError("L'IA a refusé de traiter ce devis. Reformulez la consigne.")
    if response.stop_reason == "max_tokens":
        raise AIError("Le devis est trop long pour être amélioré en une fois.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AIError("Réponse de l'IA illisible : réessayez.") from exc

    out_lines = []
    for ln in data.get("lines", [])[:200]:
        rate = float(ln.get("vat_rate", 20))
        out_lines.append(
            {
                "description": str(ln.get("description", "")).strip()[:500] or "Prestation",
                "quantity": max(float(ln.get("quantity", 1)), 0.001),
                "unit_price": round(float(ln.get("unit_price", 0)), 2),
                "vat_rate": rate if rate in VAT_RATES else 20,
            }
        )
    return {
        "title": str(data.get("title", title)).strip()[:200],
        "lines": out_lines,
        "notes": str(data.get("notes", notes)).strip()[:5000],
        "changes": [str(x) for x in data.get("changes", [])][:10],
    }


def test_connection(db: Session) -> str:
    try:
        _client(db).models.retrieve(MODEL)
    except anthropic.AuthenticationError as exc:
        raise AIError("La clé API Anthropic est refusée.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Le service d'IA est injoignable.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Erreur du service d'IA ({exc.status_code}).") from exc
    return "Connexion OK – assistant IA prêt."
