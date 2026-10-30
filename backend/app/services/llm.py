"""Appels à l'IA (Gemini, API REST de Google AI Studio) : un seul point d'entrée pour tout le Hub.

`generate` (synchrone) et `agenerate` (asynchrone, pour le copilote) prennent un historique au format
Gemini, des outils éventuels et/ou un schéma JSON, et renvoient un `Result` normalisé : texte, appels
d'outils demandés, raison de fin et jetons consommés. Les erreurs sont des `LLMError` lisibles.
"""

import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.services import integrations

logger = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash"  # secours si la liste des modèles de la clé est injoignable
TIMEOUT = 120
AUTO_TTL = 6 * 3600
# Estimation de coût (≈ €) par jeton pour Gemini Flash : sert au budget mensuel, pas à la facturation.
PRICE_IN, PRICE_OUT = 0.30 / 1_000_000, 2.50 / 1_000_000


class LLMError(RuntimeError):
    """Erreur affichable telle quelle."""


class NetworkError(LLMError):
    """Échec réseau vers Gemini ; `started` : des morceaux de réponse avaient déjà été reçus."""

    def __init__(self, message: str, started: bool = False):
        super().__init__(message)
        self.started = started


class Unavailable(LLMError):
    """Gemini répond 5xx (modèle surchargé, panne passagère) : on peut réessayer."""


class ModelNotFound(LLMError):
    """Le modèle demandé n'existe pas (ou plus) pour cette clé."""


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
    model: str = ""  # modèle réellement utilisé


def _timeout(read: float) -> httpx.Timeout:
    # `read` = attente maximale entre deux morceaux de réponse, pas durée totale de l'appel.
    return httpx.Timeout(connect=10, write=30, read=read, pool=10)


def _net_error(exc: httpx.HTTPError, model_id: str, read: float, started: bool, t0: float) -> NetworkError:
    """Message précis (délai ou coupure) + trace serveur ; le type exact aide à diagnostiquer."""
    took = time.monotonic() - t0
    logger.warning(
        "Gemini %s : %s (%s) après %.1fs, réponse commencée : %s",
        model_id,
        type(exc).__name__,
        exc,
        took,
        started,
    )
    if isinstance(exc, httpx.TimeoutException):
        return NetworkError(
            f"Gemini n'a pas répondu en {read:.0f} s (modèle {model_id}) : réessayez.", started
        )
    return NetworkError(f"Connexion à Gemini interrompue ({type(exc).__name__}) : réessayez.", started)


def configured(db: Session) -> bool:
    return bool(integrations.get(db, "gemini_api_key"))


_auto: dict[str, tuple[float, str]] = {}  # clé API -> (instant, modèle choisi)
_FLASH = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash$")


def available_models(key: str, transport: httpx.BaseTransport | None = None) -> list[str]:
    """Modèles de la clé qui savent générer du texte (noms sans le préfixe « models/ »)."""
    try:
        with httpx.Client(timeout=20, transport=transport) as c:
            resp = c.get(API, headers={"x-goog-api-key": key}, params={"pageSize": 200})
        data = resp.json() if resp.status_code < 400 else {}
    except (httpx.HTTPError, ValueError):
        return []
    return [
        m["name"].removeprefix("models/")
        for m in data.get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]


def pick_default(models: list[str]) -> str | None:
    """Le « flash » stable le plus récent (ni lite, ni preview, ni image, ni audio)."""
    found = [(float(m.group(1)), name) for name in models if (m := _FLASH.match(name))]
    return max(found)[1] if found else None


def auto_model(key: str, transport: httpx.BaseTransport | None = None, refresh: bool = False) -> str:
    cached = _auto.get(key)
    if cached and not refresh and time.time() - cached[0] < AUTO_TTL:
        return cached[1]
    picked = pick_default(available_models(key, transport))
    if not picked:
        return DEFAULT_MODEL  # liste injoignable : on ne mémorise pas ce repli
    _auto[key] = (time.time(), picked)
    return picked


def model_name(db: Session, transport: httpx.BaseTransport | None = None) -> str:
    chosen = (integrations.get(db, "gemini_model") or "").strip()
    if chosen:
        return chosen
    return auto_model(integrations.get(db, "gemini_api_key") or "", transport)


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


def _thinking(model_id: str) -> dict | None:
    """Réflexion courte (réponses plus rapides) : le réglage dépend de la génération du modèle."""
    if model_id.startswith("gemini-3"):
        return {"thinkingLevel": "low"}
    if model_id.startswith("gemini-2.5"):
        return {"thinkingBudget": 1024}
    return None


