from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user
from app.models import TaxDeadline
from app.schemas import TaxIn, TaxOut
from app.services import taxes

router = APIRouter(prefix="/taxes", tags=["impôts"], dependencies=[Depends(current_user)])


def _out(t: TaxDeadline) -> TaxOut:
    out = TaxOut.model_validate(t)
    out.days_left = (t.due_date - date.today()).days
    return out


@router.get("", response_model=list[TaxOut])
def list_taxes(include_paid: bool = True, db: Session = Depends(get_db)):
    q = select(TaxDeadline).order_by(TaxDeadline.due_date)
    if not include_paid:
        q = q.where(TaxDeadline.status == "todo")
    return [_out(t) for t in db.scalars(q)]


@router.post("", response_model=TaxOut, status_code=201)
def create(body: TaxIn, db: Session = Depends(get_db)):
    t = TaxDeadline(**body.model_dump())
    db.add(t)
    db.commit()
    return _out(t)


@router.put("/{tax_id}", response_model=TaxOut)
def update(tax_id: int, body: TaxIn, db: Session = Depends(get_db)):
    t = db.get(TaxDeadline, tax_id)
    if not t:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return _out(t)


@router.delete("/{tax_id}", status_code=204)
def delete(tax_id: int, db: Session = Depends(get_db)):
    t = db.get(TaxDeadline, tax_id)
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()


@router.post("/{tax_id}/paid", response_model=TaxOut)
def paid(tax_id: int, db: Session = Depends(get_db)):
    """Marque comme payée ; si l'échéance est récurrente, la suivante est créée automatiquement."""
    t = db.get(TaxDeadline, tax_id)
    if not t:
        raise HTTPException(404)
    taxes.mark_paid(db, t)
    return _out(t)


@router.post("/generate")
def generate(year: int | None = None, db: Session = Depends(get_db)):
    """Crée les échéances types de l'année (TVA, IS, CFE…) — à vérifier avec votre comptable."""
    return {"created": taxes.generate_year(db, year or date.today().year)}


@router.get("/calendar.ics")
def ics(db: Session = Depends(get_db)):
    rows = db.scalars(select(TaxDeadline).order_by(TaxDeadline.due_date)).all()
    return Response(
        taxes.to_ics(list(rows)),
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="echeances-deva2.ics"'},
    )
