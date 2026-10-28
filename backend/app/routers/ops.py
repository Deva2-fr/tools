"""Abonnements, trésorerie, temps, équipe, registre d'accès, documents."""

import mimetypes
import secrets
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import current_user, manager_user
from app.models import (
    AccessEntry,
    BankAccount,
    BillingDoc,
    ChecklistItem,
    Company,
    Employee,
    FileRecord,
    Subscription,
    TimeEntry,
    Transaction,
    User,
)
from app.routers._common import crud_router
from app.routers.auth import audit
from app.schemas_crm import CsvImport  # noqa: F401
from app.schemas_ops import (
    AccessIn,
    BankAccountIn,
    ChecklistIn,
    EmployeeIn,
    SubscriptionIn,
    TimeEntryIn,
    TransactionImport,
    TransactionIn,
)
from app.services import qonto, renewals, treasury

router = APIRouter(dependencies=[Depends(current_user)])

# ---------- CRUD simples (manager et +) ----------
subs, _ = crud_router(
    "/subscriptions",
    Subscription,
    SubscriptionIn,
    tag="abonnements",
    read="manager",
    write="manager",
    search=("name", "vendor"),
    order_by=[Subscription.renewal_date.is_(None), Subscription.renewal_date],
    label=lambda o: o.name,
    extra_out={"invoice_count": (int, 0)},
)
accounts, _ = crud_router(
    "/accounts",
    BankAccount,
    BankAccountIn,
    tag="trésorerie",
    read="manager",
    write="manager",
    order_by=[BankAccount.name],
    label=lambda o: o.name,
    extra_out={"provider": (str, "manual"), "last_synced_at": (datetime | None, None)},
)
transactions, _ = crud_router(
    "/transactions",
    Transaction,
    TransactionIn,
    tag="trésorerie",
    read="manager",
    write="manager",
    search=("label", "category"),
    filters=("account_id",),
    order_by=[Transaction.tx_date.desc(), Transaction.id.desc()],
    label=lambda o: o.label,
)
employees, _ = crud_router(
    "/employees",
    Employee,
    EmployeeIn,
    tag="équipe",
    read="manager",
    write="manager",
    search=("name", "email", "job_title"),
    order_by=[Employee.name],
    label=lambda o: o.name,
)
checklist, _ = crud_router(
    "/checklist",
    ChecklistItem,
    ChecklistIn,
    tag="équipe",
    read="manager",
    write="manager",
    filters=("employee_id",),
    order_by=[ChecklistItem.id],
    label=lambda o: o.title,
)
access, _ = crud_router(
    "/access",
    AccessEntry,
    AccessIn,
    tag="accès",
    read="manager",
    write="manager",
    search=("system", "account", "holders"),
    order_by=[AccessEntry.system],
    label=lambda o: o.system,
)
for r in (subs, accounts, transactions, employees, checklist, access):
    router.include_router(r)


@router.get("/subscriptions-summary", dependencies=[Depends(manager_user)])
def subscriptions_summary(db: Session = Depends(get_db)):
    active = db.scalars(select(Subscription).where(Subscription.active.is_(True))).all()
    by_kind: dict[str, float] = {}
    for s in active:
        by_kind[s.kind] = round(by_kind.get(s.kind, 0) + renewals.annual_cost(s), 2)
    return {"annual_total": round(sum(by_kind.values()), 2), "by_kind": by_kind, "count": len(active)}


class InvoiceLinks(BaseModel):
    doc_ids: list[int] = Field(default_factory=list, max_length=500)


def _linked(s: Subscription) -> list[dict]:
    return [
        {
            "id": d.id,
            "kind": d.kind,
            "number": d.number,
            "status": d.status,
            "issue_date": d.issue_date,
            "total_ttc": d.total_ttc,
            "external_url": d.external_url,
        }
        for d in s.invoices
    ]


@router.get("/subscriptions/{sub_id}/invoices", dependencies=[Depends(manager_user)])
def subscription_invoices(sub_id: int, db: Session = Depends(get_db)):
    s = db.get(Subscription, sub_id)
    if not s:
        raise HTTPException(404)
    return _linked(s)


