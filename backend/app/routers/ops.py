"""Abonnements, trésorerie, temps, équipe, registre d'accès, documents."""

import mimetypes
import secrets
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
    DocumentFolder,
    Employee,
    Expense,
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
from app.services import doc_ai, links, qonto, renewals, treasury

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
    extra_out={"link_count": (int, 0), "spent_12m": (float, 0.0)},
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


class SubscriptionLinks(BaseModel):
    invoice_ids: list[int] = Field(default_factory=list, max_length=500)
    transaction_ids: list[int] = Field(default_factory=list, max_length=500)
    expense_ids: list[int] = Field(default_factory=list, max_length=500)


def _links(db: Session, s: Subscription) -> dict:
    accounts = {a.id: a.name for a in db.scalars(select(BankAccount))}
    return {
        "invoices": [
            {
                "id": d.id,
                "date": d.issue_date,
                "label": d.number or f"Brouillon #{d.id}",
                "status": d.status,
                "amount": d.total_ttc,
                "external_url": d.external_url,
            }
            for d in s.invoices
        ],
        "transactions": [
            {
                "id": t.id,
                "date": t.tx_date,
                "label": t.label,
                "account": accounts.get(t.account_id, ""),
                "amount": abs(float(t.amount)),
            }
            for t in s.transactions
        ],
        "expenses": [
            {
                "id": e.id,
                "date": e.expense_date,
                "label": e.reason,
                "employee": e.employee,
                "amount": e.amount_ttc,
            }
            for e in s.expenses
        ],
        "spent_12m": s.spent_12m,
        "annual_cost": renewals.annual_cost(s),
    }


def _sub(db: Session, sub_id: int) -> Subscription:
    s = db.get(Subscription, sub_id)
    if not s:
        raise HTTPException(404)
    return s


def _fetch(db: Session, model, ids: list[int], what: str) -> list:
    wanted = set(ids)
    rows = db.scalars(select(model).where(model.id.in_(wanted))).all() if wanted else []
    if len(rows) != len(wanted):
        raise HTTPException(400, f"{what} introuvable")
    return list(rows)


@router.get("/subscriptions/{sub_id}/links", dependencies=[Depends(manager_user)])
def subscription_links(sub_id: int, db: Session = Depends(get_db)):
    return _links(db, _sub(db, sub_id))


@router.get("/subscriptions/link-suggestions", dependencies=[Depends(manager_user)])
def subscription_link_suggestions(db: Session = Depends(get_db)):
    """Débits bancaires qui ressemblent à un abonnement mais n'y sont pas rattachés."""
    return links.subscription_suggestions(db)


class LinkAdd(BaseModel):
    transaction_ids: list[int] = Field(default_factory=list, max_length=200)


@router.post("/subscriptions/{sub_id}/links/add")
def add_subscription_links(
    sub_id: int, body: LinkAdd, db: Session = Depends(get_db), user: User = Depends(manager_user)
):
    """Ajoute des débits aux dépenses liées (sans toucher aux liens existants)."""
    s = _sub(db, sub_id)
    new = [
        t
        for t in _fetch(db, Transaction, body.transaction_ids, "Mouvement bancaire")
        if t not in s.transactions
    ]
    if any(t.amount >= 0 for t in new):
        raise HTTPException(400, "Seuls les débits (sorties d'argent) peuvent être liés à un abonnement.")
    s.transactions.extend(new)
    db.commit()
    audit(db, user.email, "subscription_links_added", f"{s.name}: +{len(new)} mouvement(s)")
    return _links(db, s)


@router.put("/subscriptions/{sub_id}/links")
def set_subscription_links(
    sub_id: int, body: SubscriptionLinks, db: Session = Depends(get_db), user: User = Depends(manager_user)
):
    s = _sub(db, sub_id)
    transactions = _fetch(db, Transaction, body.transaction_ids, "Mouvement bancaire")
    if any(t.amount >= 0 for t in transactions):
        raise HTTPException(400, "Seuls les débits (sorties d'argent) peuvent être liés à un abonnement.")
    s.invoices = _fetch(db, BillingDoc, body.invoice_ids, "Facture")
    s.transactions = transactions
    s.expenses = _fetch(db, Expense, body.expense_ids, "Note de frais")
    db.commit()
    audit(
        db,
        user.email,
        "subscription_links_updated",
        f"{s.name}: {len(s.invoices)} facture(s), {len(s.transactions)} mouvement(s), {len(s.expenses)} note(s)",
    )
    return _links(db, s)


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
MAX_UPLOAD = 25 * 1024 * 1024
MAX_VIDEO = 500 * 1024 * 1024
VIDEOS = {".mp4", ".mov", ".m4v", ".webm"}
ALLOWED = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".docx",
    ".xlsx",
    ".odt",
    ".ods",
    ".txt",
    ".csv",
    ".pptx",
} | VIDEOS
VIDEO_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
CHUNK = 1024 * 1024
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
    ".webm": b"\x1a\x45\xdf\xa3",
}