def _body(
    system: str,
    contents: list[dict],
    tools: list[dict] | None,
    schema: dict | None,
    max_tokens: int,
    thinking: dict | None = None,
) -> dict:
    body: dict = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
    if thinking:
        body["generationConfig"]["thinkingConfig"] = thinking
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
        return ModelNotFound(f"Modèle Gemini « {model_id} » introuvable pour cette clé.")
    if status == 429:
        return LLMError("Quota ou limite de requêtes Gemini atteint : réessayez dans une minute.")
    if status >= 500:
        detail = f" ({status} : {msg[:120]})" if msg else f" ({status})"
        return Unavailable(
            f"Gemini est surchargé ou indisponible pour le moment{detail} : réessayez dans quelques minutes, "
            "ou choisissez un autre modèle dans Paramètres."
        )
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


def _request(
    db: Session,
    system,
    contents,
    tools,
    schema,
    max_tokens,
    model_id: str | None = None,
    transport=None,
    fast: bool = False,
) -> tuple[str, dict, dict, str]:
    key = integrations.get(db, "gemini_api_key")
    if not key:
        raise LLMError("Renseignez la clé API Gemini (Paramètres > Intégrations > Assistant IA).")
    model_id = model_id or model_name(db, transport)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    return (
        f"{API}/{model_id}:generateContent",
        headers,
        _body(system, contents, tools, schema, max_tokens, _thinking(model_id) if fast else None),
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


def _retry_model(db: Session, tried: str, transport) -> str:
    """Après un 404 : cherche un autre modèle utilisable pour cette clé, sinon explique lesquels existent."""
    key = integrations.get(db, "gemini_api_key") or ""
    models = available_models(key, transport)
    picked = pick_default(models)
    if picked and picked != tried:
        _auto[key] = (time.time(), picked)
        return picked
    shown = ", ".join(sorted(models)[:12]) or "aucun (liste indisponible)"
    raise ModelNotFound(
        f"Modèle Gemini « {tried} » introuvable pour cette clé. Modèles disponibles : {shown}. "
        "Choisissez-en un dans Paramètres > Intégrations > Assistant IA."
    )


_ANY_FLASH = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash(-lite)?$")
BUSY_WAITS = (2.0, 5.0)  # attentes avant de réessayer le même modèle surchargé


def _alternative(db: Session, tried: set[str], transport) -> str | None:
    """Autre modèle Flash de la clé (le plus récent d'abord, Lite en dernier) pour contourner une surcharge."""
    key = integrations.get(db, "gemini_api_key") or ""
    found = [
        (m.group(2) is None, float(m.group(1)), name)
        for name in available_models(key, transport)
        if (m := _ANY_FLASH.match(name)) and name not in tried
    ]
    return max(found)[2] if found else None


class _Retries:
    """Décide quoi faire après une erreur : même modèle après une pause, autre modèle, ou abandon."""

    def __init__(self, db: Session, transport):
        self.db, self.transport = db, transport
        self.tried: set[str] = set()
        self.busy = 0
        self.alts = 0
        self.not_found = False

    def after(self, exc: LLMError, model_id: str) -> tuple[str, float]:
        self.tried.add(model_id)
        if isinstance(exc, ModelNotFound) and not self.not_found:
            self.not_found = True
            return _retry_model(self.db, model_id, self.transport), 0.0
        if isinstance(exc, Unavailable):
            if self.busy < len(BUSY_WAITS):
                self.busy += 1
                logger.warning(
                    "Gemini %s surchargé, nouvel essai dans %ss", model_id, BUSY_WAITS[self.busy - 1]
                )
                return model_id, BUSY_WAITS[self.busy - 1]
            alt = _alternative(self.db, self.tried, self.transport) if self.alts < 2 else None
            if alt:
                self.alts += 1
                logger.warning("Gemini %s toujours surchargé : bascule sur %s", model_id, alt)
                self.busy = len(BUSY_WAITS) - 1  # un seul nouvel essai sur le modèle de secours
                return alt, 0.0
        raise exc


def generate(
    db: Session,
    contents: list[dict],
    *,
    system: str = "",
    tools: list[dict] | None = None,
    schema: dict | None = None,
    max_tokens: int = 8000,
    fast: bool = False,
    timeout: float = TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> Result:
    model_id, retries = None, _Retries(db, transport)
    while True:
        url, headers, body, model_id = _request(
            db, system, contents, tools, schema, max_tokens, model_id, transport, fast
        )
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=_timeout(timeout), transport=transport) as c:
                res = _finish(c.post(url, headers=headers, json=body), model_id)
            res.model = model_id
            return res
        except LLMError as exc:
            model_id, wait = retries.after(exc, model_id)
            time.sleep(wait)
        except httpx.HTTPError as exc:
            raise _net_error(exc, model_id, timeout, False, t0) from exc


async def agenerate(
    db: Session,
    contents: list[dict],
    *,
    system: str = "",
    tools: list[dict] | None = None,
    schema: dict | None = None,
    max_tokens: int = 8000,
    fast: bool = False,
    timeout: float = TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Result:
    model_id, retries = None, _Retries(db, transport)
    while True:
        url, headers, body, model_id = _request(
            db, system, contents, tools, schema, max_tokens, model_id, transport, fast
        )
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_timeout(timeout), transport=transport) as c:
                res = _finish(await c.post(url, headers=headers, json=body), model_id)
            res.model = model_id
            return res
        except LLMError as exc:
            model_id, wait = await asyncio.to_thread(retries.after, exc, model_id)
            await asyncio.sleep(wait)
        except httpx.HTTPError as exc:
            raise _net_error(exc, model_id, timeout, False, t0) from exc


def _merge_parts(parts: list[dict]) -> list[dict]:
    """Recolle les morceaux de texte consécutifs d'un flux en une seule part."""
    out: list[dict] = []
    for p in parts:
        if out and set(p) == {"text"} and set(out[-1]) == {"text"}:
            out[-1] = {"text": out[-1]["text"] + p["text"]}
        else:
            out.append(p)
    return out


async def astream(
    db: Session,
    contents: list[dict],
    *,
    system: str = "",
    tools: list[dict] | None = None,
    max_tokens: int = 8000,
    fast: bool = False,
    timeout: float = TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
):
    """Comme `agenerate`, mais en flux : produit ("text", morceau) au fil de l'eau, puis ("result", Result)."""
    model_id = await asyncio.to_thread(model_name, db, transport)  # appel réseau éventuel : hors boucle
    retries = _Retries(db, transport)
    while True:
        url, headers, body, model_id = _request(
            db, system, contents, tools, None, max_tokens, model_id, transport, fast
        )
        url = url.replace(":generateContent", ":streamGenerateContent?alt=sse")
        parts: list[dict] = []
        usage: dict = {}
        reason, blocked = None, None
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_timeout(timeout), transport=transport) as c:
                async with c.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        try:
                            data = resp.json()
                        except ValueError:
                            data = {}
                        raise _error(resp.status_code, data, model_id)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            chunk = json.loads(line[5:])
                        except ValueError:
                            continue
                        blocked = blocked or (chunk.get("promptFeedback") or {}).get("blockReason")
                        usage = chunk.get("usageMetadata") or usage
                        for cand in (chunk.get("candidates") or [])[:1]:
                            reason = cand.get("finishReason") or reason
                            for part in (cand.get("content") or {}).get("parts") or []:
                                parts.append(part)
                                if part.get("text") and not part.get("thought"):
                                    yield ("text", part["text"])
        except LLMError as exc:
            if fast and "thinking" in str(exc).lower():  # réglage de réflexion refusé par ce modèle
                fast = False
                continue
            if parts:  # réponse déjà commencée : on ne recommence pas
                raise
            model_id, wait = await asyncio.to_thread(retries.after, exc, model_id)
            await asyncio.sleep(wait)
            continue
        except httpx.HTTPError as exc:
            raise _net_error(exc, model_id, timeout, bool(parts), t0) from exc
        break
    data = {
        "candidates": [{"content": {"parts": _merge_parts(parts)}, "finishReason": reason or "STOP"}]
        if parts or reason
        else [],
        "usageMetadata": usage,
        "promptFeedback": {"blockReason": blocked} if blocked else {},
    }
    res = _parse(data)
    res.model = model_id
    yield ("result", res)


def test_connection(db: Session) -> str:
    t0 = time.monotonic()
    res = generate(db, [user("Réponds uniquement : OK")], max_tokens=50)
    if res.finish in ("refusal", "error"):
        raise LLMError("Gemini n'a pas pu répondre : vérifiez le modèle choisi.")
    normal = time.monotonic() - t0

    async def stream() -> None:
        async for _ in astream(db, [user("Réponds uniquement : OK")], max_tokens=50, fast=True, timeout=30):
            pass

    t1 = time.monotonic()
    try:
        asyncio.run(stream())
    except LLMError as exc:
        raise LLMError(f"Appel normal OK ({normal:.1f} s) mais le flux échoue : {exc}") from exc
    return (
        f"Connexion OK – modèle {res.model} prêt (appel {normal:.1f} s, flux {time.monotonic() - t1:.1f} s)."
    )
