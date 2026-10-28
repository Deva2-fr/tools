import httpx
import pytest
from sqlalchemy import select

from app.models import BillingDoc, Company
from app.services import integrations, qonto, qonto_billing

INVOICES = [
    {
        "id": "inv-1",
        "number": "F-2026-001",
        "status": "paid",
        "issue_date": "2026-09-01",
        "due_date": "2026-10-01",
        "paid_at": "2026-09-20T10:00:00Z",
        "invoice_url": "https://pay.qonto.com/invoices/inv-1",
        "total_amount": {"value": "1200.00", "currency": "EUR"},
        "vat_amount": {"value": "200.00", "currency": "EUR"},
        "client": {
            "name": "Formasyl",
            "vat_number": "FR12345678901",
            "email": "compta@formasyl.org",
            "billing_address": {"street_address": "1 rue X", "zip_code": "75001", "city": "Paris"},
        },
        "items": [
            {
                "title": "Maintenance",
                "description": "Septembre",
                "quantity": "1",
                "unit_price": {"value": "1000.00", "currency": "EUR"},
                "vat_rate": "0.2",
            }
        ],
    },
    {
        "id": "inv-2",
        "number": "F-2026-002",
        "status": "unpaid",
        "issue_date": "2026-10-01",
        "due_date": "2026-10-15",
        "total_amount_cents": 60000,
        "vat_amount_cents": 10000,
        "client": {"first_name": "Jean", "last_name": "Client"},
        "items": [],
    },
]
QUOTES = [
    {
        "id": "q-1",
        "number": "D-2026-001",
        "status": "approved",
        "issue_date": "2026-08-01",
        "expiry_date": "2026-09-01",
        "quote_url": "https://pay.qonto.com/quotes/q-1",
        "total_amount": {"value": "2400.00"},
        "vat_amount": {"value": "400.00"},
        "client": {"name": "formasyl"},
        "items": [],
    }
]


def fake(invoices=INVOICES, quotes=QUOTES, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={})
        if request.url.path.endswith("/client_invoices"):
            page = int(request.url.params.get("current_page", 1))
            # 2 pages pour vérifier la pagination
            body = {
                "client_invoices": invoices[page - 1 : page],
                "meta": {"next_page": page + 1 if page < len(invoices) else None},
            }
            return httpx.Response(200, json=body)
        if request.url.path.endswith("/quotes"):
            return httpx.Response(200, json={"quotes": quotes, "meta": {"next_page": None}})
        return httpx.Response(404)

    return httpx.Client(base_url=qonto.API_URL, transport=httpx.MockTransport(handler))


def test_import_invoices_and_quotes(db):
    res = qonto_billing.sync(db, client=fake())
    assert res == {"invoices": 2, "quotes": 1, "created": 3}

    paid = db.scalar(select(BillingDoc).where(BillingDoc.number == "F-2026-001"))
    assert paid.provider == "qonto" and paid.status == "paid" and paid.kind == "invoice"
    assert (paid.total_ht, paid.total_vat, paid.total_ttc) == (1000.0, 200.0, 1200.0)
    assert paid.amount_paid == 1200.0 and paid.payments[0].paid_on.isoformat() == "2026-09-20"
    assert paid.lines[0].vat_rate == 20 and paid.lines[0].description == "Maintenance – Septembre"
    assert paid.external_url.endswith("/inv-1")

    unpaid = db.scalar(select(BillingDoc).where(BillingDoc.number == "F-2026-002"))
    assert unpaid.status == "sent" and unpaid.total_ttc == 600.0 and unpaid.amount_paid == 0

    quote = db.scalar(select(BillingDoc).where(BillingDoc.kind == "quote", BillingDoc.provider == "qonto"))
    assert quote.status == "accepted" and quote.due_date.isoformat() == "2026-09-01"
    # Le client est créé une fois puis retrouvé par son nom (casse ignorée).
    formasyl = db.scalars(select(Company).where(Company.name.ilike("formasyl"))).all()
    assert len(formasyl) == 1 and formasyl[0].vat_number == "FR12345678901" and formasyl[0].kind == "client"
    assert quote.company_id == paid.company_id == formasyl[0].id
    assert db.scalar(select(Company).where(Company.name == "Jean Client"))
    assert integrations.get(db, "qonto_billing_synced_at")


