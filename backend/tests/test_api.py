import json

import pyotp

from app.core.security import login_limiter

PW = "CorrectHorse-Battery-9"


def test_requires_login(anon):
    assert anon.get("/api/projects").status_code == 401


def test_login_wrong_password_and_rate_limit(anon):
    login_limiter._fails.clear()
    for _ in range(5):
        assert (
            anon.post("/api/auth/login", json={"email": "admin@test.fr", "password": "nope"}).status_code
            == 401
        )
    r = anon.post("/api/auth/login", json={"email": "admin@test.fr", "password": PW})
    assert r.status_code == 429
    login_limiter._fails.clear()


def test_csrf_header_required_for_writes(client):
    r = client.post("/api/projects", json={"name": "x", "url": "x.fr"}, headers={"X-Requested-With": ""})
    assert r.status_code == 403


def test_seeded_projects_and_crud(client):
    names = {p["name"] for p in client.get("/api/projects").json()}
    assert {"Deva2", "Formasyl", "IceTheaters (dev)"} <= names
    p = client.post("/api/projects", json={"name": "Nouveau", "url": "nouveau.fr"}).json()
    assert p["url"] == "https://nouveau.fr"
    s = client.post(f"/api/projects/{p['id']}/servers", json={"provider": "OVH", "ip": "1.2.3.4"})
    assert s.status_code == 201
    t = client.post(f"/api/projects/{p['id']}/technologies", json={"name": "nginx", "version": "1.24"})
    assert t.status_code == 201
    got = client.get(f"/api/projects/{p['id']}").json()
    assert got["servers"][0]["ip"] == "1.2.3.4" and got["technologies"][0]["name"] == "nginx"
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204


def test_totp_flow(client):
    secret = client.post("/api/auth/totp/setup").json()["secret"]
    assert client.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": "admin@test.fr", "password": PW})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@test.fr", "password": PW, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200


def test_integrations_never_return_secrets(client):
    client.put("/api/integrations/smtp_password", json={"value": "super-secret"})
    client.put("/api/integrations/smtp_host", json={"value": "smtp.example.com"})
    fields = {f["key"]: f for f in client.get("/api/integrations").json()}
    assert fields["smtp_password"]["is_set"] and fields["smtp_password"]["value"] == ""
    assert fields["smtp_host"]["value"] == "smtp.example.com"
    assert "microsoft_refresh_token" not in fields


def test_members_cannot_touch_admin_areas(client):
    client.post(
        "/api/users", json={"email": "m@test.fr", "password": "another-long-password", "role": "member"}
    )
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "m@test.fr", "password": "another-long-password"})
    assert client.get("/api/integrations").status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/projects").status_code == 200


def test_channels_hide_config_and_keep_secret_on_update(client):
    c = client.post(
        "/api/channels",
        json={"name": "Slack", "type": "slack", "config": {"webhook_url": "https://hooks.slack.com/x"}},
    ).json()
    assert c["config_keys"] == ["webhook_url"] and "hooks.slack" not in str(c)
    assert (
        client.put(
            f"/api/channels/{c['id']}",
            json={"name": "Slack 2", "type": "slack", "config": {"webhook_url": ""}},
        ).status_code
        == 200
    )
    assert (
        client.post("/api/channels", json={"name": "Bad", "type": "telegram", "config": {}}).status_code
        == 422
    )


def test_security_webhook(client, anon):
    assert (
        anon.post(
            "/api/webhooks/security", json={"title": "x"}, headers={"X-Webhook-Token": "bad"}
        ).status_code
        == 401
    )
    r = anon.post(
        "/api/webhooks/security",
        json={"title": "Brute force SSH", "severity": "critical", "project": "Deva2"},
        headers={"X-Webhook-Token": "hook-token"},
    )
    assert r.status_code == 200
    assert client.get("/api/alerts").json()[0]["kind"] == "attack"


def test_taxes_generate_paid_recurrence_and_ics(client):
    assert client.post("/api/taxes/generate?year=2027").json()["created"] == 6
    titles = {x["title"]: x for x in client.get("/api/taxes").json()}
    assert titles["TVA trimestrielle – déclaration CA3 (T4 2026)"]["due_date"] == "2027-01-20"
    assert titles["TVA trimestrielle – déclaration CA3 (T3 2027)"]["due_date"] == "2027-10-20"
    assert "Déclaration annuelle de résultats (liasse fiscale)" in titles and "CFE – avis à payer" in titles
    assert not any("URSSAF" in t or "Acompte" in t for t in titles)
    assert client.post("/api/taxes/generate?year=2027").json()["created"] == 0  # idempotent
    t = client.post(
        "/api/taxes",
        json={"title": "TVA janvier", "category": "tva", "due_date": "2027-01-31", "recurrence": "monthly"},
    ).json()
    client.post(f"/api/taxes/{t['id']}/paid")
    nxt = [
        x for x in client.get("/api/taxes").json() if x["title"] == "TVA janvier" and x["status"] == "todo"
    ]
    assert nxt[0]["due_date"] == "2027-02-28"
    ics = client.get("/api/taxes/calendar.ics")
    assert ics.text.startswith("BEGIN:VCALENDAR") and "TVA janvier" in ics.text


def test_expense_pdf_without_google_drive(client):
    body = {
        "expense_date": "2026-10-01",
        "reason": "Train Paris",
        "amount_ttc": 120,
        "vat_rate": 20,
        "employee": "Hugo",
    }
    e = client.post("/api/expenses", json=body).json()
    assert e["amount_ht"] == 100.0 and e["amount_vat"] == 20.0
    r = client.post("/api/expenses/save", data={"data": json.dumps(body)})
    # Sans Google : le PDF est quand même généré et téléchargé, Drive est signalé « non configuré ».
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["x-drive-status"] == "not_configured"
    assert "NDF-202610-" in r.headers["content-disposition"]
    eid = r.headers["x-expense-id"]
    assert client.get(f"/api/expenses/{eid}/pdf").content.startswith(b"%PDF")
    assert client.post(f"/api/expenses/{eid}/drive").status_code == 400


def test_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert d["projects"]["total"] >= 3 and d["mails_to_reply"] == 0
