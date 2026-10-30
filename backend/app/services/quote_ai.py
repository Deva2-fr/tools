"""Amélioration d'un devis par l'IA (Gemini) : intitulés, découpage des lignes, conditions.

La proposition n'est jamais enregistrée directement : l'interface l'affiche, l'utilisateur
l'applique (ou non) puis enregistre lui-même. Les prix ne sont modifiés que si on le demande.
"""

import json

from sqlalchemy.orm import Session

from app.models import BillingDoc, Company
from app.services import integrations, llm

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
    return llm.configured(db)


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
) -> dict:
    """Renvoie {title, lines, notes, changes} : une proposition, non enregistrée."""
    try:
        res = llm.generate(
            db,
            [llm.user(_payload(db, doc, lines, title, notes, instructions))],
            system=SYSTEM,
            schema=SCHEMA,
            max_tokens=16000,
        )
    except llm.LLMError as exc:
        raise AIError(str(exc)) from exc
    if res.finish == "refusal":
        raise AIError("L'IA a refusé de traiter ce devis. Reformulez la consigne.")
    if res.finish == "max_tokens":
        raise AIError("Le devis est trop long pour être amélioré en une fois.")
    try:
        data = json.loads(res.text)
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
        return llm.test_connection(db)
    except llm.LLMError as exc:
        raise AIError(str(exc)) from exc
