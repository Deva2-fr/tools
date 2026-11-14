from datetime import date, timedelta

from sqlalchemy import select

from app.models import Alert, BankAccount, BillingDoc, Employee, Payment, TimeEntry, Transaction
from app.services import finance, qonto
from tests.test_qonto import ORG, TX_PAGE_1, TX_PAGE_2, fake

TODAY = date.today()


def account(db):
    acc = BankAccount(name="Banque", initial_balance=10_000)
    db.add(acc)
    db.commit()
    return acc


def tx(db, acc, amount, label="Divers", days_ago=0, **kw):
    t = Transaction(
        account_id=acc.id, tx_date=TODAY - timedelta(days=days_ago), label=label, amount=amount, **kw
    )
    db.add(t)
    db.commit()
    return t


def invoice(db, company_id, ttc=1200.0, days_ago=10, paid=0.0, number="FAC-2026-0007"):
    d = BillingDoc(
        kind="invoice",
        status="paid" if paid >= ttc else "sent",
        number=number,
        company_id=company_id,
        title="Site",
        issue_date=TODAY - timedelta(days=days_ago),
        total_ht=round(ttc / 1.2, 2),
        total_vat=round(ttc - ttc / 1.2, 2),
        total_ttc=ttc,
        amount_paid=paid,
        created_by="t",
    )
    db.add(d)
    db.commit()
    return d


def test_categories_from_builtin_rules_qonto_and_user_rules(client, db):
    acc = account(db)
    ovh = tx(db, acc, -49.9, "OVH SAS")
    fee = tx(db, acc, -9, "Abonnement", operation_type="qonto_fee")
    inc = tx(db, acc, 1200, "ACME virement")
    odd = tx(db, acc, -30, "Boutique Martin")
    assert finance.categorize(db) == 4
    assert (ovh.hub_category, fee.hub_category, inc.hub_category, odd.hub_category) == (
        "Hébergement & domaines",
        "Frais bancaires",
        finance.INCOME,
        finance.OTHER,
    )
    # Choix manuel + mot à retenir : les mouvements semblables suivent, le choix manuel reste
    other = tx(db, acc, -12, "BOUTIQUE MARTIN Paris")
    r = client.put(
        f"/api/finance/transactions/{odd.id}/category",
        json={"category": "Matériel", "pattern": "boutique martin"},
    )
    assert r.status_code == 200 and r.json()["locked"] is True
    db.refresh(other)
    assert other.hub_category == "Matériel"
    assert (
        client.put(
            f"/api/finance/transactions/{odd.id}/category", json={"category": "N'existe pas"}
        ).status_code
        == 400
    )
    rules = client.get("/api/finance/rules").json()
    assert rules == [{"id": rules[0]["id"], "pattern": "boutique martin", "category": "Matériel"}]
    client.delete(f"/api/finance/rules/{rules[0]['id']}")
    db.refresh(other)
    db.refresh(odd)
    assert other.hub_category == finance.OTHER and odd.hub_category == "Matériel"  # manuel conservé


def test_overview_series_runway_and_vat(client, db):
    acc = account(db)
    for m in range(1, 4):  # 3 mois pleins : +2 000 / -5 000
        when = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10) - timedelta(days=31 * (m - 1))
        db.add(Transaction(account_id=acc.id, tx_date=when, label="Client", amount=2000))
        db.add(Transaction(account_id=acc.id, tx_date=when, label="URSSAF", amount=-5000, vat_amount=None))
    tx(db, acc, -120, "Achat", vat_amount=20)  # TVA déductible ce trimestre
    tx(db, acc, 500, "Mon autre compte", hub_category=finance.INTERNAL)  # ignoré
    db.commit()
    finance.categorize(db)
    inv = invoice(db, None, ttc=1200, days_ago=0)
    inv.payments.append(Payment(paid_on=TODAY, amount=600, method="Virement"))
    db.commit()
    o = client.get("/api/finance/overview?months=6").json()
    assert len(o["series"]) == 6 and o["series"][-1]["month"] == finance.month_key(TODAY)
    assert o["avg_net_3m"] == -3000 and o["series"][-2]["income"] == 2000
    assert o["runway_months"] == round(o["balance"] / 3000, 1)
    assert o["vat"]["collected"] == 100 and o["vat"]["deductible"] == 20 and o["vat"]["due"] == 80


