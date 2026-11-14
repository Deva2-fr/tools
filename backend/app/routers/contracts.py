from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import manager_user
from app.models import ClientContract, Company, Project, User
from app.routers.auth import audit
from app.services import client_renewals

router = APIRouter(
    prefix="/client-contracts", tags=["contrats clients"], dependencies=[Depends(manager_user)]
)


class ContractIn(BaseModel):
    company_id: int
    project_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["hosting", "domain", "maintenance", "license", "other"] = "hosting"
    unit_price: float = Field(ge=0, lt=10_000_000)
    quantity: float = Field(1, gt=0, lt=100_000)
    vat_rate: float = Field(20, ge=0, le=100)
    period: Literal["monthly", "quarterly", "yearly"] = "yearly"
    renewal_date: date
    notice_days: int = Field(30, ge=0, le=365)
    active: bool = True
    notes: str = ""


def _out(db: Session, c: ClientContract, names: dict[int, str] | None = None) -> dict:
    company = (
        names.get(c.company_id) if names is not None else getattr(db.get(Company, c.company_id), "name", "")
    )
    project = db.get(Project, c.project_id) if c.project_id else None
    return {
        "id": c.id,
        "company_id": c.company_id,
        "company": company or "",
        "project_id": c.project_id,
        "project": project.name if project else "",
        "name": c.name,
        "kind": c.kind,
        "kind_label": client_renewals.KINDS.get(c.kind, c.kind),
        "unit_price": c.unit_price,
        "quantity": c.quantity,
        "vat_rate": c.vat_rate,
        "period": c.period,
        "renewal_date": c.renewal_date,
        "notice_days": c.notice_days,
        "active": c.active,
        "notes": c.notes,
        "renewal": client_renewals.status(db, c),
    }


def _get(db: Session, contract_id: int) -> ClientContract:
    c = db.get(ClientContract, contract_id)
    if not c:
        raise HTTPException(404)
    return c


def _check(db: Session, body: ContractIn) -> None:
    if not db.get(Company, body.company_id):
        raise HTTPException(400, "Client introuvable.")
    if body.project_id and not db.get(Project, body.project_id):
        raise HTTPException(400, "Projet introuvable.")


@router.get("")
def list_contracts(
    company_id: int | None = None, kind: str = "", active: bool | None = None, db: Session = Depends(get_db)
):
    stmt = select(ClientContract).order_by(ClientContract.renewal_date, ClientContract.id)
    if company_id:
        stmt = stmt.where(ClientContract.company_id == company_id)
    if kind:
        stmt = stmt.where(ClientContract.kind == kind)
    if active is not None:
        stmt = stmt.where(ClientContract.active.is_(active))
    names = {c.id: c.name for c in db.scalars(select(Company))}
    return [_out(db, c, names) for c in db.scalars(stmt)]


@router.get("/upcoming")
def upcoming(days: int = 30, db: Session = Depends(get_db)):
    return client_renewals.upcoming(db, max(1, min(days, 365)))


@router.post("", status_code=201)
def create(body: ContractIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    _check(db, body)
    c = ClientContract(**body.model_dump())
    db.add(c)
    db.commit()
    audit(db, user.email, "client_contract_created", c.name)
    return _out(db, c)


@router.put("/{contract_id}")
def update(
    contract_id: int, body: ContractIn, user: User = Depends(manager_user), db: Session = Depends(get_db)
):
    c = _get(db, contract_id)
    _check(db, body)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    audit(db, user.email, "client_contract_updated", c.name)
    return _out(db, c)


@router.delete("/{contract_id}", status_code=204)
def delete(contract_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    c = _get(db, contract_id)
    db.delete(c)
    db.commit()
    audit(db, user.email, "client_contract_deleted", c.name)


@router.post("/prepare")
def prepare_now(
    company_id: int | None = None, user: User = Depends(manager_user), db: Session = Depends(get_db)
):
    """« Préparer le devis maintenant » : sans attendre le délai, pour un client (ou tous)."""
    docs = client_renewals.prepare(db, company_id=company_id, force=True, by=user.email)
    audit(db, user.email, "client_renewal_quotes", f"{len(docs)} devis préparé(s)")
    return {"created": [{"id": d.id, "title": d.title, "total_ht": d.total_ht} for d in docs]}