def _content_ok(ext: str, head: bytes) -> bool:
    """Vérifie que le début du fichier correspond à son extension (mp4/mov : « ftyp » à l'octet 4)."""
    if ext in (".mp4", ".mov", ".m4v"):
        return head[4:8] == b"ftyp"
    return ext not in MAGIC or head.startswith(MAGIC[ext])


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
        "folder_id": f.folder_id,
    }


# ---------- Dossiers des documents ----------
class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: int | None = None


class FileMove(BaseModel):
    folder_id: int | None = None


def _folder(db: Session, folder_id: int | None) -> DocumentFolder | None:
    if folder_id is None:
        return None
    f = db.get(DocumentFolder, folder_id)
    if not f:
        raise HTTPException(404, "Dossier introuvable.")
    return f


def _check_name(db: Session, name: str, parent_id: int | None, exclude: int | None = None) -> str:
    name = name.strip().replace("/", "-")
    if not name:
        raise HTTPException(400, "Donnez un nom au dossier.")
    same_parent = (
        DocumentFolder.parent_id.is_(None) if parent_id is None else DocumentFolder.parent_id == parent_id
    )
    for other in db.scalars(select(DocumentFolder).where(same_parent)):
        if other.id != exclude and other.name.lower() == name.lower():
            raise HTTPException(400, f"Un dossier « {name} » existe déjà ici.")
    return name


# Organisation recommandée : un dossier par client, et des dossiers fixes pour la vie de l'entreprise.
CLIENTS_ROOT = "01 Clients"
CLIENT_SUBFOLDERS = [
    "Devis & contrats",
    "Factures",
    "Projet & livrables",
    "Échanges & comptes rendus",
    "Accès & technique",
]


def _template() -> list[tuple[str, list]]:
    year = str(date.today().year)
    return [
        (CLIENTS_ROOT, []),
        (
            "02 Administration",
            [("Juridique", []), ("Assurances", []), ("Banque", []), ("Fournisseurs & abonnements", [])],
        ),
        (
            "03 Comptabilité",
            [
                ("Factures fournisseurs", [(year, [])]),
                ("Notes de frais", [(year, [])]),
                ("Impôts & TVA", []),
                ("Bilans & expert-comptable", []),
            ],
        ),
        ("04 RH", [("Collaborateurs", []), ("Paie & social", [])]),
        ("05 Commercial & marketing", []),
        ("06 Interne", []),
        ("99 Archives", []),
    ]


def _ensure(db: Session, name: str, parent_id: int | None, user: User, created: list) -> DocumentFolder:
    """Dossier `name` sous `parent_id` : réutilisé s'il existe (casse ignorée), sinon créé."""
    same_parent = (
        DocumentFolder.parent_id.is_(None) if parent_id is None else DocumentFolder.parent_id == parent_id
    )
    for f in db.scalars(select(DocumentFolder).where(same_parent)):
        if f.name.lower() == name.lower():
            return f
    f = DocumentFolder(name=name, parent_id=parent_id, created_by=user.email)
    db.add(f)
    db.flush()
    created.append(f)
    return f


def _build(db: Session, tree: list, parent_id: int | None, user: User, created: list) -> None:
    for name, children in tree:
        _build(db, children, _ensure(db, name, parent_id, user, created).id, user, created)


def client_folder(db: Session, company: Company, user: User, created: list) -> DocumentFolder:
    """Dossier du client (01 Clients › <nom>) avec ses sous-dossiers, créé au besoin et relié à la société."""
    folder = db.scalar(select(DocumentFolder).where(DocumentFolder.company_id == company.id))
    if not folder:
        root = _ensure(db, CLIENTS_ROOT, None, user, created)
        name = company.name.strip().replace("/", "-")[:120] or f"Société {company.id}"
        folder = _ensure(db, name, root.id, user, created)
        if folder.company_id and folder.company_id != company.id:  # homonyme déjà relié à une autre société
            folder = _ensure(db, f"{name} ({company.id})", root.id, user, created)
        folder.company_id = company.id
    for sub in CLIENT_SUBFOLDERS:
        _ensure(db, sub, folder.id, user, created)
    return folder