def test_resync_updates_without_duplicates(db):
    qonto_billing.sync(db, client=fake())
    changed = [dict(INVOICES[1], status="paid", paid_at="2026-10-10"), INVOICES[0]]
    res = qonto_billing.sync(db, client=fake(invoices=changed))
    assert res["created"] == 0
    assert db.scalar(select(BillingDoc).where(BillingDoc.number == "F-2026-002")).amount_paid == 600.0
    assert len(db.scalars(select(BillingDoc).where(BillingDoc.provider == "qonto")).all()) == 3
    cancelled = [dict(INVOICES[0], status="canceled")]
    qonto_billing.sync(db, client=fake(invoices=cancelled))
    doc = db.scalar(select(BillingDoc).where(BillingDoc.number == "F-2026-001"))
    assert doc.status == "cancelled" and doc.amount_paid == 0 and not doc.payments


def test_errors_are_readable(db):
    with pytest.raises(qonto.QontoError, match="devis|factures"):
        qonto_billing.sync(db, client=fake(status=403))
    with pytest.raises(qonto.QontoError, match="identifiants"):
        qonto_billing.sync(db, client=fake(status=401))


def test_endpoints_are_read_only(client, db, as_role, monkeypatch):
    assert client.get("/api/billing/qonto").json()["configured"] is False
    integrations.put(db, "qonto_login", "deva2-1234")
    integrations.put(db, "qonto_secret_key", "secret")
    monkeypatch.setattr(qonto_billing, "_client", lambda _db: fake())
    r = client.post("/api/billing/qonto/sync")
    assert r.status_code == 200 and r.json()["invoices"] == 2
    assert client.get("/api/billing/qonto").json()["last_synced_at"]
    assert as_role("member").post("/api/billing/qonto/sync").status_code == 403

    docs = client.get("/api/billing?kind=invoice").json()
    inv = next(d for d in docs if d["number"] == "F-2026-002")
    assert inv["provider"] == "qonto" and inv["remaining"] == 600.0
    # Lecture seule dans le Hub
    assert client.post(f"/api/billing/{inv['id']}/status", json={"status": "cancelled"}).status_code == 400
    assert client.delete(f"/api/billing/{inv['id']}").status_code == 400
    assert client.get(f"/api/billing/{inv['id']}/pdf").content.startswith(b"%PDF")


def test_expense_pdf_uploaded_to_drive(client, db, monkeypatch):
    import json

    from app.services import google_drive

    integrations.put(
        db,
        "google_service_account_json",
        json.dumps({"client_email": "hub@x.iam", "private_key": "k", "token_uri": "t"}),
    )
    integrations.put(
        db, "google_output_folder_id", "https://drive.google.com/drive/folders/FOLDER123?usp=sharing"
    )
    monkeypatch.setattr(google_drive, "_access_token", lambda _db: "tok")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.method == "POST":
            return httpx.Response(
                200, json={"id": "file-1", "webViewLink": "https://drive.google.com/file/d/file-1"}
            )
        return httpx.Response(
            200, json={"id": "file-1", "webViewLink": "https://drive.google.com/file/d/file-1"}
        )

    real = httpx.Client
    monkeypatch.setattr(
        google_drive.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    body = {"expense_date": "2026-10-01", "reason": "Train", "amount_ttc": 60, "vat_rate": 10}
    r = client.post("/api/expenses/save", json=body)
    assert r.status_code == 200 and r.headers["x-drive-status"] == "ok"
    assert seen[0][0] == "POST" and b'"parents": ["FOLDER123"]' in seen[0][2] and b"%PDF" in seen[0][2]
    e = next(x for x in client.get("/api/expenses").json() if x["id"] == int(r.headers["x-expense-id"]))
    assert e["drive_link"].endswith("file-1")
    # Réenregistrer la note remplace le même fichier Drive (pas de doublon).
    r = client.post(f"/api/expenses/save?expense_id={e['id']}", json=body)
    assert r.headers["x-drive-status"] == "ok" and seen[1][0] == "PATCH" and "file-1" in seen[1][1]

    def denied(request):
        return httpx.Response(403, json={"error": {"errors": [{"reason": "storageQuotaExceeded"}]}})

    monkeypatch.setattr(
        google_drive.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(denied), **kw)
    )
    r = client.post("/api/expenses/save", json=body)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    from urllib.parse import unquote

    assert "Drive partagé" in unquote(r.headers["x-drive-status"])
