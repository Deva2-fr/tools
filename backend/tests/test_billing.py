from datetime import date, timedelta

import pytest

from app.models import BillingDoc
from app.services import billing

TODAY = date.today()


def doc(kind="invoice", lines=None, company_id=None, **kw):
    return {
        "kind": kind,
        "company_id": company_id,
        "issue_date": TODAY.isoformat(),
        "title": "Prestation",
        "lines": lines or [{"description": "Dév", "quantity": 2, "unit_price": 500, "vat_rate": 20}],
        **kw,
    }


@pytest.fixture()
def acme(client):
    return client.post(
        "/api/crm/companies", json={"name": "Acme", "kind": "client", "address": "1 rue X", "city": "Paris"}
    ).json()["id"]


def test_totals_vat_per_rate_rounding():
    class L:
        def __init__(self, q, p, v):
            self.quantity, self.unit_price, self.vat_rate = q, p, v

    # TVA calculée par taux sur la somme, pas ligne par ligne
    ht, vat, ttc = billing.compute_totals([L(1, 0.33, 20), L(1, 0.33, 20), L(1, 0.33, 20), L(3, 10, 5.5)])
    assert (
        ht == 30.99
        and vat == round(round(0.99 * 0.2, 2) + round(30 * 0.055, 2), 2)
        and ttc == round(ht + vat, 2)
    )


def test_create_totals_and_draft_has_no_number(client, acme):
    d = client.post("/api/billing", json=doc(company_id=acme)).json()
    assert (d["total_ht"], d["total_vat"], d["total_ttc"]) == (1000, 200, 1200)
    assert d["number"] is None and d["status"] == "draft"
    assert d["due_date"] == (TODAY + timedelta(days=30)).isoformat()


def test_numbering_is_sequential_without_gaps(client, acme):
    ids = [client.post("/api/billing", json=doc(company_id=acme)).json()["id"] for _ in range(3)]
    client.delete(f"/api/billing/{ids[1]}")  # un brouillon supprimé ne consomme aucun numéro
    n1 = client.post(f"/api/billing/{ids[0]}/issue").json()["number"]
    n2 = client.post(f"/api/billing/{ids[2]}/issue").json()["number"]
    y = TODAY.year
    assert (n1, n2) == (f"FAC-{y}-0001", f"FAC-{y}-0002")
    q = client.post("/api/billing", json=doc("quote", company_id=acme)).json()["id"]
    assert client.post(f"/api/billing/{q}/issue").status_code == 400  # devis : officiel dans Qonto seulement


def test_issued_invoice_is_immutable_and_undeletable(client, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    client.post(f"/api/billing/{i}/issue")
    assert client.put(f"/api/billing/{i}", json=doc(company_id=acme)).status_code == 400
    assert client.delete(f"/api/billing/{i}").status_code == 400
    assert client.post(f"/api/billing/{i}/issue").status_code == 400  # déjà émise


def test_cannot_issue_empty_or_clientless_invoice(client, acme):
    e = client.post("/api/billing", json={**doc(company_id=acme), "lines": []}).json()["id"]
    assert client.post(f"/api/billing/{e}/issue").status_code == 400
    n = client.post("/api/billing", json=doc()).json()["id"]
    assert client.post(f"/api/billing/{n}/issue").status_code == 400


def test_partial_then_full_payment(client, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    assert (
        client.post(
            f"/api/billing/{i}/payments", json={"paid_on": TODAY.isoformat(), "amount": 100}
        ).status_code
        == 400
    )  # brouillon
    client.post(f"/api/billing/{i}/issue")
    r = client.post(f"/api/billing/{i}/payments", json={"paid_on": TODAY.isoformat(), "amount": 500}).json()
    assert r["status"] == "sent" and r["remaining"] == 700
    assert (
        client.post(
            f"/api/billing/{i}/payments", json={"paid_on": TODAY.isoformat(), "amount": 800}
        ).status_code
        == 400
    )
    r = client.post(f"/api/billing/{i}/payments", json={"paid_on": TODAY.isoformat(), "amount": 700}).json()
    assert r["status"] == "paid" and r["remaining"] == 0
    pid = r["payments"][0]["id"]
    r = client.delete(f"/api/billing/{i}/payments/{pid}").json()
    assert r["status"] == "sent" and r["remaining"] == 500
    assert (
        client.post(f"/api/billing/{i}/status", json={"status": "cancelled"}).status_code == 400
    )  # a des paiements


def test_quote_to_invoice_once(client, db, acme):
    from app.models import BillingDoc

    q = client.post("/api/billing", json=doc("quote", company_id=acme)).json()["id"]
    assert client.post(f"/api/billing/{q}/convert").status_code == 400  # devis non émis
    db.get(BillingDoc, q).status = "sent"  # devis émis avant que les devis passent par Qonto
    db.commit()
    inv = client.post(f"/api/billing/{q}/convert")
    assert inv.status_code == 201
    body = inv.json()
    assert (
        body["kind"] == "invoice"
        and body["status"] == "draft"
        and body["source_quote_id"] == q
        and body["total_ttc"] == 1200
    )
    assert client.get(f"/api/billing/{q}").json()["status"] == "accepted"
    assert client.post(f"/api/billing/{q}/convert").status_code == 400  # déjà facturé
    client.post(f"/api/billing/{body['id']}/issue")
    client.post(f"/api/billing/{body['id']}/status", json={"status": "cancelled"})
    assert (
        client.post(f"/api/billing/{q}/convert").status_code == 201
    )  # on peut refacturer si l'autre est annulée


def test_pdf_renders(client, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    client.post(f"/api/billing/{i}/issue")
    r = client.get(f"/api/billing/{i}/pdf")
    assert (
        r.status_code == 200
        and r.content.startswith(b"%PDF")
        and r.headers["content-type"] == "application/pdf"
    )
    draft = client.post("/api/billing", json=doc(company_id=acme, title="<b>&injection</b>")).json()["id"]
    assert client.get(f"/api/billing/{draft}/pdf").content.startswith(b"%PDF")  # caractères spéciaux échappés


def test_overdue_and_reminders_without_duplicates(client, db, acme):
    i = client.post(
        "/api/billing", json=doc(company_id=acme, due_date=(TODAY - timedelta(days=8)).isoformat())
    ).json()["id"]
    client.post(f"/api/billing/{i}/issue")
    assert client.get("/api/billing?status=overdue").json()[0]["is_overdue"] is True
    assert billing.send_reminders(db, TODAY) == 1
    assert billing.send_reminders(db, TODAY) == 0  # même palier : pas de doublon
    assert billing.send_reminders(db, TODAY + timedelta(days=8)) == 1  # palier suivant
    d = db.get(BillingDoc, i)
    assert billing.overdue(d, TODAY) and not billing.overdue(d, TODAY - timedelta(days=30))


def test_summary(client, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    client.post(f"/api/billing/{i}/issue")
    client.post(f"/api/billing/{i}/payments", json={"paid_on": TODAY.isoformat(), "amount": 200})
    s = client.get("/api/billing/summary").json()
    assert s["invoiced_ht"] == 1000 and s["collected"] == 200 and s["outstanding"] == 1000


def test_members_have_no_access_to_billing(client, as_role):
    member = as_role("member")
    for path in (
        "/api/billing",
        "/api/billing/summary",
        "/api/subscriptions",
        "/api/accounts",
        "/api/employees",
        "/api/access",
        "/api/files",
    ):
        assert member.get(path).status_code == 403, path
    assert as_role("manager").get("/api/billing").status_code == 200
