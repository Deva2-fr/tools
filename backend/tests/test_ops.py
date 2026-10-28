from datetime import date, timedelta

from sqlalchemy import select

from app.models import Alert, Subscription
from app.services import digest, renewals, treasury

TODAY = date.today()


def sub(client, **kw):
    body = {
        "name": "OVH",
        "kind": "domain",
        "cost": 12,
        "period": "yearly",
        "renewal_date": (TODAY + timedelta(days=30)).isoformat(),
        **kw,
    }
    r = client.post("/api/subscriptions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_annual_cost_and_summary(client):
    sub(client, name="Slack", kind="saas", cost=10, period="monthly")
    sub(client, name="Assurance", kind="insurance", cost=300, period="quarterly")
    sub(client, name="Domaine", cost=12)
    s = client.get("/api/subscriptions-summary").json()
    assert s["annual_total"] == 120 + 1200 + 12 and s["by_kind"]["insurance"] == 1200


def test_occurrences_and_roll(db):
    s = Subscription(
        name="x", cost=5, period="monthly", renewal_date=date(2026, 1, 31), auto_renew=True, active=True
    )
    assert renewals.occurrences(s, date(2026, 1, 1), date(2026, 4, 1)) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]
    s.auto_renew = False
    assert renewals.occurrences(s, date(2026, 1, 1), date(2026, 4, 1)) == [date(2026, 1, 31)]
    assert renewals.occurrences(s, date(2026, 2, 1), date(2026, 4, 1)) == []
    db.add(
        Subscription(
            name="auto", cost=1, period="yearly", renewal_date=TODAY - timedelta(days=10), auto_renew=True
        )
    )
    db.add(
        Subscription(
            name="manuel", cost=1, period="yearly", renewal_date=TODAY - timedelta(days=10), auto_renew=False
        )
    )
    db.commit()
    assert renewals.roll_renewals(db) == 1
    rolled = {x.name: x.renewal_date for x in db.scalars(select(Subscription))}
    assert rolled["auto"] > TODAY and rolled["manuel"] < TODAY


def test_renewal_reminders_once(client, db):
    sub(client, renewal_date=(TODAY + timedelta(days=30)).isoformat(), notice_days=30)
    assert renewals.send_reminders(db, TODAY) == 1
    assert renewals.send_reminders(db, TODAY) == 0
    assert renewals.send_reminders(db, TODAY + timedelta(days=5)) == 0  # pas un palier
    assert renewals.send_reminders(db, TODAY + timedelta(days=23)) == 1  # J-7


def test_treasury_balance_forecast_and_import(client, db):
    acc = client.post("/api/accounts", json={"name": "Pro", "initial_balance": 1000}).json()["id"]
    csv_text = "Date;Libellé;Montant\n01/10/2026;Virement client;1 234,50\n02/10/2026;Loyer;-800,00\n02/10/2026;Loyer;-800,00\nxx;Bad;1\n"
    r = client.post("/api/transactions/import", json={"account_id": acc, "csv": csv_text}).json()
    assert r["created"] == 2 and len(r["errors"]) == 1  # doublon exact ignoré, date illisible signalée
    assert (
        client.post("/api/transactions/import", json={"account_id": acc, "csv": csv_text}).json()["created"]
        == 0
    )
    assert treasury.current_balance(db) == 1000 + 1234.5 - 800
    c = client.post("/api/crm/companies", json={"name": "Acme"}).json()["id"]
    i = client.post(
        "/api/billing",
        json={
            "kind": "invoice",
            "company_id": c,
            "issue_date": TODAY.isoformat(),
            "due_date": (TODAY + timedelta(days=10)).isoformat(),
            "lines": [{"description": "x", "quantity": 1, "unit_price": 1000, "vat_rate": 20}],
        },
    ).json()["id"]
    client.post(f"/api/billing/{i}/issue")
    client.post(
        "/api/taxes",
        json={"title": "TVA", "due_date": (TODAY + timedelta(days=20)).isoformat(), "amount": 500},
    )
    f = client.get("/api/treasury/forecast?days=60").json()
    assert f["balance"] == 1434.5
    kinds = {e["type"]: e["amount"] for e in f["events"]}
    assert kinds["invoice"] == 1200 and kinds["tax"] == -500
    assert f["end_balance"] == 1434.5 + 1200 - 500


def test_amount_parsing():
    assert (
        treasury.parse_amount("1 234,56") == 1234.56
        and treasury.parse_amount("1.234,56") == 1234.56
        and treasury.parse_amount("-12.5") == -12.5
    )
    assert treasury.parse_date("05/03/2026") == date(2026, 3, 5) and treasury.parse_date(
        "2026-03-05"
    ) == date(2026, 3, 5)


def test_time_entries_scope_and_report(client, as_role):
    co = client.post("/api/crm/companies", json={"name": "Acme"}).json()["id"]
    client.post("/api/employees", json={"name": "Mem", "email": "member@test.fr", "daily_cost": 350})
    member = as_role("member")
    other = as_role("member", "other@test.fr")
    t = member.post(
        "/api/time", json={"work_date": TODAY.isoformat(), "hours": 7, "company_id": co, "hourly_rate": 100}
    ).json()
    other.post("/api/time", json={"work_date": TODAY.isoformat(), "hours": 3})
    assert len(member.get("/api/time").json()) == 1  # un membre ne voit que son temps
    assert len(client.get("/api/time").json()) == 2  # l'admin voit tout
    assert other.delete(f"/api/time/{t['id']}").status_code == 404  # et ne touche pas à celui des autres
    assert member.get("/api/time/report").status_code == 403
    rep = client.get("/api/time/report").json()
    row = next(r for r in rep["rows"] if r["company_id"] == co)
    assert row["hours"] == 7 and row["sales_value"] == 700 and row["cost"] == 350
    assert client.post("/api/time", json={"work_date": TODAY.isoformat(), "hours": 25}).status_code == 422


