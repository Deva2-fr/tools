from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.models import Alert, AlertChannel, Expense, Project, TaxDeadline, Technology, Vulnerability
from app.services import google_docs, monitoring, outlook, security_watch, taxes
from app.services.alerts import create_alert


def test_alert_dedupe(db):
    assert create_alert(db, "ssl", "warning", "t", dedupe_key="k", cooldown_hours=1)
    assert create_alert(db, "ssl", "warning", "t", dedupe_key="k", cooldown_hours=1) is None
    assert create_alert(db, "ssl", "warning", "t", dedupe_key="other")


def test_alert_dispatch_failure_is_recorded(db):
    from app.core.crypto import encrypt_json

    db.add(
        AlertChannel(
            name="Broken",
            type="webhook",
            config_enc=encrypt_json({"url": "http://127.0.0.1:1/x"}),
            min_severity="info",
        )
    )
    db.commit()
    a = create_alert(db, "down", "critical", "boom")
    assert "ÉCHEC" in a.delivery


def test_down_alert_after_two_failures_then_recovery(db, monkeypatch):
    p = db.scalar(select(Project))
    state = {"ok": False}

    def fake_http(project, timeout=15):
        return {
            "ok": state["ok"],
            "status_code": 200 if state["ok"] else None,
            "latency_ms": 50,
            "error": "" if state["ok"] else "ConnectError",
            "missing_headers": [],
        }

    monkeypatch.setattr(monitoring, "probe_http", fake_http)
    monkeypatch.setattr(monitoring, "probe_ssl", lambda url: None)
    monitoring.run_check(db, p)
    assert not db.scalars(select(Alert).where(Alert.kind == "down")).all()  # 1 échec : pas d'alerte
    monitoring.run_check(db, p)
    assert len(db.scalars(select(Alert).where(Alert.kind == "down")).all()) == 1
    monitoring.run_check(db, p)  # toujours down : pas de doublon
    assert len(db.scalars(select(Alert).where(Alert.kind == "down")).all()) == 1
    state["ok"] = True
    monitoring.run_check(db, p)
    assert p.status == "up" and len(db.scalars(select(Alert).where(Alert.kind == "recovered")).all()) == 1


def test_ssl_expiry_alert(db, monkeypatch):
    p = db.scalar(select(Project))
    monkeypatch.setattr(
        monitoring,
        "probe_http",
        lambda pr, timeout=15: {
            "ok": True,
            "status_code": 200,
            "latency_ms": 10,
            "error": "",
            "missing_headers": [],
        },
    )
    monkeypatch.setattr(
        monitoring,
        "probe_ssl",
        lambda url: {"expires": datetime.now(UTC) + timedelta(days=5), "fingerprint": "abc", "error": ""},
    )
    monitoring.run_check(db, p)
    a = db.scalar(select(Alert).where(Alert.kind == "ssl"))
    assert a and a.severity == "warning"


def test_cve_scan_alerts_only_serious_and_recent(db):
    p = db.scalar(select(Project))
    t = Technology(project_id=p.id, name="nginx", version="1.24")
    db.add(t)
    db.commit()
    now = datetime.now(UTC)
    fake = [
        {"cve_id": "CVE-2026-0001", "cvss": 9.8, "summary": "RCE", "published": now - timedelta(days=10)},
        {"cve_id": "CVE-2026-0002", "cvss": 5.0, "summary": "meh", "published": now - timedelta(days=10)},
        {"cve_id": "CVE-2015-0003", "cvss": 9.9, "summary": "old", "published": now - timedelta(days=4000)},
        {
            "cve_id": "CVE-2015-0004",
            "cvss": 3.0,
            "summary": "old but exploited",
            "published": now - timedelta(days=4000),
        },
    ]
    n = security_watch.scan_technology(db, t, {"CVE-2015-0004"}, nvd=lambda d, tech: fake)
    assert n == 2
    assert db.scalar(select(Vulnerability).where(Vulnerability.cve_id == "CVE-2015-0004")).exploited
    assert security_watch.scan_technology(db, t, set(), nvd=lambda d, tech: fake) == 0  # pas de doublon


def test_parse_nvd():
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-1",
                    "published": "2026-09-01T10:00:00.000",
                    "descriptions": [{"lang": "en", "value": "bad"}],
                    "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.1}}]},
                }
            }
        ]
    }
    out = security_watch.parse_nvd(payload)
    assert out[0]["cvss"] == 9.1 and out[0]["published"].tzinfo


def test_tax_reminders(db):
    today = date(2027, 3, 1)
    db.add_all(
        [
            TaxDeadline(title="A", due_date=date(2027, 3, 8)),  # J-7 -> rappel
            TaxDeadline(title="B", due_date=date(2027, 3, 20)),  # J-19 -> rien
            TaxDeadline(title="C", due_date=date(2027, 2, 25)),  # en retard
            TaxDeadline(title="D", due_date=date(2027, 3, 8), status="paid"),
        ]
    )
    db.commit()
    assert taxes.send_reminders(db, today) == 2
    assert taxes.send_reminders(db, today) == 0  # pas de doublon le même jour


def test_next_due_edges():
    assert taxes.next_due(date(2027, 1, 31), "monthly") == date(2027, 2, 28)
    assert taxes.next_due(date(2027, 12, 15), "monthly") == date(2028, 1, 15)
    assert taxes.next_due(date(2027, 11, 30), "quarterly") == date(2028, 2, 29)
    assert taxes.next_due(date(2028, 2, 29), "yearly") == date(2029, 2, 28)


def test_mail_classification():
    f = outlook.classify
    assert (
        f("client@acme.fr", "Devis", "Pouvez-vous m'envoyer le devis ?", "moi@deva2.fr", False)
        == "a_repondre"
    )
    assert f("noreply@github.com", "Notification", "Merci de confirmer ?", "moi@deva2.fr", False) == "info"
    assert f("client@acme.fr", "Re: devis", "Pouvez-vous ?", "moi@deva2.fr", True) == "repondu"
    assert f("client@acme.fr", "Info", "Voici le compte rendu.", "moi@deva2.fr", False) == "info"
    assert outlook.is_urgent("URGENT", "")


def test_google_placeholders_and_requests():
    e = Expense(
        id=7,
        expense_date=date(2026, 10, 1),
        employee="Hugo",
        reason="Train",
        category="Transport",
        project="",
        payment_method="CB",
        amount_ttc=120,
        vat_rate=20,
        amount_ht=100,
        amount_vat=20,
        notes="",
    )
    v = google_docs.placeholders(e)
    assert v["numero"] == "NDF-202610-0007" and v["montant_ttc"] == "120,00 €" and v["taux_tva"] == "20 %"
    reqs = google_docs.replace_requests(v)
    assert {
        "replaceAllText": {"containsText": {"text": "{{motif}}", "matchCase": True}, "replaceText": "Train"}
    } in reqs
    assert any(r["replaceAllText"]["replaceText"] == "—" for r in reqs)  # champ vide