def test_budget_alert_once_per_month(client, db):
    acc = account(db)
    tx(db, acc, -300, "OVH")
    finance.categorize(db)
    assert (
        client.put(
            "/api/finance/budgets", json={"category": "Hébergement & domaines", "monthly_amount": 200}
        ).status_code
        == 200
    )
    rows = {r["category"]: r for r in client.get("/api/finance/categories?months=3").json()["rows"]}
    assert rows["Hébergement & domaines"]["over_budget"] is True
    assert finance.check_budgets(db) == 1 and finance.check_budgets(db) == 0
    assert (
        db.scalar(select(Alert).where(Alert.kind == "budget")).title
        == "Budget dépassé : Hébergement & domaines"
    )
    client.put("/api/finance/budgets", json={"category": "Hébergement & domaines", "monthly_amount": None})
    assert client.get("/api/finance/budgets").json() == {}


def test_client_profitability(client, db):
    acme = client.post("/api/crm/companies", json={"name": "Acme", "kind": "client"}).json()["id"]
    db.add(Employee(name="Bob", email="bob@test.fr", daily_cost=350))  # 50 €/h
    db.add(TimeEntry(user_email="bob@test.fr", work_date=TODAY, hours=10, company_id=acme, billable=True))
    db.commit()
    invoice(db, acme, ttc=1200, paid=600)
    (row,) = client.get("/api/finance/clients?months=12").json()
    assert row["company"] == "Acme" and row["invoiced_ht"] == 1000 and row["collected"] == 600
    assert (
        row["time_cost"] == 500
        and row["margin"] == 500
        and row["margin_pct"] == 50
        and row["hourly_value"] == 100
    )


def test_missing_receipts_reconciliation_and_export(client, db):
    acme = client.post("/api/crm/companies", json={"name": "Acme", "kind": "client"}).json()["id"]
    acc = account(db)
    card = tx(db, acc, -59, "Restaurant Le Midi", operation_type="card")
    tx(db, acc, -59, "Restaurant justifié", operation_type="card", attachment_count=1)
    tx(db, acc, -800, "DGFIP TVA", operation_type="direct_debit", attachment_required=True)
    finance.categorize(db)
    assert [r["id"] for r in client.get("/api/finance/receipts").json()] == [card.id]

    inv = invoice(db, acme, ttc=1200, number="FAC-2026-0042")
    pay = tx(db, acc, 1200, "VIR ACME FAC-2026-0042")
    finance.categorize(db)
    rec = client.get("/api/finance/reconciliation").json()
    (u,) = rec["unmatched"]
    assert u["id"] == pay.id and u["suggestion"]["id"] == inv.id and u["suggestion"]["company"] == "Acme"
    assert (
        client.put(f"/api/finance/transactions/{card.id}/match", json={"billing_doc_id": inv.id}).status_code
        == 400
    )
    m = client.put(f"/api/finance/transactions/{pay.id}/match", json={"billing_doc_id": inv.id}).json()
    assert m["invoice"]["number"] == "FAC-2026-0042"
    rec = client.get("/api/finance/reconciliation").json()
    assert rec["unmatched"] == [] and rec["matched"][0]["id"] == pay.id

    r = client.get(f"/api/finance/export.csv?start={TODAY - timedelta(days=5)}&end={TODAY}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8-sig")
    assert (
        text.splitlines()[0].startswith("Date;Libellé;Montant")
        and "FAC-2026-0042" in text
        and "-59,00" in text
    )


def test_qonto_sync_keeps_receipt_and_vat_details(db):
    t3 = {**TX_PAGE_2["transactions"][0], "vat_amount": 1.67, "attachment_ids": []}
    qonto.sync(db, client=fake(pages=(TX_PAGE_1, {**TX_PAGE_2, "transactions": [t3]})))
    card = db.scalar(select(Transaction).where(Transaction.external_id == "t3"))
    assert card.operation_type == "card" and card.vat_amount == 1.67 and card.attachment_count == 0
    ovh = db.scalar(select(Transaction).where(Transaction.external_id == "t2"))
    assert ovh.hub_category == "Hébergement & domaines"  # classé dès l'import
    # Justificatif ajouté ensuite dans Qonto : mis à jour à la synchronisation suivante
    t3b = {**t3, "attachment_ids": ["a1"]}
    qonto.sync(db, client=fake(org=ORG, pages=(TX_PAGE_1, {**TX_PAGE_2, "transactions": [t3b]})))
    db.refresh(card)
    assert card.attachment_count == 1


def test_finance_is_for_managers(as_role):
    member = as_role("member")
    for path in ("/api/finance/overview", "/api/finance/clients", "/api/finance/receipts"):
        assert member.get(path).status_code == 403, path
