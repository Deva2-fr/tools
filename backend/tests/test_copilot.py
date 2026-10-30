import json

from app.models import CopilotMessage
from app.services import copilot, integrations
from tests.llm_fake import FakeLLM


def events(resp):
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def last_tool_responses(fake, i):
    """Réponses d'outils renvoyées au modèle lors de l'appel n° i."""
    return [p["functionResponse"] for p in fake.calls[i]["contents"][-1]["parts"]]


def test_copilot_reads_hub_and_proposes_actions(client, db, monkeypatch):
    integrations.put(db, "gemini_api_key", "AIza-test")
    company = client.post("/api/crm/companies", json={"name": "Formasyl", "kind": "client"}).json()
    task = {"title": "Relancer Formasyl", "company_id": company["id"]}
    fake = FakeLLM(
        monkeypatch,
        turns=[
            {"calls": [("hub_get", {"path": "/crm/companies", "params_json": '{"q": "forma"}'})]},
            {"calls": [("hub_get", {"path": "/integrations"})]},  # interdit : secrets
            {
                "calls": [
                    (
                        "propose_action",
                        {
                            "kind": "create_task",
                            "summary": "Relancer Formasyl",
                            "payload_json": json.dumps(task),
                        },
                    )
                ]
            },
            {"text": "Formasyl est un client. Je propose une relance."},
        ],
    )
    r = client.post("/api/copilot/chat", json={"message": "Où en est Formasyl ?", "page": "/crm/societes"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "conversation" and kinds[-1] == "done" and "error" not in kinds

    # 1) lecture réelle du Hub avec les droits de l'utilisateur
    (resp,) = last_tool_responses(fake, 1)
    assert resp["name"] == "hub_get" and "Formasyl" in resp["response"]["result"]
    # 2) chemin hors liste refusé
    (resp,) = last_tool_responses(fake, 2)
    assert "non autorisé" in resp["response"]["error"]
    # 3) action proposée, jamais exécutée par le serveur
    (action,) = [e["action"] for e in ev if e["type"] == "action"]
    assert (
        action["method"] == "POST"
        and action["path"] == "/api/crm/tasks"
        and action["body"]["company_id"] == company["id"]
    )
    assert client.get("/api/crm/tasks").json() == []
    assert "".join(e["text"] for e in ev if e["type"] == "text").endswith("Je propose une relance.")
    # Le contexte (page, utilisateur) est donné à l'IA ; les outils sont déclarés sans objet libre
    assert "/crm/societes" in fake.calls[0]["system"]
    assert {t["name"] for t in fake.calls[0]["tools"]} == {"hub_get", "propose_action"}

    # Conversation enregistrée, réservée à son auteur ; consommation comptée
    conv_id = ev[0]["id"]
    conv = client.get(f"/api/copilot/conversations/{conv_id}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["actions"][0]["kind"] == "create_task"
    assert conv["title"] == "Où en est Formasyl ?"
    assert sum(m.input_tokens for m in db.query(CopilotMessage).all()) == 4000
    assert client.get("/api/copilot/status").json()["spent"] > 0

    # Suite de la conversation : l'historique est renvoyé à l'IA
    fake2 = FakeLLM(monkeypatch, turns=[{"text": "Oui."}])
    client.post("/api/copilot/chat", json={"message": "Et ensuite ?", "conversation_id": conv_id})
    sent = fake2.calls[0]["contents"]
    assert [m["role"] for m in sent] == ["user", "model", "user"]
    assert sent[-1]["parts"][0]["text"] == "Et ensuite ?"


def test_copilot_respects_roles_budget_and_ownership(client, db, as_role, monkeypatch):
    integrations.put(db, "gemini_api_key", "AIza-test")
    member = as_role("member")
    fake = FakeLLM(
        monkeypatch, turns=[{"calls": [("hub_get", {"path": "/billing"})]}, {"text": "Pas d'accès."}]
    )
    ev = events(member.post("/api/copilot/chat", json={"message": "Mes factures ?"}))
    (resp,) = last_tool_responses(fake, 1)
    assert "Accès refusé" in resp["response"]["error"]
    # La conversation d'un membre n'est pas visible par un autre utilisateur
    assert client.get(f"/api/copilot/conversations/{ev[0]['id']}").status_code == 404

    integrations.put(db, "copilot_monthly_budget", "0")
    ev = events(client.post("/api/copilot/chat", json={"message": "Bonjour"}))
    assert ev[-1]["type"] == "error" and "Budget" in ev[-1]["message"]


def test_copilot_asks_for_key_and_reports_ai_errors(client, db, monkeypatch):
    ev = events(client.post("/api/copilot/chat", json={"message": "Bonjour"}))
    assert ev[-1]["type"] == "error" and "clé API Gemini" in ev[-1]["message"]
    assert client.get("/api/copilot/status").json()["configured"] is False

    integrations.put(db, "gemini_api_key", "AIza-test")
    assert client.get("/api/copilot/status").json()["configured"] is True
    FakeLLM(monkeypatch, turns=[{"finish": "refusal"}])
    ev = events(client.post("/api/copilot/chat", json={"message": "Bonjour"}))
    assert ev[-1]["type"] == "done" and any(e["type"] == "error" for e in ev)


def test_actions_are_built_safely():
    a = copilot.make_action("tag_mail", "Marquer urgent", {"message_id": 7, "tag": "urgent"})
    assert a["method"] == "PUT" and a["path"] == "/api/mail/messages/7/tag" and a["body"] == {"tag": "urgent"}
    q = copilot.make_action("create_quote", "Devis", {"company_id": 1, "title": "Site", "lines": []})
    assert q["body"]["kind"] == "quote" and q["path"] == "/api/billing"
    assert copilot.allowed_path("/crm/companies/12/overview") and not copilot.allowed_path("/integrations")
    assert not copilot.allowed_path("/users/1/summary/../../integrations")
    assert copilot._json_arg('{"q": "ovh"}') == {"q": "ovh"} and copilot._json_arg("") == {}
