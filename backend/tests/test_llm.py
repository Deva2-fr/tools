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
        if seen is not None and request.method == "POST":
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


@pytest.fixture(autouse=True)
def _reset_model_cache():
    llm._auto.clear()


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
    assert req.url.path == "/v1beta/models/gemini-3.5-flash:generateContent"
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

    with pytest.raises(llm.LLMError, match=r"interrompue \(ConnectError\)"):
        llm.generate(db, [llm.user("x")], transport=httpx.MockTransport(boom))

    import asyncio

    res = asyncio.run(
        llm.agenerate(db, [llm.user("x")], transport=server(body=reply([{"text": "async ok"}])))
    )
    assert res.text == "async ok"


def listing(*names):
    return {
        "models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in names]
        + [{"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}]
    }


def test_pick_default_takes_latest_stable_flash():
    names = [
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash-preview",
        "gemini-3.5-pro",
        "gemini-3.1-flash-image",
    ]
    assert llm.pick_default(names) == "gemini-3.5-flash"
    assert llm.pick_default(["gemini-3.5-pro"]) is None


def test_model_is_chosen_from_the_keys_model_list(keyed):
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.headers["x-goog-api-key"] == "AIza-test"
            return httpx.Response(200, json=listing("gemini-2.5-flash", "gemini-4.0-flash", "gemini-4.0-pro"))
        posted.append(request.url.path)
        return httpx.Response(200, json=reply([{"text": "ok"}]))

    transport = httpx.MockTransport(handler)
    res = llm.generate(keyed, [llm.user("x")], transport=transport)
    llm.generate(keyed, [llm.user("x")], transport=transport)
    assert res.model == "gemini-4.0-flash" and posted[0].endswith("/gemini-4.0-flash:generateContent")
    assert len(posted) == 2


def test_removed_saved_model_falls_back_to_available_one(keyed):
    integrations.put(keyed, "gemini_model", "gemini-2.5-flash")
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=listing("gemini-3.5-flash"))
        posted.append(request.url.path.rsplit("/", 1)[-1])
        if "2.5" in request.url.path:
            return httpx.Response(404, json={"error": {"message": "not found"}})
        return httpx.Response(200, json=reply([{"text": "ok"}]))

    res = llm.generate(keyed, [llm.user("x")], transport=httpx.MockTransport(handler))
    assert res.text == "ok" and res.model == "gemini-3.5-flash"
    assert posted == ["gemini-2.5-flash:generateContent", "gemini-3.5-flash:generateContent"]


def test_not_found_lists_available_models(keyed):
    integrations.put(keyed, "gemini_model", "gemini-9-flash")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=listing("gemini-3.5-pro"))
        return httpx.Response(404, json={"error": {"message": "not found"}})

    with pytest.raises(llm.LLMError, match=r"gemini-9-flash.*Modèles disponibles : gemini-3\.5-pro"):
        llm.generate(keyed, [llm.user("x")], transport=httpx.MockTransport(handler))


def sse(*chunks):
    return "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks).encode()


def test_stream_yields_text_then_result_and_requests_low_thinking(keyed):
    import asyncio

    integrations.put(keyed, "gemini_model", "gemini-3.5-flash")
    call = {"functionCall": {"name": "hub_get", "args": {"path": "/billing"}}, "thoughtSignature": "sig"}
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.url.query, json.loads(request.content)))
        body = sse(
            {"candidates": [{"content": {"parts": [{"text": "Bon"}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "jour"}, call]}, "finishReason": "STOP"}]},
            {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4, "thoughtsTokenCount": 6}},
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async def run():
        return [
            item
            async for item in llm.astream(
                keyed, [llm.user("x")], tools=[TOOL], fast=True, transport=httpx.MockTransport(handler)
            )
        ]

    items = asyncio.run(run())
    assert [i for i in items if i[0] == "text"] == [("text", "Bon"), ("text", "jour")]
    res = items[-1][1]
    assert items[-1][0] == "result" and res.text == "Bonjour" and (res.tokens_in, res.tokens_out) == (10, 10)
    assert res.calls[0].args == {"path": "/billing"} and res.parts[-1] == call  # signature conservée
    path, query, body = seen[0]
    assert path.endswith(":streamGenerateContent") and b"alt=sse" in query
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_stream_retries_without_thinking_when_model_refuses_it(keyed):
    import asyncio

    integrations.put(keyed, "gemini_model", "gemini-2.5-flash")
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "thinkingConfig" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"message": "Thinking budget not supported"}})
        return httpx.Response(
            200,
            content=sse({"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}),
        )

    async def run():
        return [
            i
            async for i in llm.astream(
                keyed, [llm.user("x")], fast=True, transport=httpx.MockTransport(handler)
            )
        ]

    assert asyncio.run(run())[-1][1].text == "ok" and len(bodies) == 2


def test_stream_errors_are_readable(keyed):
    import asyncio

    async def run():
        return [i async for i in llm.astream(keyed, [llm.user("x")], transport=server(429, {}))]

    with pytest.raises(llm.LLMError, match="Quota"):
        asyncio.run(run())


def test_network_failures_are_told_apart(keyed):
    import asyncio

    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def cut(request):
        raise httpx.ReadError("reset")

    with pytest.raises(llm.NetworkError, match=r"n'a pas répondu en 30 s"):
        llm.generate(keyed, [llm.user("x")], timeout=30, transport=httpx.MockTransport(timeout))
    with pytest.raises(llm.NetworkError, match="interrompue \\(ReadError\\)") as info:
        llm.generate(keyed, [llm.user("x")], transport=httpx.MockTransport(cut))
    assert info.value.started is False

    async def run():
        return [i async for i in llm.astream(keyed, [llm.user("x")], transport=httpx.MockTransport(timeout))]

    with pytest.raises(llm.NetworkError, match="n'a pas répondu") as info:
        asyncio.run(run())
    assert info.value.started is False and isinstance(info.value, llm.LLMError)


def test_connection_reports_both_calls(keyed, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda db, c, **kw: llm.Result(text="OK", model="gemini-3.5-flash"))

    async def fake_stream(db, c, **kw):
        yield ("text", "OK")
        yield ("result", llm.Result(text="OK", model="gemini-3.5-flash"))

    monkeypatch.setattr(llm, "astream", fake_stream)
    msg = llm.test_connection(keyed)
    assert "gemini-3.5-flash" in msg and "appel" in msg and "flux" in msg

    async def broken(db, c, **kw):
        raise llm.NetworkError("Connexion à Gemini interrompue (ReadError) : réessayez.")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "astream", broken)
    with pytest.raises(llm.LLMError, match="le flux échoue"):
        llm.test_connection(keyed)