def _folder_out(f: DocumentFolder, files: int = 0, folders: int = 0) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "parent_id": f.parent_id,
        "company_id": f.company_id,
        "files": files,
        "folders": folders,
    }


@router.post("/files/folders/template")
def create_template(user: User = Depends(manager_user), db: Session = Depends(get_db)):
    """Crée l'organisation recommandée. Relançable : ce qui existe déjà est gardé, rien n'est déplacé."""
    created: list[DocumentFolder] = []
    _build(db, _template(), None, user, created)
    db.commit()
    audit(db, user.email, "folders_template", f"{len(created)} dossier(s) créé(s)")
    return {"created": len(created)}


@router.get("/files/clients/{company_id}")
def company_folder(company_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    """Dossier du client et ses sous-dossiers (créés à la première ouverture depuis la fiche société)."""
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404)
    created: list[DocumentFolder] = []
    folder = client_folder(db, company, user, created)
    db.commit()
    if created:
        audit(db, user.email, "client_folder_created", company.name)
    # Sous-dossiers prévus d'abord, dans l'ordre d'usage, puis ceux ajoutés à la main.
    order = {n.lower(): i for i, n in enumerate(CLIENT_SUBFOLDERS)}
    subs = sorted(
        db.scalars(select(DocumentFolder).where(DocumentFolder.parent_id == folder.id)),
        key=lambda f: (order.get(f.name.lower(), len(order)), f.name.lower()),
    )
    return {**_folder_out(folder), "subfolders": [_folder_out(f) for f in subs]}


@router.post("/files/clients")
def create_all_client_folders(user: User = Depends(manager_user), db: Session = Depends(get_db)):
    """Un dossier pour chaque société de type « client » qui n'en a pas encore."""
    created: list[DocumentFolder] = []
    clients = db.scalars(select(Company).where(Company.kind == "client").order_by(Company.name)).all()
    for company in clients:
        client_folder(db, company, user, created)
    db.commit()
    audit(db, user.email, "client_folders_created", f"{len(created)} dossier(s) créé(s)")
    return {"clients": len(clients), "created": len(created)}


@router.get("/files/folders", dependencies=[Depends(manager_user)])
def list_folders(db: Session = Depends(get_db)):
    folders = db.scalars(select(DocumentFolder).order_by(DocumentFolder.name)).all()
    files = {
        fid: n
        for fid, n in db.execute(select(FileRecord.folder_id, func.count()).group_by(FileRecord.folder_id))
    }
    subs: dict[int, int] = {}
    for f in folders:
        if f.parent_id:
            subs[f.parent_id] = subs.get(f.parent_id, 0) + 1
    return [_folder_out(f, files.get(f.id, 0), subs.get(f.id, 0)) for f in folders]


