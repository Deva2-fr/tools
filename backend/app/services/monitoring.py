import hashlib
import socket
import ssl
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import CheckResult, Project
from app.services.alerts import create_alert

FAILURE_THRESHOLD = 2  # nombre d'échecs consécutifs avant l'alerte « site down »
SSL_WARN_DAYS = 14
SECURITY_HEADERS = {
    "strict-transport-security": "HSTS",
    "content-security-policy": "CSP",
    "x-content-type-options": "X-Content-Type-Options",
    "referrer-policy": "Referrer-Policy",
}


def probe_http(project: Project, timeout: float = 15) -> dict:
    start = time.perf_counter()
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, headers={"User-Agent": "Deva2Hub-Monitor/1.0"}
        ) as client:
            resp = client.get(project.url)
        latency = int((time.perf_counter() - start) * 1000)
        expected = project.expected_status
        ok = resp.status_code == expected if expected else resp.status_code < 500
        headers = {k.lower() for k in resp.headers}
        csp = resp.headers.get("content-security-policy", "")
        missing = [label for h, label in SECURITY_HEADERS.items() if h not in headers]
        if "x-frame-options" not in headers and "frame-ancestors" not in csp:
            missing.append("X-Frame-Options")
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "latency_ms": latency,
            "error": "" if ok else f"HTTP {resp.status_code}",
            "missing_headers": missing if project.url.startswith("https") else [],
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": None,
            "error": f"{exc.__class__.__name__}: {exc}"[:480],
        }


def probe_ssl(url: str, timeout: float = 10) -> dict | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host, port = parsed.hostname, parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                der = tls.getpeercert(binary_form=True)
        expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), UTC)
        return {"expires": expires, "fingerprint": hashlib.sha256(der).hexdigest(), "error": ""}
    except (ssl.SSLError, OSError) as exc:
        return {"expires": None, "fingerprint": None, "error": f"{exc.__class__.__name__}: {exc}"[:200]}


def run_check(db: Session, project: Project) -> CheckResult:
    http = probe_http(project)
    tls = probe_ssl(project.url)
    now = utcnow()

    days_left = None
    if tls and tls["expires"]:
        days_left = (tls["expires"] - now).days
    result = CheckResult(
        project_id=project.id,
        ts=now,
        ok=http["ok"],
        status_code=http["status_code"],
        latency_ms=http["latency_ms"],
        error=http["error"],
        ssl_days_left=days_left,
    )
    db.add(result)

    previous_days = (
        (project.ssl_expires_at - project.last_checked_at).days
        if (project.ssl_expires_at and project.last_checked_at)
        else None
    )
    _evaluate(db, project, http, tls, days_left, previous_days)

    project.last_checked_at = now
    project.last_latency_ms = http["latency_ms"]
    project.missing_headers = http.get("missing_headers", [])
    if tls and tls["expires"]:
        project.ssl_expires_at = tls["expires"]
        project.cert_fingerprint = tls["fingerprint"]
    db.commit()
    _prune(db, project.id)
    return result


def _evaluate(db: Session, project: Project, http: dict, tls: dict | None, days_left, previous_days) -> None:
    pid, name = project.id, project.name

    if http["ok"]:
        if project.consecutive_failures >= FAILURE_THRESHOLD:
            create_alert(
                db,
                "recovered",
                "info",
                f"✅ {name} est de nouveau en ligne",
                f"{project.url} répond à nouveau ({http['latency_ms']} ms).",
                pid,
            )
        project.consecutive_failures = 0
        project.status = "up"
        _latency_spike(db, project, http["latency_ms"])
    else:
        project.consecutive_failures += 1
        if project.consecutive_failures >= FAILURE_THRESHOLD:
            project.status = "down"
            if project.consecutive_failures == FAILURE_THRESHOLD:
                create_alert(
                    db,
                    "down",
                    "critical",
                    f"{name} est INACCESSIBLE",
                    f"{project.url} ne répond pas ({project.consecutive_failures} vérifications de suite) : "
                    f"{http['error']}",
                    pid,
                )

    if tls:
        if tls["error"]:
            create_alert(
                db,
                "ssl",
                "critical",
                f"Certificat SSL invalide : {name}",
                tls["error"],
                pid,
                dedupe_key=f"sslerr:{pid}",
                cooldown_hours=12,
            )
        elif days_left is not None and days_left <= SSL_WARN_DAYS:
            sev = "critical" if days_left <= 3 else "warning"
            create_alert(
                db,
                "ssl",
                sev,
                f"Certificat SSL de {name} : expire dans {days_left} j",
                "Renouvelez le certificat (ou vérifiez le renouvellement automatique).",
                pid,
                dedupe_key=f"ssl:{pid}",
                cooldown_hours=24,
            )
        # Un certificat qui change alors que l'ancien était valide longtemps = signal suspect.
        if (
            tls["fingerprint"]
            and project.cert_fingerprint
            and tls["fingerprint"] != project.cert_fingerprint
            and previous_days is not None
            and previous_days > 35
        ):
            create_alert(
                db,
                "attack",
                "warning",
                f"Certificat modifié de façon inattendue : {name}",
                "Le certificat a changé alors que l'ancien n'arrivait pas à expiration. "
                "Si ce n'est pas vous, possible interception ou compromission.",
                pid,
                dedupe_key=f"certchg:{pid}",
                cooldown_hours=24,
            )


def _latency_spike(db: Session, project: Project, latency: int | None) -> None:
    if latency is None:
        return
    rows = db.scalars(
        select(CheckResult.latency_ms)
        .where(
            CheckResult.project_id == project.id,
            CheckResult.ok.is_(True),
            CheckResult.latency_ms.is_not(None),
        )
        .order_by(CheckResult.ts.desc())
        .limit(21)
        .offset(1)
    ).all()
    if len(rows) >= 10:
        avg = sum(rows) / len(rows)
        if latency > max(3000, 5 * avg):
            create_alert(
                db,
                "attack",
                "warning",
                f"Ralentissement anormal : {project.name}",
                f"{latency} ms contre ~{int(avg)} ms d'habitude. Peut indiquer une attaque (DDoS, bots) "
                "ou une surcharge.",
                project.id,
                dedupe_key=f"slow:{project.id}",
                cooldown_hours=2,
            )


def _prune(db: Session, project_id: int, keep_days: int = 30) -> None:
    cutoff = utcnow() - timedelta(days=keep_days)
    db.query(CheckResult).filter(CheckResult.project_id == project_id, CheckResult.ts < cutoff).delete()
    db.commit()


def run_due_checks(db: Session) -> int:
    now = utcnow()
    count = 0
    for project in db.scalars(select(Project).where(Project.monitoring_enabled.is_(True))):
        due = project.last_checked_at is None or now - project.last_checked_at >= timedelta(
            minutes=project.check_interval_min
        ) - timedelta(seconds=20)
        if due:
            run_check(db, project)
            count += 1
    return count
