import httpx
import pytest
from sqlalchemy import select

from app.models import BankAccount, Transaction
from app.services import integrations, qonto, treasury

ORG = {
    "organization": {
        "slug": "deva2-1234",
        "legal_name": "DEVA2",
        "bank_accounts": [
            {
                "id": "acc-1",
                "slug": "deva2-bank-1",
                "iban": "FR7616958000010000000000001",
                "name": "Compte principal",
                "status": "active",
                "balance": 1500.0,
                "balance_cents": 150000,
            },
            {"id": "acc-closed", "iban": "FR76X", "name": "Ancien", "status": "closed", "balance": 0},
        ],
    }
}
TX_PAGE_1 = {
    "transactions": [
        {
            "id": "t1",
            "amount": 1200.0,
            "side": "credit",
            "settled_at": "2026-10-01T09:00:00.000Z",
            "label": "ACME SAS",
            "reference": "FAC-2026-0001",
            "category": "other_income",
            "status": "completed",
        },
        {
            "id": "t2",
            "amount": 49.9,
            "side": "debit",
            "settled_at": "2026-10-02T10:00:00.000Z",
            "label": "OVH",
            "category": "hosting",
            "status": "completed",
        },
    ],
    "meta": {"current_page": 1, "next_page": 2},
}
TX_PAGE_2 = {
    "transactions": [
        {
            "id": "t3",
            "amount_cents": 1000,
            "side": "debit",
            "settled_at": "2026-10-03T08:00:00.000Z",
            "operation_type": "card",
            "status": "completed",
        }
    ],
    "meta": {"current_page": 2, "next_page": None},
}


def fake(status=200, calls=None, pages=(TX_PAGE_1, TX_PAGE_2), org=ORG):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if status != 200:
            return httpx.Response(status, json={"errors": []})
        if request.url.path.endswith("/organization"):
            return httpx.Response(200, json=org)
        page = int(request.url.params.get("current_page", 1))
        return httpx.Response(
            200, json=pages[page - 1] if page <= len(pages) else {"transactions": [], "meta": {}}
        )

    return httpx.Client(
        base_url=qonto.API_URL, transport=httpx.MockTransport(handler), headers={"Authorization": "x:y"}
    )


def test_first_sync_imports_transactions_and_matches_qonto_balance(db):
    calls = []
    res = qonto.sync(db, client=fake(calls=calls))
    assert res["created"] == 3 and len(res["accounts"]) == 1  # compte fermé ignoré
    acc = db.scalar(select(BankAccount).where(BankAccount.provider == "qonto"))
    assert acc.name == "Qonto – Compte principal" and acc.iban.startswith("FR76") and acc.last_synced_at
    amounts = sorted(t.amount for t in db.scalars(select(Transaction)))
    assert amounts == [-49.9, -10.0, 1200.0]
    # le solde du Hub = solde réel Qonto
    assert treasury.current_balance(db) == 1500.0
    tx_req = [c for c in calls if c.url.path.endswith("/transactions")][0]
    assert (
        tx_req.url.params["status[]"] == "completed"
        and tx_req.url.params["iban"] == "FR7616958000010000000000001"
    )


def test_resync_is_idempotent_and_follows_balance(db):
    qonto.sync(db, client=fake())
    org = {
        "organization": {
            **ORG["organization"],
            "bank_accounts": [{**ORG["organization"]["bank_accounts"][0], "balance": 1700.0}],
        }
    }
    res = qonto.sync(db, client=fake(org=org))
    assert res["created"] == 0  # pas de doublon
    assert len(db.scalars(select(Transaction)).all()) == 3
    assert treasury.current_balance(db) == 1700.0


def test_errors_are_readable(db):
    with pytest.raises(qonto.QontoError, match="identifiants"):
        qonto.sync(db, client=fake(status=401))
    with pytest.raises(qonto.QontoError, match="pas configuré"):
        qonto.sync(db)


def test_endpoints_and_permissions(client, db, as_role, monkeypatch):
    status = client.get("/api/treasury/qonto").json()
    assert status == {"configured": False, "accounts": 0, "last_synced_at": None}
    r = client.post("/api/treasury/qonto/sync")
    assert r.status_code == 400 and "pas configuré" in r.json()["detail"]

    integrations.put(db, "qonto_login", "deva2-1234")
    integrations.put(db, "qonto_secret_key", "secret")
    monkeypatch.setattr(qonto, "_client", lambda _db: fake())
    r = client.post("/api/treasury/qonto/sync")
    assert r.status_code == 200 and r.json()["created"] == 3
    accounts = client.get("/api/accounts").json()
    assert accounts[0]["provider"] == "qonto" and accounts[0]["last_synced_at"]
    assert client.get("/api/treasury/qonto").json()["configured"] is True
    fields = {f["key"]: f for f in client.get("/api/integrations").json()}
    assert (
        fields["qonto_secret_key"]["is_set"] and fields["qonto_secret_key"]["value"] == ""
    )  # jamais renvoyée
    assert as_role("member").post("/api/treasury/qonto/sync").status_code == 403
