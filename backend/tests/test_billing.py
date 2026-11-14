from datetime import date, timedelta

import pytest

from app.models import BillingDoc, Payment
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


def emitted(db, doc_id, status="sent", number="FAC-2026-0001"):
    """Document déjà émis (avant la règle « brouillons seulement », ou synchronisé depuis Qonto)."""
    d = db.get(BillingDoc, doc_id)
    d.status, d.number = status, number
    db.commit()
    return d


def test_hub_documents_stay_drafts(client, acme):
    """Le Hub ne fait que des brouillons : ni émission, ni statut, ni paiement, ni transformation."""
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    q = client.post("/api/billing", json=doc("quote", company_id=acme)).json()["id"]
    for path, body in (
        (f"/api/billing/{i}/issue", None),
        (f"/api/billing/{q}/status", {"status": "accepted"}),
        (f"/api/billing/{q}/convert", None),
        (f"/api/billing/{i}/payments", {"paid_on": TODAY.isoformat(), "amount": 100}),
    ):
        assert client.post(path, json=body).status_code in (404, 405), path
    for d in (i, q):
        assert client.get(f"/api/billing/{d}").json()["status"] == "draft"
    # Un brouillon reste modifiable et supprimable
    assert (
        client.put(f"/api/billing/{i}", json=doc(company_id=acme, title="Autre")).json()["title"] == "Autre"
    )
    assert client.delete(f"/api/billing/{i}").status_code == 204


def test_emitted_document_is_read_only(client, db, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    emitted(db, i)
    assert client.put(f"/api/billing/{i}", json=doc(company_id=acme)).status_code == 400
    assert client.delete(f"/api/billing/{i}").status_code == 400


def test_pdf_renders(client, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
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
    emitted(db, i)
    assert client.get("/api/billing?status=overdue").json()[0]["is_overdue"] is True
    assert billing.send_reminders(db, TODAY) == 1
    assert billing.send_reminders(db, TODAY) == 0  # même palier : pas de doublon
    assert billing.send_reminders(db, TODAY + timedelta(days=8)) == 1  # palier suivant
    d = db.get(BillingDoc, i)
    assert billing.overdue(d, TODAY) and not billing.overdue(d, TODAY - timedelta(days=30))


def test_summary(client, db, acme):
    i = client.post("/api/billing", json=doc(company_id=acme)).json()["id"]
    d = emitted(db, i)
    d.payments.append(Payment(paid_on=TODAY, amount=200, method="virement", note=""))  # remonté par Qonto
    d.amount_paid = 200
    db.commit()
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
