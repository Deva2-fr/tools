"""Veille des failles : interroge NVD (CVE) et le catalogue CISA KEV (failles activement exploitées)."""

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import Technology, Vulnerability
from app.services import integrations
from app.services.alerts import create_alert

log = logging.getLogger(__name__)
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
RECENT_DAYS = 120  # on n'alerte que sur les CVE publiées récemment (ou exploitées activement)


def fetch_kev() -> set[str]:
    try:
        r = httpx.get(KEV_URL, timeout=30)
        r.raise_for_status()
        return {v["cveID"] for v in r.json().get("vulnerabilities", [])}
    except Exception as exc:
        log.warning("KEV indisponible : %s", exc)
        return set()


def _cvss(metrics: dict) -> float | None:
    for key in ("cvssMetricV31", "cvssMetricV40", "cvssMetricV30", "cvssMetricV2"):
        if metrics.get(key):
            return float(metrics[key][0]["cvssData"]["baseScore"])
    return None


def parse_nvd(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("vulnerabilities", []):
        cve = item["cve"]
        desc = next((d["value"] for d in cve.get("descriptions", []) if d["lang"] == "en"), "")
        out.append(
            {
                "cve_id": cve["id"],
                "cvss": _cvss(cve.get("metrics", {})),
                "summary": desc[:1000],
                "published": datetime.fromisoformat(cve["published"]).replace(tzinfo=UTC),
            }
        )
    return out


def query_nvd(db: Session, tech: Technology) -> list[dict]:
    headers = {}
    if key := integrations.get(db, "nvd_api_key"):
        headers["apiKey"] = key
    keyword = f"{tech.name} {tech.version}".strip()
    r = httpx.get(
        NVD_URL, params={"keywordSearch": keyword, "resultsPerPage": 40}, headers=headers, timeout=45
    )
    r.raise_for_status()
    return parse_nvd(r.json())


def scan_technology(db: Session, tech: Technology, kev: set[str], nvd=query_nvd) -> int:
    threshold = integrations.cvss_threshold(db)
    new_alerts = 0
    for cve in nvd(db, tech):
        exists = db.scalar(
            select(Vulnerability.id).where(
                Vulnerability.technology_id == tech.id, Vulnerability.cve_id == cve["cve_id"]
            )
        )
        if exists:
            continue
        exploited = cve["cve_id"] in kev
        vuln = Vulnerability(
            project_id=tech.project_id,
            technology_id=tech.id,
            cve_id=cve["cve_id"],
            cvss=cve["cvss"],
            summary=cve["summary"],
            exploited=exploited,
            published_at=cve["published"],
        )
        db.add(vuln)
        recent = cve["published"] >= utcnow() - timedelta(days=RECENT_DAYS)
        serious = exploited or (cve["cvss"] or 0) >= threshold
        if serious and (recent or exploited):
            create_alert(
                db,
                "vuln",
                "critical",
                f"Faille {cve['cve_id']} ({tech.name} {tech.version}) – CVSS {cve['cvss'] or '?'}"
                + (" – DÉJÀ EXPLOITÉE" if exploited else ""),
                f"{tech.project.name} : {cve['summary'][:400]}\nhttps://nvd.nist.gov/vuln/detail/{cve['cve_id']}\n"
                "Résultat de recherche par mot-clé : vérifiez que votre version est bien concernée.",
                tech.project_id,
                dedupe_key=f"vuln:{tech.id}:{cve['cve_id']}",
                cooldown_hours=24 * 365,
            )
            new_alerts += 1
    tech.last_scanned_at = utcnow()
    db.commit()
    return new_alerts


def scan_all(db: Session, project_id: int | None = None, nvd=query_nvd) -> int:
    q = select(Technology).where(Technology.watch_cve.is_(True))
    if project_id:
        q = q.where(Technology.project_id == project_id)
    kev = fetch_kev()
    total = 0
    delay = 0.7 if integrations.get(db, "nvd_api_key") else 6.5  # quotas NVD
    for tech in db.scalars(q).all():
        try:
            total += scan_technology(db, tech, kev, nvd)
        except Exception as exc:
            log.warning("Scan %s %s échoué : %s", tech.name, tech.version, exc)
        if nvd is query_nvd:
            time.sleep(delay)
    return total
