from app.models import CopilotUsage
from app.services import integrations
from tests.llm_fake import FakeLLM


def test_receipt_is_read_into_expense_fields(client, db, monkeypatch):
    r = client.post("/api/expenses/ai-read", files={"file": ("t.pdf", b"%PDF-1.4 ticket", "application/pdf")})
    assert r.status_code == 400 and "clé API Gemini" in r.json()["detail"]
    integrations.put(db, "gemini_api_key", "AIza-test")
    fake = FakeLLM(
        monkeypatch,
        payload={
            "expense_date": "2026-10-20",
            "amount_ttc": 54.5,
            "vat_rate": 10,
            "vendor": "SNCF",
            "reason": "Train Paris-Lyon",
            "category": "Transport",
        },
    )
    r = client.post("/api/expenses/ai-read", files={"file": ("t.pdf", b"%PDF-1.4 ticket", "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "expense_date": "2026-10-20",
        "amount_ttc": 54.5,
        "vat_rate": 10,
        "reason": "Train Paris-Lyon – SNCF",
        "category": "Transport",
    }
    assert fake.calls[0]["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "application/pdf"
    assert db.query(CopilotUsage).one().kind == "receipt_ocr"
    bad = client.post(
        "/api/expenses/ai-read", files={"file": ("t.docx", b"PK..", "application/octet-stream")}
    )
    assert bad.status_code == 400 and "PDF" in bad.json()["detail"]


def test_contract_analysis(client, db, monkeypatch):
    up = client.post(
        "/api/files",
        data={"name": "Contrat OVH"},
        files={"file": ("c.pdf", b"%PDF-1.4 contrat", "application/pdf")},
    ).json()
    integrations.put(db, "gemini_api_key", "AIza-test")
    payload = {
        "title": "Contrat d'hébergement",
        "summary": "Hébergement mutualisé, 12 mois.",
        "parties": ["OVH", "Deva2"],
        "amount": "120 € HT / an",
        "key_dates": [
            {"label": "Fin du contrat", "date": "2027-03-01"},
            {"label": "Bidon", "date": "bientôt"},
        ],
        "notice": "Résiliation 1 mois avant l'échéance.",
        "points_attention": ["Reconduction tacite"],
    }
    FakeLLM(monkeypatch, payload=payload)
    r = client.post(f"/api/files/{up['id']}/ai-analyze")
    assert r.status_code == 200, r.text
    assert r.json()["key_dates"] == [
        {"label": "Fin du contrat", "date": "2027-03-01"}
    ]  # dates invalides écartées
