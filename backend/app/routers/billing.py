from datetime import date
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.core.config import get_settings, public_base_url
from app.core.db import get_db, utcnow
from app.core.security import admin_user, manager_user
from app.models import BillingDoc, Company, Payment, User
from app.routers._common import csv_response
from app.routers.auth import audit
from app.schemas_billing import DocIn, DocOut
from app.services import billing, billing_pdf, integrations, qonto, qonto_billing, qonto_oauth

router = APIRouter(prefix="/billing", tags=["devis & factures"], dependencies=[Depends(manager_user)])


def _out(db: Session, d: BillingDoc) -> DocOut:
    out = DocOut.model_validate(d)
    out.company_name = db.get(Company, d.company_id).name if d.company_id else ""
    out.remaining = billing.remaining(d)
    out.is_overdue = billing.overdue(d)
    out.qonto_editable = bool(qonto_billing.qonto_quote_id(d))
    out.deletable = qonto_billing.hub_deletable(d)
    return out


def _get(db: Session, doc_id: int) -> BillingDoc:
    d = db.get(BillingDoc, doc_id)
    if not d:
        raise HTTPException(404, "Document introuvable")
    return d


def _editable(d: BillingDoc) -> BillingDoc:
    """Contenu modifiable : documents du Hub, et devis Qonto encore en attente (reportés dans Qonto)."""
    if d.provider == "qonto" and not qonto_billing.qonto_quote_id(d):
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
def qonto_status(request: Request, db: Session = Depends(get_db)):
    return {
        "configured": qonto.is_configured(db),
        "last_synced_at": integrations.get(db, "qonto_billing_synced_at") or None,
        # Connexion OAuth (devis)
        "oauth_configured": qonto_oauth.is_configured(db),
        "oauth_connected": qonto_oauth.is_connected(db),
        "redirect_uri": qonto_oauth.redirect_uri(request),
    }


@router.get("/qonto/connect")
def qonto_connect(request: Request, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    state = jwt.encode(
        {"uid": admin.id, "exp": utcnow().timestamp() + 600}, get_settings().secret_key, algorithm="HS256"
    )
    try:
        return {"url": qonto_oauth.authorize_url(db, state, request)}
    except qonto_oauth.QontoOAuthError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/qonto/oauth/callback")
def qonto_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    base = public_base_url(request)
    try:
        data = jwt.decode(state, get_settings().secret_key, algorithms=["HS256"])
        if data["uid"] != user.id:
            raise ValueError("utilisateur différent")
        if error or not code:
            raise ValueError(error or "code manquant")
        qonto_oauth.exchange_code(db, code, request)
    except Exception as exc:
        return RedirectResponse(f"{base}/parametres?qonto_error={quote(str(exc)[:150])}")
    audit(db, user.email, "qonto_oauth_connected", "")
    return RedirectResponse(f"{base}/parametres?qonto=connected")


@router.post("/qonto/disconnect")
def qonto_disconnect(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    qonto_oauth.disconnect(db)
    audit(db, admin.email, "qonto_oauth_disconnected", "")
    return {"ok": True}


@router.post("/{doc_id}/push-qonto", response_model=DocOut)
def push_qonto(doc_id: int, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    """Crée le devis dans Qonto (en attente de validation, non envoyé au client)."""
    d = _get(db, doc_id)
    try:
        qonto_billing.push_quote(db, d)
    except qonto.QontoError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, user.email, "quote_pushed_to_qonto", d.number or str(doc_id))
    return _out(db, d)


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
def update(doc_id: int, body: DocIn, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    d = _editable(_get(db, doc_id))
    if d.provider != "qonto":
        return _out(db, _guard(billing.update_doc, db, d, body))
    # Devis lié à Qonto (en attente de validation) : la modification est reportée dans Qonto.
    if body.kind != "quote":
        raise HTTPException(400, "Le type de document ne peut pas être changé.")
    with db.no_autoflush:
        for k, v in body.model_dump(exclude={"lines", "kind"}).items():
            setattr(d, k, v)
        billing.set_lines(d, body.lines)
        try:
            qonto_billing.update_quote(db, d)
        except qonto.QontoError as exc:
            db.rollback()
            raise HTTPException(400, str(exc)) from exc
    audit(db, user.email, "quote_updated_in_qonto", d.number or str(doc_id))
    return _out(db, d)


@router.delete("/{doc_id}", status_code=204)
def delete(doc_id: int, db: Session = Depends(get_db), user: User = Depends(manager_user)):
    d = _get(db, doc_id)
    if not qonto_billing.hub_deletable(d):
        if d.provider == "qonto":
            msg = (
                "Devis validé ou importé de Qonto : il se supprime dans Qonto."
                if d.kind == "quote"
                else "Facture de Qonto : elle se gère dans Qonto."
            )
        elif d.kind == "quote":
            msg = "Devis accepté : il ne peut plus être supprimé."
        else:
            msg = "Seuls les brouillons peuvent être supprimés (une facture émise garde son numéro)."
        raise HTTPException(400, msg)
    if d.provider == "qonto":  # devis envoyé depuis le Hub : supprimé aussi dans Qonto
        try:
            qonto_billing.delete_quote(db, d)
        except qonto.QontoError as exc:
            raise HTTPException(400, str(exc)) from exc
    db.delete(d)
    db.commit()
    audit(db, user.email, f"{d.kind}_deleted", str(doc_id))


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
