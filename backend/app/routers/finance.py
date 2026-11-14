from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import manager_user
from app.models import BillingDoc, Budget, CategoryRule, Company, Transaction, User
from app.routers.auth import audit
from app.services import finance

router = APIRouter(prefix="/finance", tags=["finances"], dependencies=[Depends(manager_user)])


class CategoryIn(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    # Facultatif : mot du libellé à retenir pour classer automatiquement les mouvements semblables.
    pattern: str = Field("", max_length=120)


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=1, max_length=80)


class BudgetIn(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    monthly_amount: float | None = Field(None, ge=0, lt=10_000_000)  # vide = pas de budget


class MatchIn(BaseModel):
    billing_doc_id: int | None = None


def _check_category(cat: str) -> str:
    if cat not in finance.CATEGORIES:
        raise HTTPException(400, "Catégorie inconnue.")
    return cat


def _tx_out(tx: Transaction, doc: BillingDoc | None = None) -> dict:
    return {
        "id": tx.id,
        "date": tx.tx_date,
        "label": tx.label,
        "amount": tx.amount,
        "category": tx.hub_category or "",
        "locked": tx.category_locked,
        "vat_amount": tx.vat_amount,
        "attachments": tx.attachment_count,
        "operation_type": tx.operation_type,
        "billing_doc_id": tx.billing_doc_id,
        "invoice": _doc_out(doc) if doc else None,
    }


def _doc_out(d: BillingDoc) -> dict:
    return {
        "id": d.id,
        "number": d.number,
        "title": d.title,
        "total_ttc": d.total_ttc,
        "issue_date": d.issue_date,
    }


@router.get("/overview")
def overview(months: int = 12, db: Session = Depends(get_db)):
    return finance.overview(db, max(3, min(months, 24)))


@router.get("/categories")
def categories(months: int = 6, db: Session = Depends(get_db)):
    return {"categories": finance.CATEGORIES, **finance.by_category(db, max(1, min(months, 12)))}


@router.get("/transactions")
def transactions(
    category: str = "",
    uncategorized: bool = False,
    q: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
):
    stmt = select(Transaction).order_by(Transaction.tx_date.desc(), Transaction.id.desc())
    if uncategorized:
        stmt = stmt.where(Transaction.hub_category == "")
    elif category:
        stmt = stmt.where(Transaction.hub_category == category)
    if q:
        stmt = stmt.where(Transaction.label.ilike(f"%{q}%"))
    return [_tx_out(t) for t in db.scalars(stmt.limit(max(1, min(limit, 1000))))]


@router.put("/transactions/{tx_id}/category")
def set_category(
    tx_id: int, body: CategoryIn, user: User = Depends(manager_user), db: Session = Depends(get_db)
):
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404)
    tx.hub_category, tx.category_locked = _check_category(body.category), True
    applied = 0
    if pattern := body.pattern.strip():
        db.add(CategoryRule(pattern=pattern, category=body.category, created_by=user.email))
        db.flush()
        applied = finance.categorize(db, force=True)
    db.commit()
    return {**_tx_out(tx), "applied": applied}


@router.post("/recategorize")
def recategorize(db: Session = Depends(get_db)):
    """Re-classe tous les mouvements avec les règles actuelles (les choix manuels sont gardés)."""
    return {"changed": finance.categorize(db, force=True)}


@router.get("/rules")
def rules(db: Session = Depends(get_db)):
    return [
        {"id": r.id, "pattern": r.pattern, "category": r.category}
        for r in db.scalars(select(CategoryRule).order_by(CategoryRule.pattern))
    ]


@router.post("/rules", status_code=201)
def add_rule(body: RuleIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    r = CategoryRule(
        pattern=body.pattern.strip(), category=_check_category(body.category), created_by=user.email
    )
    db.add(r)
    db.commit()
    changed = finance.categorize(db, force=True)
    audit(db, user.email, "finance_rule_added", f"{r.pattern} → {r.category}")
    return {"id": r.id, "pattern": r.pattern, "category": r.category, "changed": changed}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(CategoryRule, rule_id)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    finance.categorize(db, force=True)


@router.get("/budgets")
def budgets(db: Session = Depends(get_db)):
    return {b.category: b.monthly_amount for b in db.scalars(select(Budget))}


@router.put("/budgets")
def set_budget(body: BudgetIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    cat = _check_category(body.category)
    b = db.get(Budget, cat)
    if body.monthly_amount is None or body.monthly_amount == 0:
        if b:
            db.delete(b)
    elif b:
        b.monthly_amount = body.monthly_amount
    else:
        db.add(Budget(category=cat, monthly_amount=body.monthly_amount))
    db.commit()
    audit(db, user.email, "finance_budget_set", f"{cat} : {body.monthly_amount or 0}")
    return budgets(db)


@router.get("/clients")
def clients(months: int = 12, db: Session = Depends(get_db)):
    return finance.clients(db, max(1, min(months, 36)))


@router.get("/receipts")
def receipts(days: int = 90, db: Session = Depends(get_db)):
    return [_tx_out(t) for t in finance.missing_receipts(db, max(7, min(days, 366)))]


@router.get("/reconciliation")
def reconciliation(db: Session = Depends(get_db)):
    data = finance.reconciliation(db)
    names = {c.id: c.name for c in db.scalars(select(Company))}

    def with_client(d: dict | None, doc: BillingDoc | None) -> dict | None:
        return {**d, "company": names.get(doc.company_id, "")} if d and doc else None

    return {
        "unmatched": [
            {**_tx_out(tx), "suggestion": with_client(_doc_out(s) if s else None, s)}
            for tx, s in data["unmatched"]
        ],
        "matched": [
            _tx_out(tx, doc) for tx in data["matched"] if (doc := db.get(BillingDoc, tx.billing_doc_id))
        ],
    }


@router.put("/transactions/{tx_id}/match")
def match(tx_id: int, body: MatchIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404)
    doc = None
    if body.billing_doc_id is not None:
        doc = db.get(BillingDoc, body.billing_doc_id)
        if not doc or doc.kind != "invoice":
            raise HTTPException(400, "Facture introuvable.")
        if tx.amount <= 0:
            raise HTTPException(400, "Seul un encaissement se rapproche d'une facture.")
    tx.billing_doc_id = doc.id if doc else None
    db.commit()
    audit(db, user.email, "finance_matched", f"{tx.label} → {doc.number if doc else 'aucune'}")
    return _tx_out(tx, doc)


@router.get("/export.csv")
def export(start: date, end: date, db: Session = Depends(get_db)):
    if end < start:
        raise HTTPException(400, "La fin de période précède le début.")
    return Response(
        finance.export_csv(db, start, end),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="mouvements-{start}-{end}.csv"'},
    )
