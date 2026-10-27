from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user
from app.models import Project, Vulnerability
from app.schemas import VulnOut
from app.services import security_watch

router = APIRouter(prefix="/security", tags=["sécurité"], dependencies=[Depends(current_user)])


def _out(v: Vulnerability) -> VulnOut:
    out = VulnOut.model_validate(v)
    out.tech_name, out.tech_version = v.technology.name, v.technology.version
    out.project_name = v.technology.project.name
    return out


@router.get("/vulnerabilities", response_model=list[VulnOut])
def list_vulns(include_dismissed: bool = False, project_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Vulnerability).order_by(Vulnerability.exploited.desc(), Vulnerability.cvss.desc().nulls_last())
    if not include_dismissed:
        q = q.where(Vulnerability.dismissed.is_(False))
    if project_id:
        q = q.where(Vulnerability.project_id == project_id)
    return [_out(v) for v in db.scalars(q.limit(300))]


@router.post("/vulnerabilities/{vuln_id}/dismiss", response_model=VulnOut)
def dismiss(vuln_id: int, restore: bool = False, db: Session = Depends(get_db)):
    v = db.get(Vulnerability, vuln_id)
    if not v:
        raise HTTPException(404)
    v.dismissed = not restore
    db.commit()
    return _out(v)


@router.post("/scan")
def scan(project_id: int | None = None, db: Session = Depends(get_db)):
    if project_id and not db.get(Project, project_id):
        raise HTTPException(404)
    return {"new_alerts": security_watch.scan_all(db, project_id)}
