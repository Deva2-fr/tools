from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import manager_user
from app.models import BillingDoc, Company, Payment, User
from app.routers._common import csv_response
from app.routers.auth import audit
from app.schemas_billing import DocIn, DocOut, PaymentIn, StatusIn
from app.services import billing, billing_pdf, integrations, qonto, qonto_billing

router = APIRouter(prefix="/billing", tags=["devis & factures"], dependencies=[Depends(manager_user)])


def _out(db: Session, d: BillingDoc) -> DocOut:
    out = DocOut.model_validate(d)
    out.company_name = db.get(Company, d.company_id).name if d.company_id else ""
    out.remaining = billing.remaining(d)
    out.is_overdue = billing.overdue(d)
    return out


def _get(db: Session, doc_id: int) -> BillingDoc:
    d = db.get(BillingDoc, doc_id)
    if not d:
        raise HTTPException(404, "Document introuvable")
    return d


def _editable(d: BillingDoc) -> BillingDoc:
    if d.provider == "qonto":
        raise HTTPException(
            400, "Document importé de Qonto : modifiez-le dans Qonto, il sera mis à jour ici."
        )
    return d


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except billing.BillingError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("", response_model=list[DocOut])
def list_docs(
    kind: str = "",
    status: str = "",
    company_id: int | None = None,
    q: str = "",
    db: Session = Depends(get_db),
):
    stmt = select(BillingDoc).order_by(BillingDoc.issue_date.desc(), BillingDoc.id.desc())
    if kind:
        stmt = stmt.where(BillingDoc.kind == kind)
    if company_id:
        stmt = stmt.where(BillingDoc.company_id == company_id)
    if q:
        stmt = stmt.where(BillingDoc.number.ilike(f"%{q}%") | BillingDoc.title.ilike(f"%{q}%"))
    out = [_out(db, d) for d in db.scalars(stmt.limit(500))]
    if status == "overdue":
        return [d for d in out if d.is_overdue]
    return [d for d in out if d.status == status] if status else out


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    today = date.today()
    invoices = db.scalars(
        select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status.in_(("sent", "paid")))
    ).all()
    year = [d for d in invoices if d.issue_date.year == today.year]
    open_quotes = db.scalars(
        select(BillingDoc).where(BillingDoc.kind == "quote", BillingDoc.status == "sent")
    ).all()
    months = [0.0] * 12
    for d in year:
        months[d.issue_date.month - 1] += d.total_ht
    return {
        "year": today.year,
        "invoiced_ht": round(sum(d.total_ht for d in year), 2),
        "collected": round(
            sum(
                p.amount
                for p in db.scalars(select(Payment).where(extract("year", Payment.paid_on) == today.year))
            ),
            2,
        ),
        "outstanding": round(sum(billing.remaining(d) for d in invoices), 2),
        "overdue": round(sum(billing.remaining(d) for d in invoices if billing.overdue(d)), 2),
        "overdue_count": sum(billing.overdue(d) for d in invoices),
        "open_quotes_amount": round(sum(d.total_ht for d in open_quotes), 2),
        "open_quotes_count": len(open_quotes),
        "monthly_ht": [round(m, 2) for m in months],
    }


@router.get("/qonto")
def qonto_status(db: Session = Depends(get_db)):
    return {
        "configured": qonto.is_configured(db),
        "last_synced_at": integrations.get(db, "qonto_billing_synced_at") or None,
    }


@router.post("/qonto/sync")
def qonto_sync(db: Session = Depends(get_db), user: User = Depends(manager_user)):
    try:
        res = qonto_billing.sync(db)
    except qonto.QontoError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, user.email, "qonto_billing_synced", f"{res['invoices']} factures, {res['quotes']} devis")
    return res


@router.post("", response_model=DocOut, status_code=201)
def create(body: DocIn, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    d = billing.create_doc(db, body, user.email)
    audit(db, user.email, f"{d.kind}_created", str(d.id))
    return _out(db, d)


@router.get("/{doc_id}", response_model=DocOut)
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    return _out(db, _get(db, doc_id))


@router.put("/{doc_id}", response_model=DocOut)
def update(doc_id: int, body: DocIn, db: Session = Depends(get_db)):
    return _out(db, _guard(billing.update_doc, db, _editable(_get(db, doc_id)), body))


@router.delete("/{doc_id}", status_code=204)
def delete(doc_id: int, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    d = _editable(_get(db, doc_id))
    if d.status != "draft":
        raise HTTPException(
            400, "Seuls les brouillons peuvent être supprimés (un document émis garde son numéro)."
        )
    db.delete(d)
    db.commit()
    audit(db, user.email, f"{d.kind}_deleted", str(doc_id))


@router.post("/{doc_id}/issue", response_model=DocOut)
def issue(doc_id: int, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    d = _guard(billing.issue, db, _editable(_get(db, doc_id)))
    audit(db, user.email, f"{d.kind}_issued", d.number or "")
    return _out(db, d)


@router.post("/{doc_id}/status", response_model=DocOut)
def status(doc_id: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    d = _guard(billing.set_status, db, _editable(_get(db, doc_id)), body.status)
    audit(db, user.email, f"{d.kind}_{body.status}", d.number or "")
    return _out(db, d)


@router.post("/{doc_id}/convert", response_model=DocOut, status_code=201)
def convert(doc_id: int, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    inv = _guard(billing.convert_to_invoice, db, _editable(_get(db, doc_id)), user.email)
    audit(db, user.email, "quote_converted", str(doc_id))
    return _out(db, inv)


@router.post("/{doc_id}/payments", response_model=DocOut, status_code=201)
def add_payment(
    doc_id: int, body: PaymentIn, db: Session = Depends(get_db), user: User = Depends(manager_user)
):
    d = _editable(_get(db, doc_id))
    _guard(billing.add_payment, db, d, body.paid_on, body.amount, body.method, body.note)
    audit(db, user.email, "payment_added", f"{d.number}: {body.amount}")
    return _out(db, d)


@router.delete("/{doc_id}/payments/{payment_id}", response_model=DocOut)
def delete_payment(
    doc_id: int, payment_id: int, db: Session = Depends(get_db), user: User = Depends(manager_user)
):
    d = _editable(_get(db, doc_id))
    p = next((x for x in d.payments if x.id == payment_id), None)
    if not p:
        raise HTTPException(404)
    d.payments.remove(p)
    db.flush()
    billing.refresh_payment_status(d)
    db.commit()
    audit(db, user.email, "payment_deleted", d.number or "")
    return _out(db, d)


@router.get("/{doc_id}/pdf")
def pdf(doc_id: int, db: Session = Depends(get_db)):
    d = _get(db, doc_id)
    company = db.get(Company, d.company_id) if d.company_id else None
    data = billing_pdf.render_pdf(d, company, integrations.company_info(db))
    name = d.number or f"brouillon-{d.id}"
    return Response(
        data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'}
    )


@router.get("/export/csv")
def export(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(BillingDoc).where(BillingDoc.status != "draft").order_by(BillingDoc.issue_date)
    ).all()
    names = {c.id: c.name for c in db.scalars(select(Company))}
    return csv_response(
        "devis-factures.csv",
        ["numero", "type", "statut", "date", "echeance", "client", "total_ht", "tva", "total_ttc", "regle"],
        [
            [
                d.number,
                d.kind,
                d.status,
                d.issue_date,
                d.due_date,
                names.get(d.company_id, ""),
                d.total_ht,
                d.total_vat,
                d.total_ttc,
                d.amount_paid,
            ]
            for d in rows
        ],
    )
