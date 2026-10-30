"""Appels à l'IA (Gemini, API REST de Google AI Studio) : un seul point d'entrée pour tout le Hub.

`generate` (synchrone) et `agenerate` (asynchrone, pour le copilote) prennent un historique au format
Gemini, des outils éventuels et/ou un schéma JSON, et renvoient un `Result` normalisé : texte, appels
d'outils demandés, raison de fin et jetons consommés. Les erreurs sont des `LLMError` lisibles.
"""

import base64
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.services import integrations

API = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT = 120
# Estimation de coût (≈ €) par jeton pour Gemini Flash : sert au budget mensuel, pas à la facturation.
PRICE_IN, PRICE_OUT = 0.30 / 1_000_000, 2.50 / 1_000_000


class LLMError(RuntimeError):
    """Erreur affichable telle quelle."""


@dataclass
class Call:
    name: str
    args: dict


@dataclass
class Result:
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    parts: list[dict] = field(default_factory=list)  # parts brutes du modèle, à renvoyer dans l'historique
    finish: str = "stop"  # stop | max_tokens | refusal | error
    tokens_in: int = 0
    tokens_out: int = 0


def configured(db: Session) -> bool:
    return bool(integrations.get(db, "gemini_api_key"))


def model_name(db: Session) -> str:
    return (integrations.get(db, "gemini_model") or "").strip() or DEFAULT_MODEL


def text_part(text: str) -> dict:
    return {"text": text}


def file_part(data: bytes, mime: str) -> dict:
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}


def user(*parts: dict | str) -> dict:
    return {"role": "user", "parts": [text_part(p) if isinstance(p, str) else p for p in parts]}


def model(parts: list[dict]) -> dict:
    return {"role": "model", "parts": parts}


def tool_results(results: list[tuple[str, str, bool]]) -> dict:
    """Résultats d'outils (nom, texte, est_une_erreur) renvoyés au modèle, dans l'ordre des appels."""
    return {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": n, "response": {"error": t} if err else {"result": t}}}
            for n, t, err in results
        ],
    }


_TYPES = {
    "object": "OBJECT",
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "array": "ARRAY",
    "boolean": "BOOLEAN",
}


def clean_schema(node):
    """Schéma JSON → sous-ensemble compris par Gemini (types en majuscules, sans additionalProperties,
    `enum` réservé aux chaînes)."""
    if isinstance(node, list):
        return [clean_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in ("additionalProperties", "$schema", "title"):
            continue
        out[k] = clean_schema(v) if k in ("properties", "items") or isinstance(v, (dict, list)) else v
    if isinstance(out.get("type"), str):
        out["type"] = _TYPES.get(out["type"], out["type"].upper())
    if "enum" in out and out.get("type") != "STRING":
        del out["enum"]  # les valeurs autorisées sont revérifiées côté serveur
    if "properties" in out and isinstance(out["properties"], dict):
        out["properties"] = {k: clean_schema(v) for k, v in out["properties"].items()}
    return out


def _body(
    system: str, contents: list[dict], tools: list[dict] | None, schema: dict | None, max_tokens: int
) -> dict:
    body: dict = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        body["systemInstruction"] = {"parts": [text_part(system)]}
    if tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": clean_schema(t["input_schema"]),
                    }
                    for t in tools
                ]
            }
        ]
    elif schema:  # sortie JSON structurée (non combinable avec les outils)
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = clean_schema(schema)
    return body


def _error(status: int, data: dict, model_id: str) -> LLMError:
    msg = ""
    if isinstance(data, dict):
        msg = str((data.get("error") or {}).get("message") or "")
    if status in (401, 403) or "API key not valid" in msg or "API_KEY_INVALID" in msg:
        return LLMError(
            "La clé API Gemini est refusée : vérifiez-la dans Paramètres > Intégrations > Assistant IA."
        )
    if status == 404:
        return LLMError(f"Modèle Gemini « {model_id} » introuvable : vérifiez le réglage dans Paramètres.")
    if status == 429:
        return LLMError("Quota ou limite de requêtes Gemini atteint : réessayez dans une minute.")
    if status >= 500:
        return LLMError("Le service Gemini est momentanément indisponible : réessayez.")
    return LLMError(f"Gemini a refusé la demande ({status}) : {msg[:160] or 'requête invalide'}")


def _parse(data: dict) -> Result:
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        return Result(finish="refusal")
    usage = data.get("usageMetadata") or {}
    res = Result(
        tokens_in=int(usage.get("promptTokenCount") or 0),
        # Les jetons de réflexion (modèles « thinking ») sont facturés comme du texte généré.
        tokens_out=int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0),
    )
    cands = data.get("candidates") or []
    if not cands:
        res.finish = "error"
        return res
    cand = cands[0]
    res.parts = list((cand.get("content") or {}).get("parts") or [])
    res.text = "".join(p["text"] for p in res.parts if "text" in p and not p.get("thought"))
    res.calls = [
        Call(p["functionCall"]["name"], dict(p["functionCall"].get("args") or {}))
        for p in res.parts
        if "functionCall" in p
    ]
    reason = cand.get("finishReason") or "STOP"
    if reason == "MAX_TOKENS":
        res.finish = "max_tokens"
    elif reason in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"):
        res.finish = "refusal"
    elif reason in ("MALFORMED_FUNCTION_CALL", "OTHER", "UNEXPECTED_TOOL_CALL"):
        res.finish = "error"
    return res


def _request(db: Session, system, contents, tools, schema, max_tokens) -> tuple[str, dict, dict, str]:
    key = integrations.get(db, "gemini_api_key")
    if not key:
        raise LLMError("Renseignez la clé API Gemini (Paramètres > Intégrations > Assistant IA).")
    model_id = model_name(db)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    return (
        f"{API}/{model_id}:generateContent",
        headers,
        _body(system, contents, tools, schema, max_tokens),
        model_id,
    )


def _finish(resp: httpx.Response, model_id: str) -> Result:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        raise _error(resp.status_code, data, model_id)
    return _parse(data)


def generate(
    db: Session,
    contents: list[dict],
    *,
    system: str = "",
    tools: list[dict] | None = None,
    schema: dict | None = None,
    max_tokens: int = 8000,
    transport: httpx.BaseTransport | None = None,
) -> Result:
    url, headers, body, model_id = _request(db, system, contents, tools, schema, max_tokens)
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as c:
            return _finish(c.post(url, headers=headers, json=body), model_id)
    except httpx.HTTPError as exc:
        raise LLMError("Le service d'IA est injoignable pour le moment.") from exc


async def agenerate(
    db: Session,
    contents: list[dict],
    *,
    system: str = "",
    tools: list[dict] | None = None,
    schema: dict | None = None,
    max_tokens: int = 8000,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Result:
    url, headers, body, model_id = _request(db, system, contents, tools, schema, max_tokens)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as c:
            return _finish(await c.post(url, headers=headers, json=body), model_id)
    except httpx.HTTPError as exc:
        raise LLMError("Le service d'IA est injoignable pour le moment.") from exc


def test_connection(db: Session) -> str:
    res = generate(db, [user("Réponds uniquement : OK")], max_tokens=50)
    if res.finish in ("refusal", "error"):
        raise LLMError("Gemini n'a pas pu répondre : vérifiez le modèle choisi.")
    return f"Connexion OK – modèle {model_name(db)} prêt."