@router.post("/files/folders", status_code=201)
def create_folder(body: FolderIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    _folder(db, body.parent_id)
    f = DocumentFolder(
        name=_check_name(db, body.name, body.parent_id), parent_id=body.parent_id, created_by=user.email
    )
    db.add(f)
    db.commit()
    audit(db, user.email, "folder_created", f.name)
    return _folder_out(f)


@router.put("/files/folders/{folder_id}")
def update_folder(
    folder_id: int, body: FolderIn, user: User = Depends(manager_user), db: Session = Depends(get_db)
):
    f = _folder(db, folder_id)
    # Pas de boucle : on ne range pas un dossier dans lui-même ou dans l'un de ses sous-dossiers.
    p = _folder(db, body.parent_id)
    while p is not None:
        if p.id == f.id:
            raise HTTPException(
                400, "Impossible de ranger un dossier dans l'un de ses propres sous-dossiers."
            )
        p = db.get(DocumentFolder, p.parent_id) if p.parent_id else None
    f.name = _check_name(db, body.name, body.parent_id, exclude=f.id)
    f.parent_id = body.parent_id
    db.commit()
    audit(db, user.email, "folder_updated", f.name)
    return {"id": f.id, "name": f.name, "parent_id": f.parent_id}


@router.delete("/files/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    f = _folder(db, folder_id)
    has_files = db.scalar(select(func.count()).select_from(FileRecord).where(FileRecord.folder_id == f.id))
    has_subs = db.scalar(
        select(func.count()).select_from(DocumentFolder).where(DocumentFolder.parent_id == f.id)
    )
    if has_files or has_subs:
        raise HTTPException(400, "Videz le dossier avant de le supprimer (fichiers et sous-dossiers).")
    db.delete(f)
    db.commit()
    audit(db, user.email, "folder_deleted", f.name)


@router.get("/files", dependencies=[Depends(manager_user)])
def list_files(
    company_id: int | None = None, q: str = "", folder_id: int | None = None, db: Session = Depends(get_db)
):
    """Contenu d'un dossier (racine si aucun). Une recherche ou un filtre société porte sur tous les dossiers."""
    stmt = select(FileRecord).order_by(FileRecord.id.desc()).limit(500)
    if company_id:
        stmt = stmt.where(FileRecord.company_id == company_id)
    if q:
        stmt = stmt.where(FileRecord.name.ilike(f"%{q}%") | FileRecord.original_name.ilike(f"%{q}%"))
    elif not company_id:
        stmt = stmt.where(FileRecord.folder_id == folder_id if folder_id else FileRecord.folder_id.is_(None))
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
    folder_id: int | None = Form(None),
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
    limit = MAX_VIDEO if ext in VIDEOS else MAX_UPLOAD
    _folder(db, folder_id)
    stored = secrets.token_hex(16) + ext  # nom aléatoire : jamais celui fourni par l'utilisateur
    path = _files_dir() / stored
    size = 0
    try:
        with path.open("wb") as out:  # écriture par morceaux : une vidéo ne passe jamais entière en mémoire
            while chunk := await file.read(CHUNK):
                if not size and not _content_ok(ext, chunk):
                    raise HTTPException(400, "Le contenu du fichier ne correspond pas à son extension.")
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        413, f"Fichier trop volumineux ({limit // (1024 * 1024)} Mo maximum)."
                    )
                out.write(chunk)
        if not size:
            raise HTTPException(400, "Fichier vide.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    rec = FileRecord(
        name=(name or original)[:200],
        category=category[:40],
        original_name=original[:300],
        stored_name=stored,
        mime=VIDEO_MIME.get(ext) or mimetypes.types_map.get(ext, "application/octet-stream"),
        size=size,
        company_id=company_id,
        project_id=project_id,
        expires_on=expires_on,
        notes=notes[:500],
        folder_id=folder_id,
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


@router.get("/files/{file_id}/view", dependencies=[Depends(manager_user)])
def view_file(file_id: int, db: Session = Depends(get_db)):
    """Affichage dans la page (lecteur vidéo) ; les requêtes partielles permettent d'avancer dans la vidéo."""
    f = db.get(FileRecord, file_id)
    path = _files_dir() / f.stored_name if f else None
    if not f or not path or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type=f.mime, filename=f.original_name, content_disposition_type="inline")


@router.post("/files/{file_id}/ai-analyze", dependencies=[Depends(manager_user)])
def ai_analyze_file(file_id: int, db: Session = Depends(get_db)):
    """Résumé, dates clés et préavis d'un contrat ou document (PDF / image) lus par l'IA."""
    f = db.get(FileRecord, file_id)
    path = _files_dir() / f.stored_name if f else None
    if not f or not path or not path.exists():
        raise HTTPException(404)
    try:
        return doc_ai.analyze_contract(db, path.read_bytes(), Path(f.original_name).suffix)
    except doc_ai.DocAIError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/files/{file_id}/folder")
def move_file(
    file_id: int, body: FileMove, user: User = Depends(manager_user), db: Session = Depends(get_db)
):
    f = db.get(FileRecord, file_id)
    if not f:
        raise HTTPException(404)
    dest = _folder(db, body.folder_id)
    f.folder_id = body.folder_id
    db.commit()
    audit(db, user.email, "file_moved", f"{f.name} → {dest.name if dest else 'racine'}")
    return _file_out(f)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    f = db.get(FileRecord, file_id)
    if not f:
        raise HTTPException(404)
    (_files_dir() / f.stored_name).unlink(missing_ok=True)
    db.delete(f)
    db.commit()
    audit(db, user.email, "file_deleted", f.name)