def test_leaves_workflow(client, as_role):
    member = as_role("member")
    body = {"start_date": "2026-12-21", "end_date": "2026-12-28"}  # lun → lun : 6 jours ouvrés
    assert member.post("/api/leaves", json=body).status_code == 400  # pas de fiche collaborateur
    emp = client.post(
        "/api/employees", json={"name": "Mem", "email": "member@test.fr", "leave_days_per_year": 25}
    ).json()
    lv = member.post("/api/leaves", json=body)
    assert lv.status_code == 201 and lv.json()["days"] == 6 and lv.json()["status"] == "pending"
    assert (
        member.post("/api/leaves", json={"start_date": "2026-12-26", "end_date": "2026-12-27"}).status_code
        == 400
    )  # week-end
    assert (
        member.post("/api/leaves", json={"start_date": "2026-12-30", "end_date": "2026-12-01"}).status_code
        == 422
    )
    assert (
        member.post(f"/api/leaves/{lv.json()['id']}/decide", json={"status": "approved"}).status_code == 403
    )
    assert (
        client.post(f"/api/leaves/{lv.json()['id']}/decide", json={"status": "approved"}).json()["decided_by"]
        == "admin@test.fr"
    )
    assert client.get("/api/leaves/calendar").json()[0]["employee"] == "Mem"
    assert member.get("/api/leaves/balances").status_code == 403
    bal = client.get("/api/leaves/balances").json()[0]
    assert bal["employee_id"] == emp["id"] and bal["used"] == 6 and bal["left"] == 19
    assert (
        member.delete(f"/api/leaves/{lv.json()['id']}").status_code == 404
    )  # déjà validée : plus annulable par le membre


def test_file_vault_security(client, as_role):
    pdf = ("a.pdf", b"%PDF-1.4 test", "application/pdf")
    r = client.post("/api/files", files={"file": pdf}, data={"name": "Kbis", "category": "legal"})
    assert r.status_code == 201 and "stored_name" not in r.json()
    fid = r.json()["id"]
    dl = client.get(f"/api/files/{fid}/download")
    assert dl.content == b"%PDF-1.4 test" and "attachment" in dl.headers["content-disposition"]
    assert client.post("/api/files", files={"file": ("x.html", b"<script>", "text/html")}).status_code == 400
    assert client.post("/api/files", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}).status_code == 400
    assert (
        client.post(
            "/api/files", files={"file": ("fake.pdf", b"MZ not a pdf", "application/pdf")}
        ).status_code
        == 400
    )
    assert (
        client.post("/api/files", files={"file": ("../../etc/p.pdf", b"%PDF", "application/pdf")}).json()[
            "original_name"
        ]
        == "p.pdf"
    )
    assert (
        client.post(
            "/api/files", files={"file": ("big.pdf", b"%PDF" + b"0" * (15 * 1024 * 1024), "application/pdf")}
        ).status_code
        == 413
    )
    assert as_role("member").get(f"/api/files/{fid}/download").status_code == 403
    assert client.delete(f"/api/files/{fid}").status_code == 204
    assert client.get(f"/api/files/{fid}/download").status_code == 404


def test_access_registry_and_audit(client):
    a = client.post(
        "/api/access",
        json={"system": "OVH", "secret_location": "Bitwarden > Deva2", "rotate_every_days": 180},
    ).json()
    assert (
        client.put(f"/api/access/{a['id']}", json={"system": "OVH", "holders": "Hugo"}).json()["holders"]
        == "Hugo"
    )
    log = client.get("/api/users/audit/log").json()
    assert {"access_created", "access_updated"} <= {x["action"] for x in log}


def test_public_status_exposes_only_flagged_projects(client, anon):
    projs = client.get("/api/projects").json()
    p = projs[0]
    assert anon.get("/api/public/status").json() == {"overall": "unknown", "services": []}
    body = {
        k: p[k]
        for k in (
            "name",
            "url",
            "description",
            "environment",
            "repo_url",
            "monitoring_tools",
            "notes",
            "monitoring_enabled",
            "check_interval_min",
            "expected_status",
        )
    }
    client.put(f"/api/projects/{p['id']}", json={**body, "public_status": True})
    data = anon.get("/api/public/status").json()
    assert data["services"] == [{"name": p["name"], "status": "unknown"}]
    assert set(data["services"][0]) == {"name", "status"}  # aucune URL, IP ou note exposée


def test_digest_builds_and_dedupes(client, db):
    client.post(
        "/api/crm/tasks", json={"title": "Appeler Bob", "due_date": (TODAY - timedelta(days=1)).isoformat()}
    )
    lines = digest.build(db)
    assert any("tâche" in line for line in lines)
    first = digest.send(db)
    assert first is True and digest.send(db) is False
    assert db.scalar(select(Alert).where(Alert.kind == "digest")) is not None


def test_dashboard_finance_only_for_managers(client, as_role):
    assert client.get("/api/dashboard").json()["finance"]["balance"] == 0
    assert as_role("member").get("/api/dashboard").json()["finance"] is None
    assert as_role("manager").get("/api/dashboard").json()["finance"] is not None


def test_role_assignment_validation(client):
    assert (
        client.post(
            "/api/users", json={"email": "z@test.fr", "password": "long-enough-password", "role": "root"}
        ).status_code
        == 422
    )
