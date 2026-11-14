from datetime import date, timedelta

from sqlalchemy import select

from app.models import Alert, BillingDoc, ClientContract
from app.services import client_renewals

TODAY = date.today()


def company(client, name="Acme"):
    return client.post("/api/crm/companies", json={"name": name, "kind": "client"}).json()["id"]


def contract(client, company_id, **kw):
    body = {
        "company_id": company_id,
        "name": "Hébergement acme.fr",
        "kind": "hosting",
        "unit_price": 600,
        "renewal_date": str(TODAY + timedelta(days=20)),
        **kw,
    }
    r = client.post("/api/client-contracts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_quote_prepared_30_days_before_and_grouped_per_client(client, db):
    acme, beta = company(client), company(client, "Beta")
    contract(client, acme)
    contract(client, acme, name="Domaine acme.fr", kind="domain", unit_price=15, quantity=2)
    contract(
        client,
        acme,
        name="Maintenance",
        kind="maintenance",
        unit_price=100,
        renewal_date=str(TODAY + timedelta(days=60)),
    )
    contract(client, beta, name="Hébergement beta.fr", active=False)  # résilié

    assert client.get("/api/client-contracts").json()[0]["renewal"]["state"] == "planned"
    (doc,) = client_renewals.prepare(db, TODAY)
    assert doc.kind == "quote" and doc.status == "draft" and doc.company_id == acme
    assert doc.total_ht == 630 and len(doc.lines) == 2  # maintenance pas encore dans les 30 jours
    start = TODAY + timedelta(days=20)
    assert doc.lines[0].description.startswith(f"Hébergement acme.fr – du {start:%d/%m/%Y}")
    assert doc.title.startswith(f"Renouvellement {start.year} – Acme") and doc.due_date == start
    assert (
        db.scalar(select(Alert).where(Alert.kind == "renewal")).title == "Devis de renouvellement prêt – Acme"
    )
    # Pas de doublon le lendemain ; la maintenance est préparée quand son tour vient
    assert client_renewals.prepare(db, TODAY + timedelta(days=1)) == []
    (later,) = client_renewals.prepare(db, TODAY + timedelta(days=31))
    assert later.total_ht == 100 and len(db.scalars(select(BillingDoc)).all()) == 2

    rows = {r["name"]: r["renewal"] for r in client.get(f"/api/client-contracts?company_id={acme}").json()}
    assert (
        rows["Hébergement acme.fr"]["state"] == "draft"
        and rows["Hébergement acme.fr"]["quote"]["id"] == doc.id
    )


def test_after_renewal_next_period_gets_a_new_quote(client, db):
    acme = company(client)
    c = contract(client, acme, renewal_date=str(TODAY + timedelta(days=5)))
    client_renewals.prepare(db, TODAY)
    # L'échéance passe : la date avance d'un an, et le devis suivant est préparé 30 jours avant
    assert client_renewals.roll(db, TODAY + timedelta(days=6)) == 1
    row = db.get(ClientContract, c["id"])
    db.refresh(row)
    nxt = row.renewal_date
    assert (nxt.year, nxt.month) == ((TODAY + timedelta(days=5)).year + 1, (TODAY + timedelta(days=5)).month)
    assert client_renewals.prepare(db, nxt - timedelta(days=31)) == []
    assert len(client_renewals.prepare(db, nxt - timedelta(days=30))) == 1


def test_prepare_now_and_deleted_draft(client, db):
    acme = company(client)
    contract(client, acme, renewal_date=str(TODAY + timedelta(days=200)))
    r = client.post(f"/api/client-contracts/prepare?company_id={acme}").json()
    assert len(r["created"]) == 1 and r["created"][0]["total_ht"] == 600
    # Brouillon supprimé : pas recréé tout seul, mais « préparer maintenant » le refait
    client.delete(f"/api/billing/{r['created'][0]['id']}")
    (row,) = client.get("/api/client-contracts").json()
    assert row["renewal"]["state"] == "deleted"
    assert client_renewals.prepare(db, TODAY + timedelta(days=190)) == []
    assert len(client.post("/api/client-contracts/prepare").json()["created"]) == 1


def test_validation_dashboard_and_permissions(client, as_role):
    acme = company(client)
    assert (
        client.post(
            "/api/client-contracts",
            json={"company_id": 999, "name": "x", "unit_price": 1, "renewal_date": str(TODAY)},
        ).status_code
        == 400
    )
    c = contract(client, acme)
    assert (
        client.put(
            f"/api/client-contracts/{c['id']}",
            json={
                **{k: c[k] for k in ("company_id", "name", "kind", "unit_price", "renewal_date")},
                "unit_price": 700,
            },
        ).json()["unit_price"]
        == 700
    )
    up = client.get("/api/dashboard").json()["finance"]["client_renewals"]
    assert up["count"] == 1 and up["with_quote"] == 0 and up["amount_ht"] == 700
    assert as_role("member").get("/api/client-contracts").status_code == 403
    assert client.delete(f"/api/client-contracts/{c['id']}").status_code == 204
