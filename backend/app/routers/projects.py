from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user
from app.models import CheckResult, Project, Server, Technology, User, Vulnerability
from app.routers.auth import audit
from app.schemas import CheckOut, ProjectIn, ProjectOut, ServerIn, ServerOut, TechIn, TechOut
from app.services import monitoring

router = APIRouter(tags=["projets"], dependencies=[Depends(current_user)])


def _out(db: Session, p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.open_vulnerabilities = (
        db.scalar(
            select(func.count())
            .select_from(Vulnerability)
            .where(Vulnerability.project_id == p.id, Vulnerability.dismissed.is_(False))
        )
        or 0
    )
    return out


def _get(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    return p


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return [_out(db, p) for p in db.scalars(select(Project).order_by(Project.name))]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    audit(db, user.email, "project_created", p.name)
    return _out(db, p)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _out(db, _get(db, project_id))


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int, body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    p = _get(db, project_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    audit(db, user.email, "project_updated", p.name)
    return _out(db, p)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _get(db, project_id)
    db.delete(p)
    db.commit()
    audit(db, user.email, "project_deleted", p.name)


@router.post("/projects/{project_id}/check", response_model=CheckOut)
def check_now(project_id: int, db: Session = Depends(get_db)):
    return monitoring.run_check(db, _get(db, project_id))


@router.get("/projects/{project_id}/checks", response_model=list[CheckOut])
def history(project_id: int, limit: int = 100, db: Session = Depends(get_db)):
    q = (
        select(CheckResult)
        .where(CheckResult.project_id == project_id)
        .order_by(CheckResult.ts.desc())
        .limit(min(limit, 1000))
    )
    return list(reversed(db.scalars(q).all()))


# ----- serveurs -----
@router.post("/projects/{project_id}/servers", response_model=ServerOut, status_code=201)
def add_server(project_id: int, body: ServerIn, db: Session = Depends(get_db)):
    _get(db, project_id)
    s = Server(project_id=project_id, **body.model_dump())
    db.add(s)
    db.commit()
    return s


@router.put("/servers/{server_id}", response_model=ServerOut)
def update_server(server_id: int, body: ServerIn, db: Session = Depends(get_db)):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return s


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: int, db: Session = Depends(get_db)):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404)
    db.delete(s)
    db.commit()


# ----- technologies -----
@router.post("/projects/{project_id}/technologies", response_model=TechOut, status_code=201)
def add_tech(project_id: int, body: TechIn, db: Session = Depends(get_db)):
    _get(db, project_id)
    t = Technology(project_id=project_id, **body.model_dump())
    db.add(t)
    db.commit()
    return t


@router.put("/technologies/{tech_id}", response_model=TechOut)
def update_tech(tech_id: int, body: TechIn, db: Session = Depends(get_db)):
    t = db.get(Technology, tech_id)
    if not t:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return t


@router.delete("/technologies/{tech_id}", status_code=204)
def delete_tech(tech_id: int, db: Session = Depends(get_db)):
    t = db.get(Technology, tech_id)
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
