from datetime import date, timedelta

from app.models import BillingDoc, Company, CopilotBrief, Opportunity, Task
from app.services import integrations
from tests.llm_fake import FakeLLM


def seed_data(db):
    acme = Company(name="Acme", kind="client")
    db.add(acme)
    db.flush()
    db.add_all(
        [
            BillingDoc(
                kind="quote",
                status="sent",
                company_id=acme.id,
                title="Refonte",
                issue_date=date.today() - timedelta(days=15),
                total_ht=3000,
                total_vat=600,
                total_ttc=3600,
            ),
            Opportunity(
                title="Site vitrine",
                company_id=acme.id,
                stage="quote",
                amount=5000,
                probability=50,
                expected_close=date.today() - timedelta(days=3),
            ),
            Task(title="Rappeler Bob", due_date=date.today() - timedelta(days=2)),
        ]
    )
    db.commit()


def test_suggestions_and_fallback_brief(client, db):
    seed_data(db)
    r = client.get("/api/copilot/brief")
    assert r.status_code == 200, r.text
    b = r.json()
    kinds = {s["kind"] for s in b["suggestions"]}
    assert {"relance_devis", "client_silencieux", "affaire_en_retard", "taches_retard"} <= kinds
    relance = next(s for s in b["suggestions"] if s["kind"] == "relance_devis")
    assert "Acme" in relance["title"] and relance["link"].startswith("/facturation/") and relance["ask"]
    # Sans clé API : brief rédigé automatiquement, sans IA
    assert b["ai"] is False and b["points"] and b["headline"]


def test_ai_brief_is_cached_daily_and_counts_budget(client, db, monkeypatch):
    seed_data(db)
    integrations.put(db, "gemini_api_key", "AIza-test")
    fake = FakeLLM(
        monkeypatch,
        payload={
            "headline": "Relancez Acme aujourd'hui.",
            "points": ["Devis Refonte sans réponse depuis 15 jours."],
        },
    )
    b = client.get("/api/copilot/brief").json()
    assert b["ai"] is True and b["headline"] == "Relancez Acme aujourd'hui."
    assert "Acme" in fake.calls[0]["contents"][0]["parts"][0]["text"]  # faits réels envoyés à l'IA
    client.get("/api/copilot/brief")
    assert len(fake.calls) == 1  # en cache pour la journée
    client.get("/api/copilot/brief?refresh=true")
    assert len(fake.calls) == 2 and db.query(CopilotBrief).count() == 1
    assert client.get("/api/copilot/status").json()["spent"] > 0


def test_member_sees_no_finance(client, db, as_role):
    seed_data(db)
    member = as_role("member")
    b = member.get("/api/copilot/brief").json()
    assert not any(s["kind"] in ("relance_devis", "factures_retard") for s in b["suggestions"])
