import json
from types import SimpleNamespace

from app.models import CopilotMessage
from app.services import copilot, integrations


def block(**kw):
    return SimpleNamespace(**kw)


class FakeStream:
    def __init__(self, turn):
        self.turn = turn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for t in self.turn.get("texts", []):
                yield block(type="text", text=t)

        return gen()

    async def get_final_message(self):
        content = [block(type="text", text=t) for t in self.turn.get("texts", [])]
        content += [
            block(type="tool_use", id=f"tu{i}", name=n, input=inp)
            for i, (n, inp) in enumerate(self.turn.get("tools", []))
        ]
        return block(
            content=content,
            stop_reason="tool_use" if self.turn.get("tools") else "end_turn",
            usage=block(
                input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0
            ),
        )


class FakeClient:
    """Rejoue des tours de modèle scriptés et garde les requêtes envoyées."""

    def __init__(self, turns):
        self.turns, self.calls = list(turns), []
        outer = self

        class _Msgs:
            def stream(self, **kw):
                outer.calls.append(json.loads(json.dumps(kw, default=lambda o: o.__dict__)))
                return FakeStream(outer.turns.pop(0))

        self.messages = _Msgs()


def events(resp):
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def test_copilot_reads_hub_and_proposes_actions(client, db, monkeypatch):
    integrations.put(db, "anthropic_api_key", "sk-test")
    company = client.post("/api/crm/companies", json={"name": "Formasyl", "kind": "client"}).json()
    fake = FakeClient(
        [
            {"tools": [("hub_get", {"path": "/crm/companies", "params": {"q": "forma"}})]},
            {"tools": [("hub_get", {"path": "/integrations"})]},  # interdit : secrets
            {
                "tools": [
                    (
                        "propose_action",
                        {
                            "kind": "create_task",
                            "summary": "Relancer Formasyl",
                            "payload": {"title": "Relancer Formasyl", "company_id": company["id"]},
                        },
                    )
                ]
            },
            {"texts": ["Formasyl est un client. ", "Je propose une relance."]},
        ]
    )
    monkeypatch.setattr(copilot, "_client", lambda _db: fake)
    r = client.post("/api/copilot/chat", json={"message": "Où en est Formasyl ?", "page": "/crm/societes"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "conversation" and kinds[-1] == "done" and "error" not in kinds

    # 1) lecture réelle du Hub avec les droits de l'utilisateur
    tool_result = fake.calls[1]["messages"][-1]["content"][0]
    assert "Formasyl" in tool_result["content"] and not tool_result["is_error"]
    # 2) chemin hors liste refusé
    assert "non autorisé" in fake.calls[2]["messages"][-1]["content"][0]["content"]
    # 3) action proposée, jamais exécutée par le serveur
    (action,) = [e["action"] for e in ev if e["type"] == "action"]
    assert (
        action["method"] == "POST"
        and action["path"] == "/api/crm/tasks"
        and action["body"]["company_id"] == company["id"]
    )
    assert client.get("/api/crm/tasks").json() == []
    assert "".join(e["text"] for e in ev if e["type"] == "text").endswith("Je propose une relance.")

    # Conversation enregistrée, réservée à son auteur ; consommation comptée
    conv_id = ev[0]["id"]
    conv = client.get(f"/api/copilot/conversations/{conv_id}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] and conv["messages"][1]["actions"][
        0
    ]["kind"] == "create_task"
    assert conv["title"] == "Où en est Formasyl ?"
    assert sum(m.input_tokens for m in db.query(CopilotMessage).all()) == 4000
    assert client.get("/api/copilot/status").json()["spent"] > 0

    # Suite de la conversation : l'historique est renvoyé à l'IA
    fake2 = FakeClient([{"texts": ["Oui."]}])
    monkeypatch.setattr(copilot, "_client", lambda _db: fake2)
    client.post("/api/copilot/chat", json={"message": "Et ensuite ?", "conversation_id": conv_id})
    sent = fake2.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"] and sent[-1][
        "content"
    ] == "Et ensuite ?"


def test_copilot_respects_roles_budget_and_ownership(client, db, as_role, monkeypatch):
    integrations.put(db, "anthropic_api_key", "sk-test")
    member = as_role("member")
    fake = FakeClient([{"tools": [("hub_get", {"path": "/billing"})]}, {"texts": ["Pas d'accès."]}])
    monkeypatch.setattr(copilot, "_client", lambda _db: fake)
    ev = events(member.post("/api/copilot/chat", json={"message": "Mes factures ?"}))
    assert "Accès refusé" in fake.calls[1]["messages"][-1]["content"][0]["content"]
    # La conversation d'un membre n'est pas visible par un autre utilisateur
    assert client.get(f"/api/copilot/conversations/{ev[0]['id']}").status_code == 404

    integrations.put(db, "copilot_monthly_budget", "0")
    ev = events(client.post("/api/copilot/chat", json={"message": "Bonjour"}))
    assert ev[-1]["type"] == "error" and "Budget" in ev[-1]["message"]


def test_actions_are_built_safely():
    a = copilot.make_action("tag_mail", "Marquer urgent", {"message_id": 7, "tag": "urgent"})
    assert a["method"] == "PUT" and a["path"] == "/api/mail/messages/7/tag" and a["body"] == {"tag": "urgent"}
    q = copilot.make_action("create_quote", "Devis", {"company_id": 1, "title": "Site", "lines": []})
    assert q["body"]["kind"] == "quote" and q["path"] == "/api/billing"
    assert copilot.allowed_path("/crm/companies/12/overview") and not copilot.allowed_path("/integrations")
    assert not copilot.allowed_path("/users/1/summary/../../integrations")