@router.put("/subscriptions/{sub_id}/invoices")
def link_subscription_invoices(
    sub_id: int, body: InvoiceLinks, db: Session = Depends(get_db), user: User = Depends(manager_user)
):
    s = db.get(Subscription, sub_id)
    if not s:
        raise HTTPException(404)
    ids = set(body.doc_ids)
    docs = db.scalars(select(BillingDoc).where(BillingDoc.id.in_(ids))).all() if ids else []
    if len(docs) != len(ids):
        raise HTTPException(400, "Facture introuvable")
    s.invoices = list(docs)
    db.commit()
    audit(db, user.email, "subscription_invoices_linked", f"{s.name}: {len(docs)}")
    return _linked(s)


# ---------- Trésorerie ----------
@router.post("/transactions/import", dependencies=[Depends(manager_user)])
def import_transactions(
    body: TransactionImport, db: Session = Depends(get_db), user: User = Depends(manager_user)
):
    if not db.get(BankAccount, body.account_id):
        raise HTTPException(404, "Compte introuvable")
    res = treasury.import_csv(db, body.account_id, body.csv)
    audit(db, user.email, "transactions_imported", str(res["created"]))
    return res


@router.get("/treasury/qonto", dependencies=[Depends(manager_user)])
def qonto_status(db: Session = Depends(get_db)):
    synced = db.scalars(select(BankAccount).where(BankAccount.provider == "qonto")).all()
    last = max((a.last_synced_at for a in synced if a.last_synced_at), default=None)
    return {"configured": qonto.is_configured(db), "accounts": len(synced), "last_synced_at": last}


@router.post("/treasury/qonto/sync")
def qonto_sync(db: Session = Depends(get_db), user: User = Depends(manager_user)):
    try:
        res = qonto.sync(db)
    except qonto.QontoError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, user.email, "qonto_synced", f"{res['created']} transaction(s)")
    return res


@router.get("/treasury/forecast", dependencies=[Depends(manager_user)])
def forecast(days: int = 90, db: Session = Depends(get_db)):
    return treasury.forecast(db, max(7, min(days, 365)))


# ---------- Suivi du temps ----------
def _time_out(t: TimeEntry) -> dict:
    return {
        c: getattr(t, c)
        for c in (
            "id",
            "user_email",
            "work_date",
            "hours",
            "company_id",
            "project_id",
            "description",
            "billable",
            "hourly_rate",
        )
    }


