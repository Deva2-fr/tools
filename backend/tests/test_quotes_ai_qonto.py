import json
from types import SimpleNamespace

import httpx
import pytest

from app.models import BillingDoc
from app.services import integrations, qonto, qonto_billing, qonto_oauth, quote_ai


def make_quote(client, company_name="Formasyl"):
    company = client.post(
        "/api/crm/companies", json={"name": company_name, "vat_number": "FR12345678901", "city": "Paris"}
    ).json()
    return client.post(
        "/api/billing",
        json={
            "kind": "quote",
            "company_id": company["id"],
            "title": "site",
            "issue_date": "2026-11-02",
            "due_date": "2026-12-02",
            "lines": [
                {"description": "dev site", "quantity": 1, "unit_price": 3000, "vat_rate": 20},
                {"description": "hebergement", "quantity": 12, "unit_price": 25, "vat_rate": 20},
            ],
        },
    ).json()


class FakeAnthropic:
    """Client Anthropic factice : renvoie une réponse JSON fixe et garde la requête."""

    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        outer = self

        class _Msgs:
            def create(self, **kw):
                outer.calls.append(kw)
                return SimpleNamespace(
                    stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=json.dumps(payload))]
                )

        self.beta = SimpleNamespace(messages=_Msgs())


PROPOSAL = {
    "title": "Refonte du site vitrine Formasyl",
    "lines": [
        {
            "description": "Conception et développement du site\nMaquettes, intégration, 10 pages",
            "quantity": 1,
            "unit_price": 3000,
            "vat_rate": 20,
        },
        {
            "description": "Hébergement et maintenance (mensuel)",
            "quantity": 12,
            "unit_price": 25,
            "vat_rate": 7,
        },
    ],
    "notes": "Délai : 6 semaines. Acompte de 30 % à la commande.",
    "changes": ["Intitulés précisés", "Conditions ajoutées"],
}


