"""Page de statut publique : sans authentification, n'expose que le nom et l'état des projets cochés « public »."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Project

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/status")
def public_status(db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).where(Project.public_status.is_(True)).order_by(Project.name)).all()
    states = [p.status for p in projects]
    overall = "down" if "down" in states else "up" if states and all(s == "up" for s in states) else "unknown"
    return {"overall": overall, "services": [{"name": p.name, "status": p.status} for p in projects]}