@router.get("/time")
def list_time(
    start: date | None = None,
    end: date | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = select(TimeEntry).order_by(TimeEntry.work_date.desc(), TimeEntry.id.desc()).limit(1000)
    if user.role == "member":
        q = q.where(TimeEntry.user_email == user.email)
    if start:
        q = q.where(TimeEntry.work_date >= start)
    if end:
        q = q.where(TimeEntry.work_date <= end)
    return [_time_out(t) for t in db.scalars(q)]


@router.post("/time", status_code=201)
def add_time(body: TimeEntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = TimeEntry(**body.model_dump(), user_email=user.email)
    db.add(t)
    db.commit()
    return _time_out(t)


def _own_entry(db: Session, user: User, entry_id: int) -> TimeEntry:
    t = db.get(TimeEntry, entry_id)
    if not t or (t.user_email != user.email and user.role == "member"):
        raise HTTPException(404)
    return t


@router.put("/time/{entry_id}")
def edit_time(
    entry_id: int, body: TimeEntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    t = _own_entry(db, user, entry_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return _time_out(t)


@router.delete("/time/{entry_id}", status_code=204)
def delete_time(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_entry(db, user, entry_id))
    db.commit()


@router.get("/time/report", dependencies=[Depends(manager_user)])
def time_report(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    """Rentabilité par client : facturé HT – coût du temps passé (coût journalier ÷ 7 h)."""
    end = end or date.today()
    start = start or end.replace(day=1)
    cost_h = {e.email.lower(): float(e.daily_cost) / 7 for e in db.scalars(select(Employee)) if e.email}
    rows: dict[int | None, dict] = {}
    for t in db.scalars(select(TimeEntry).where(TimeEntry.work_date >= start, TimeEntry.work_date <= end)):
        r = rows.setdefault(
            t.company_id, {"hours": 0.0, "billable_hours": 0.0, "sales_value": 0.0, "cost": 0.0}
        )
        r["hours"] += t.hours
        if t.billable:
            r["billable_hours"] += t.hours
            r["sales_value"] += t.hours * (t.hourly_rate or 0)
        r["cost"] += t.hours * cost_h.get(t.user_email.lower(), 0)
    invoiced: dict[int | None, float] = {}
    for d in db.scalars(
        select(BillingDoc).where(
            BillingDoc.kind == "invoice",
            BillingDoc.status.in_(("sent", "paid")),
            BillingDoc.issue_date >= start,
            BillingDoc.issue_date <= end,
        )
    ):
        invoiced[d.company_id] = invoiced.get(d.company_id, 0) + d.total_ht
    names = {c.id: c.name for c in db.scalars(select(Company))}
    out = []
    for cid in set(rows) | set(invoiced):
        r = rows.get(cid, {"hours": 0.0, "billable_hours": 0.0, "sales_value": 0.0, "cost": 0.0})
        inv = invoiced.get(cid, 0.0)
        out.append(
            {
                "company_id": cid,
                "company": names.get(cid, "Sans client"),
                **{k: round(v, 2) for k, v in r.items()},
                "invoiced_ht": round(inv, 2),
                "margin": round(inv - r["cost"], 2),
            }
        )
    out.sort(key=lambda x: -x["hours"])
    return {"start": start, "end": end, "rows": out, "total_hours": round(sum(r["hours"] for r in out), 2)}


# ---------- Documents (coffre de fichiers) ----------
MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".odt", ".ods", ".txt", ".csv", ".pptx"}
MAGIC = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".docx": b"PK",
    ".xlsx": b"PK",
    ".pptx": b"PK",
    ".odt": b"PK",
    ".ods": b"PK",
}


def _files_dir() -> Path:
    d = Path(get_settings().data_dir) / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_out(f: FileRecord) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "category": f.category,
        "original_name": f.original_name,
        "size": f.size,
        "company_id": f.company_id,
        "project_id": f.project_id,
        "expires_on": f.expires_on,
        "notes": f.notes,
        "uploaded_by": f.uploaded_by,
        "created_at": f.created_at,
    }


@router.get("/files", dependencies=[Depends(manager_user)])
def list_files(company_id: int | None = None, q: str = "", db: Session = Depends(get_db)):
    stmt = select(FileRecord).order_by(FileRecord.id.desc()).limit(500)
    if company_id:
        stmt = stmt.where(FileRecord.company_id == company_id)
    if q:
        stmt = stmt.where(FileRecord.name.ilike(f"%{q}%"))
    return [_file_out(f) for f in db.scalars(stmt)]


@router.post("/files", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    name: str = Form(""),
    category: str = Form("autre"),
    company_id: int | None = Form(None),
    project_id: int | None = Form(None),
    expires_on: date | None = Form(None),
    notes: str = Form(""),
    user: User = Depends(manager_user),
    db: Session = Depends(get_db),
):
    original = Path(file.filename or "fichier").name
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(
            400,
            f"Type de fichier non autorisé ({ext or 'sans extension'}). Autorisés : {', '.join(sorted(ALLOWED))}",
        )
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Fichier trop volumineux (15 Mo maximum).")
    if not data:
        raise HTTPException(400, "Fichier vide.")
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        raise HTTPException(400, "Le contenu du fichier ne correspond pas à son extension.")
    stored = secrets.token_hex(16) + ext  # nom aléatoire : jamais celui fourni par l'utilisateur
    (_files_dir() / stored).write_bytes(data)
    rec = FileRecord(
        name=(name or original)[:200],
        category=category[:40],
        original_name=original[:300],
        stored_name=stored,
        mime=mimetypes.types_map.get(ext, "application/octet-stream"),
        size=len(data),
        company_id=company_id,
        project_id=project_id,
        expires_on=expires_on,
        notes=notes[:500],
        uploaded_by=user.email,
    )
    db.add(rec)
    db.commit()
    audit(db, user.email, "file_uploaded", rec.name)
    return _file_out(rec)


@router.get("/files/{file_id}/download", dependencies=[Depends(manager_user)])
def download_file(file_id: int, db: Session = Depends(get_db)):
    f = db.get(FileRecord, file_id)
    path = _files_dir() / f.stored_name if f else None
    if not f or not path or not path.exists():
        raise HTTPException(404)
    return FileResponse(
        path, media_type=f.mime, filename=f.original_name, content_disposition_type="attachment"
    )


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    f = db.get(FileRecord, file_id)
    if not f:
        raise HTTPException(404)
    (_files_dir() / f.stored_name).unlink(missing_ok=True)
    db.delete(f)
    db.commit()
    audit(db, user.email, "file_deleted", f.name)