def test_ai_improve_returns_proposal_without_saving(client, db, monkeypatch):
    q = make_quote(client)
    body = {
        "instructions": "plus pro",
        "title": q["title"],
        "notes": "",
        "lines": [
            {k: ln[k] for k in ("description", "quantity", "unit_price", "vat_rate")} for ln in q["lines"]
        ],
    }
    r = client.post(f"/api/billing/{q['id']}/ai-improve", json=body)
    assert r.status_code == 400 and "clé API Anthropic" in r.json()["detail"]

    fake = FakeAnthropic(PROPOSAL)
    integrations.put(db, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(quote_ai, "_client", lambda _db: fake)
    r = client.post(f"/api/billing/{q['id']}/ai-improve", json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["title"] == "Refonte du site vitrine Formasyl" and p["changes"] == [
        "Intitulés précisés",
        "Conditions ajoutées",
    ]
    assert p["lines"][1]["vat_rate"] == 20  # taux non autorisé (7) ramené à 20
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    sent = json.loads(call["messages"][0]["content"])
    assert sent["client"] == "Formasyl" and sent["consigne_utilisateur"] == "plus pro"
    # Rien n'est enregistré tant que l'utilisateur n'applique pas la proposition
    assert client.get(f"/api/billing/{q['id']}").json()["title"] == "site"

    monkeypatch.setattr(quote_ai, "_client", lambda _db: FakeAnthropic({}, stop_reason="refusal"))
    r = client.post(f"/api/billing/{q['id']}/ai-improve", json=body)
    assert r.status_code == 400 and "refusé" in r.json()["detail"]


class FakeQonto:
    def __init__(self, existing_clients=(), quote_status=201):
        self.clients = list(existing_clients)
        self.quote_status = quote_status
        self.posted: dict[str, list] = {"/v2/clients": [], "/v2/quotes": []}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/v2/clients":
            return httpx.Response(200, json={"clients": self.clients, "meta": {"next_page": None}})
        if request.method == "POST" and path == "/v2/clients":
            body = json.loads(request.content)
            self.posted[path].append(body)
            return httpx.Response(201, json={"client": {"id": "cl-new", **body}})
        if request.method == "POST" and path == "/v2/quotes":
            body = json.loads(request.content)
            self.posted[path].append(body)
            if self.quote_status != 201:
                return httpx.Response(
                    self.quote_status, json={"errors": [{"detail": "expiry_date must be after issue_date"}]}
                )
            return httpx.Response(
                201,
                json={
                    "quote": {
                        "id": "q-42",
                        "number": "D-2026-007",
                        "status": "pending_approval",
                        "issue_date": body["issue_date"],
                        "expiry_date": body["expiry_date"],
                        "quote_url": "https://pay.qonto.com/quotes/q-42",
                        "terms_and_conditions": body.get("terms_and_conditions"),
                        "header": body.get("header"),
                        "total_amount": {"value": "3960.00"},
                        "vat_amount": {"value": "660.00"},
                        "client": {"name": "Formasyl", "vat_number": "FR12345678901"},
                        "items": [
                            {
                                "title": i["title"],
                                "quantity": i["quantity"],
                                "unit_price": i["unit_price"],
                                "vat_rate": i["vat_rate"],
                            }
                            for i in body["items"]
                        ],
                    }
                },
            )
        return httpx.Response(404, json={})

    def client(self, _db=None):
        return httpx.Client(base_url=qonto_oauth.API_URL, transport=httpx.MockTransport(self.handler))


def test_push_quote_to_qonto(client, db, monkeypatch):
    q = make_quote(client)
    r = client.post(f"/api/billing/{q['id']}/push-qonto")
    assert r.status_code == 400 and "Se connecter avec Qonto" in r.json()["detail"]

    fake = FakeQonto()
    monkeypatch.setattr(qonto_oauth, "client", fake.client)
    r = client.post(f"/api/billing/{q['id']}/push-qonto")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["provider"] == "qonto" and doc["number"] == "D-2026-007" and doc["status"] == "sent"
    assert doc["external_url"].endswith("/q-42")
    assert doc["title"] == "site" and doc["notes"] == body_notes(fake)  # objet et conditions conservés
    (new_client,) = fake.posted["/v2/clients"]
    assert (
        new_client["kind"] == "company"
        and new_client["name"] == "Formasyl"
        and new_client["vat_number"] == "FR12345678901"
    )
    (body,) = fake.posted["/v2/quotes"]
    assert body["client_id"] == "cl-new" and body["currency"] == "EUR" and body["expiry_date"] == "2026-12-02"
    assert body["items"][1] == {
        "title": "hebergement",
        "quantity": "12",
        "unit_price": {"value": "25.00", "currency": "EUR"},
        "vat_rate": "0.20",
    }
    # Devis désormais suivi depuis Qonto : lecture seule, pas de second envoi
    assert client.post(f"/api/billing/{q['id']}/push-qonto").status_code == 400
    assert (
        client.put(f"/api/billing/{q['id']}", json={"kind": "quote", "issue_date": "2026-11-02"}).status_code
        == 400
    )


def test_push_reuses_existing_qonto_client_and_reports_errors(client, db, monkeypatch):
    q = make_quote(client)
    fake = FakeQonto(existing_clients=[{"id": "cl-1", "name": "FORMASYL"}], quote_status=422)
    monkeypatch.setattr(qonto_oauth, "client", fake.client)
    r = client.post(f"/api/billing/{q['id']}/push-qonto")
    assert r.status_code == 400 and "expiry_date must be after issue_date" in r.json()["detail"]
    assert fake.posted["/v2/clients"] == [] and fake.posted["/v2/quotes"][0]["client_id"] == "cl-1"
    assert db.get(BillingDoc, q["id"]).provider == "manual"  # rien n'a changé dans le Hub


def test_sync_imports_invoices_even_if_quotes_forbidden(db):
    def handler(request):
        if request.url.path.endswith("/client_invoices"):
            return httpx.Response(
                200,
                json={
                    "client_invoices": [
                        {
                            "id": "i1",
                            "number": "F-1",
                            "status": "unpaid",
                            "issue_date": "2026-10-01",
                            "total_amount": {"value": "120"},
                            "vat_amount": {"value": "20"},
                            "client": {"name": "X"},
                            "items": [],
                        }
                    ],
                    "meta": {},
                },
            )
        return httpx.Response(403, json={})

    c = httpx.Client(base_url=qonto.API_URL, transport=httpx.MockTransport(handler))
    res = qonto_billing.sync(db, client=c)
    assert res["invoices"] == 1 and res["quotes"] == 0 and "OAuth" in res["warnings"][0]


def test_qonto_oauth_flow(client, db, monkeypatch):
    assert client.get("/api/billing/qonto/connect").status_code == 400
    integrations.put(db, "qonto_oauth_client_id", "app-123")
    integrations.put(db, "qonto_oauth_client_secret", "s3cret")
    url = client.get("/api/billing/qonto/connect").json()["url"]
    assert (
        url.startswith("https://oauth.qonto.com/oauth2/auth?")
        and "client_invoice.write" in url
        and "app-123" in url
    )
    state = url.split("state=")[1].split("&")[0]

    def fake_post(u, data, timeout):
        assert u == qonto_oauth.TOKEN_URL and data["client_secret"] == "s3cret"
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt-1"})

    monkeypatch.setattr(qonto_oauth.httpx, "post", fake_post)
    r = client.get(f"/api/billing/qonto/oauth/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307) and "qonto=connected" in r.headers["location"]
    st = client.get("/api/billing/qonto").json()
    assert st["oauth_connected"] is True and st["redirect_uri"].endswith("/api/billing/qonto/oauth/callback")
    assert qonto_oauth.access_token(db) == "at"
    bad = client.get("/api/billing/qonto/oauth/callback?code=abc&state=forged", follow_redirects=False)
    assert "qonto_error" in bad.headers["location"]
    client.post("/api/billing/qonto/disconnect")
    assert client.get("/api/billing/qonto").json()["oauth_connected"] is False
    with pytest.raises(qonto_oauth.QontoOAuthError):
        qonto_oauth.access_token(db)


def body_notes(fake):
    return fake.posted["/v2/quotes"][0]["terms_and_conditions"]
