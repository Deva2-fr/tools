import json

import httpx
import pytest

from app.services import integrations, llm

TOOL = {
    "name": "hub_get",
    "description": "Lit le Hub",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "n": {"type": "integer", "enum": [1, 2]}},
        "required": ["path"],
        "additionalProperties": False,
    },
}


def server(status=200, body=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request, json.loads(request.content)))
        return httpx.Response(status, json=body or {})

    return httpx.MockTransport(handler)


def reply(parts, finish="STOP", prompt=120, out=30, thoughts=0):
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
        "usageMetadata": {
            "promptTokenCount": prompt,
            "candidatesTokenCount": out,
            "thoughtsTokenCount": thoughts,
        },
    }


@pytest.fixture()
def keyed(db):
    integrations.put(db, "gemini_api_key", "AIza-test")
    return db


def test_request_shape_and_text_response(keyed):
    seen = []
    res = llm.generate(
        keyed,
        [llm.user("Bonjour")],
        system="Tu es utile.",
        schema={"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False},
        transport=server(body=reply([{"text": '{"a": "x"}'}], thoughts=50), seen=seen),
    )
    req, body = seen[0]
    assert req.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert req.headers["x-goog-api-key"] == "AIza-test"
    assert body["systemInstruction"]["parts"][0]["text"] == "Tu es utile."
    cfg = body["generationConfig"]
    assert (
        cfg["responseMimeType"] == "application/json" and "additionalProperties" not in cfg["responseSchema"]
    )
    assert (
        cfg["responseSchema"]["type"] == "OBJECT"
        and cfg["responseSchema"]["properties"]["a"]["type"] == "STRING"
    )
    assert res.text == '{"a": "x"}' and res.finish == "stop"
    assert (res.tokens_in, res.tokens_out) == (120, 80)  # la réflexion est comptée comme du texte généré


def test_model_setting_and_pdf_part(keyed):
    integrations.put(keyed, "gemini_model", "gemini-2.5-pro")
    seen = []
    llm.generate(
        keyed,
        [llm.user(llm.file_part(b"%PDF-1.4", "application/pdf"), "Lis")],
        transport=server(body=reply([{"text": "ok"}]), seen=seen),
    )
    assert seen[0][0].url.path.endswith("/gemini-2.5-pro:generateContent")
    part = seen[0][1]["contents"][0]["parts"][0]["inlineData"]
    assert part["mimeType"] == "application/pdf" and part["data"] == "JVBERi0xLjQ="


def test_tools_are_declared_and_calls_are_read(keyed):
    seen = []
    call = {"functionCall": {"name": "hub_get", "args": {"path": "/crm/companies"}}}
    res = llm.generate(
        keyed, [llm.user("Cherche")], tools=[TOOL], transport=server(body=reply([call]), seen=seen)
    )
    decl = seen[0][1]["tools"][0]["functionDeclarations"][0]
    assert decl["name"] == "hub_get" and decl["parameters"]["type"] == "OBJECT"
    assert "enum" not in decl["parameters"]["properties"]["n"]  # enum non texte : retiré pour Gemini
    assert "responseSchema" not in seen[0][1]["generationConfig"]
    assert [(c.name, c.args) for c in res.calls] == [("hub_get", {"path": "/crm/companies"})]
    assert res.parts == [call]
    back = llm.tool_results([("hub_get", "[]", False), ("hub_get", "403", True)])
    assert back["parts"][0]["functionResponse"]["response"] == {"result": "[]"}
    assert back["parts"][1]["functionResponse"]["response"] == {"error": "403"}


def test_finish_reasons(keyed):
    def t(reason):
        return llm.generate(keyed, [llm.user("x")], transport=server(body=reply([{"text": "x"}], reason)))

    assert (
        t("MAX_TOKENS").finish == "max_tokens"
        and t("SAFETY").finish == "refusal"
        and t("STOP").finish == "stop"
    )
    blocked = llm.generate(
        keyed, [llm.user("x")], transport=server(body={"promptFeedback": {"blockReason": "SAFETY"}})
    )
    assert blocked.finish == "refusal"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            400,
            {"error": {"message": "API key not valid. Please pass a valid API key."}},
            "clé API Gemini est refusée",
        ),
        (403, {"error": {"message": "denied"}}, "clé API Gemini est refusée"),
        (404, {"error": {"message": "not found"}}, "introuvable"),
        (429, {"error": {"message": "quota"}}, "Quota"),
        (503, {}, "indisponible"),
        (400, {"error": {"message": "bad schema"}}, "bad schema"),
    ],
)
def test_errors_are_readable(keyed, status, body, expected):
    with pytest.raises(llm.LLMError, match=expected):
        llm.generate(keyed, [llm.user("x")], transport=server(status, body))


def test_missing_key_and_network_error_and_async(db):
    with pytest.raises(llm.LLMError, match="clé API Gemini"):
        llm.generate(db, [llm.user("x")])
    integrations.put(db, "gemini_api_key", "AIza-test")

    def boom(request):
        raise httpx.ConnectError("down")

    with pytest.raises(llm.LLMError, match="injoignable"):
        llm.generate(db, [llm.user("x")], transport=httpx.MockTransport(boom))

    import asyncio

    res = asyncio.run(
        llm.agenerate(db, [llm.user("x")], transport=server(body=reply([{"text": "async ok"}])))
    )
    assert res.text == "async ok"
