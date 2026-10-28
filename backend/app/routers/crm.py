import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user, require_role
from app.models import (
    Activity,
    BillingDoc,
    Company,
    Contact,
    FileRecord,
    MailMessage,
    Opportunity,
    Task,
    User,
)
from app.routers._common import crud_router, out_schema
from app.routers.auth import audit
from app.schemas_crm import (
    STAGE_DEFAULT_PROBA,
    ActivityIn,
    CompanyIn,
    ContactIn,
    CsvImport,
    OpportunityIn,
    StageIn,
    TaskIn,
)
from app.services import company_lookup, outlook

router = APIRouter(prefix="/crm", dependencies=[Depends(current_user)])

companies, CompanyOut = crud_router(
    "/companies",
    Company,
    CompanyIn,
    tag="crm",
    search=("name", "siret", "city", "tags", "email"),
    order_by=[Company.name],
    label=lambda o: o.name,
)
contacts, ContactOut = crud_router(
    "/contacts",
    Contact,
    ContactIn,
    tag="crm",
    search=("first_name", "last_name", "email", "tags", "job_title"),
    order_by=[Contact.last_name, Contact.first_name],
    filters=("company_id",),
    label=lambda o: f"{o.first_name} {o.last_name}".strip(),
)
opportunities, OpportunityOut = crud_router(
    "/opportunities",
    Opportunity,
    OpportunityIn,
    tag="crm",
    search=("title", "next_action"),
    filters=("company_id", "stage"),
    label=lambda o: o.title,
)
tasks, TaskOut = crud_router(
    "/tasks",
    Task,
    TaskIn,
    tag="crm",
    search=("title",),
    filters=("company_id", "contact_id", "opportunity_id", "done"),
    order_by=[Task.done, Task.due_date.is_(None), Task.due_date],
    label=lambda o: o.title,
)
for r in (companies, contacts, opportunities, tasks):
    router.include_router(r)

ActivityOut = out_schema(Activity, ActivityIn, {"created_by": (str, ""), "created_at": (datetime, ...)})


@router.get("/activities", response_model=list[ActivityOut])
def list_activities(
    company_id: int | None = None,
    contact_id: int | None = None,
    opportunity_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = select(Activity).order_by(Activity.created_at.desc()).limit(300)
    for col, val in (
        ("company_id", company_id),
        ("contact_id", contact_id),
        ("opportunity_id", opportunity_id),
    ):
        if val:
            q = q.where(getattr(Activity, col) == val)
    return db.scalars(q).all()


@router.post("/activities", response_model=ActivityOut, status_code=201)
def add_activity(body: ActivityIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = Activity(**body.model_dump(), created_by=user.email)
    db.add(a)
    db.commit()
    return a


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = db.get(Activity, activity_id)
    if not a:
        raise HTTPException(404)
    db.delete(a)
    db.commit()


@router.post("/tasks/{task_id}/toggle", response_model=TaskOut)
def toggle_task(task_id: int, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    t.done = not t.done
    db.commit()
    return t


@router.post("/opportunities/{opp_id}/stage", response_model=OpportunityOut)
def move_stage(opp_id: int, body: StageIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Glisser-déposer du Kanban : change l'étape, ajuste la probabilité et trace l'historique."""
    o = db.get(Opportunity, opp_id)
    if not o:
        raise HTTPException(404)
    if o.stage != body.stage:
        db.add(
            Activity(
                kind="note",
                subject=f"Étape : {o.stage} → {body.stage}",
                opportunity_id=o.id,
                company_id=o.company_id,
                created_by=user.email,
            )
        )
        o.stage = body.stage
        o.probability = STAGE_DEFAULT_PROBA[body.stage]
        if body.stage == "won" and o.company_id:
            company = db.get(Company, o.company_id)
            if company and company.kind == "prospect":
                company.kind = "client"  # un prospect qui signe devient client
        db.commit()
        audit(db, user.email, "opportunity_stage", f"{o.title}: {body.stage}")
    return o


@router.get("/pipeline/summary")
def pipeline_summary(db: Session = Depends(get_db)):
    stages = ["prospect", "contact", "quote", "negotiation", "won", "lost"]
    out = {s: {"count": 0, "amount": 0.0, "weighted": 0.0} for s in stages}
    for o in db.scalars(select(Opportunity)):
        row = out[o.stage]
        row["count"] += 1
        row["amount"] += o.amount
        row["weighted"] += o.amount * o.probability / 100
    open_stages = ("prospect", "contact", "quote", "negotiation")
    return {
        "stages": out,
        "open_amount": sum(out[s]["amount"] for s in open_stages),
        "forecast": round(sum(out[s]["weighted"] for s in open_stages), 2),
        "won_amount": out["won"]["amount"],
    }


def _mails_for(db: Session, emails: set[str], domain: str = "") -> list[dict]:
    if not emails and not domain:
        return []
    rows = db.scalars(select(MailMessage).order_by(MailMessage.received_at.desc()).limit(500)).all()
    out = []
    for m in rows:
        sender = m.sender_email.lower()
        if sender in emails or (domain and sender.endswith("@" + domain)):
            out.append(
                {
                    "id": m.id,
                    "subject": m.subject,
                    "sender": m.sender_name or m.sender_email,
                    "received_at": m.received_at,
                    "tag": outlook.display_tag(m),
                    "web_link": m.web_link,
                }
            )
    return out[:20]


@router.get("/companies/{company_id}/overview")
def company_overview(company_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404)
    cts = db.scalars(select(Contact).where(Contact.company_id == c.id)).all()
    emails = {x.email for x in cts if x.email}
    domain = c.email.split("@")[1].lower() if "@" in c.email else ""
    can_see_money = user.role in ("admin", "manager")
    docs = (
        db.scalars(
            select(BillingDoc).where(BillingDoc.company_id == c.id).order_by(BillingDoc.id.desc())
        ).all()
        if can_see_money
        else []
    )
    invoiced = sum(d.total_ttc for d in docs if d.kind == "invoice" and d.status in ("sent", "paid"))
    paid = sum(d.amount_paid for d in docs if d.kind == "invoice")
    return {
        "company": CompanyOut.model_validate(c),
        "contacts": [ContactOut.model_validate(x) for x in cts],
        "opportunities": [
            OpportunityOut.model_validate(x)
            for x in db.scalars(select(Opportunity).where(Opportunity.company_id == c.id))
        ],
        "tasks": [
            TaskOut.model_validate(x)
            for x in db.scalars(select(Task).where(Task.company_id == c.id, Task.done.is_(False)))
        ],
        "activities": [
            ActivityOut.model_validate(x)
            for x in db.scalars(
                select(Activity)
                .where(Activity.company_id == c.id)
                .order_by(Activity.created_at.desc())
                .limit(50)
            )
        ],
        "documents": [
            {
                "id": d.id,
                "kind": d.kind,
                "number": d.number,
                "status": d.status,
                "total_ttc": d.total_ttc,
                "issue_date": d.issue_date,
            }
            for d in docs
        ],
        "files": [
            {"id": f.id, "name": f.name, "category": f.category}
            for f in db.scalars(select(FileRecord).where(FileRecord.company_id == c.id))
        ],
        "mails": _mails_for(db, emails, domain),
        "money_visible": can_see_money,
        "invoiced": invoiced if can_see_money else None,
        "outstanding": round(invoiced - paid, 2) if can_see_money else None,
    }


@router.get("/contacts/{contact_id}/overview")
def contact_overview(contact_id: int, db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404)
    return {
        "contact": ContactOut.model_validate(c),
        "company": CompanyOut.model_validate(db.get(Company, c.company_id)) if c.company_id else None,
        "activities": [
            ActivityOut.model_validate(x)
            for x in db.scalars(
                select(Activity)
                .where(Activity.contact_id == c.id)
                .order_by(Activity.created_at.desc())
                .limit(50)
            )
        ],
        "tasks": [
            TaskOut.model_validate(x)
            for x in db.scalars(select(Task).where(Task.contact_id == c.id, Task.done.is_(False)))
        ],
        "mails": _mails_for(db, {c.email} if c.email else set()),
    }


def _rows(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))[:2000]


def _import(db: Session, rows: list[dict], schema, model, key=None):
    created, errors = 0, []
    for i, raw in enumerate(rows, start=2):
        data = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        try:
            obj = schema(**{k: v for k, v in data.items() if k in schema.model_fields and v != ""})
        except Exception as exc:
            errors.append(f"ligne {i} : {str(exc).splitlines()[0][:100]}")
            continue
        if key and (kv := getattr(obj, key)) and db.scalar(select(model.id).where(getattr(model, key) == kv)):
            continue  # déjà présent : on ne duplique pas
        db.add(model(**obj.model_dump()))
        created += 1
    db.commit()
    return {"created": created, "errors": errors[:20]}


@router.get("/companies/lookup")
def lookup_company(q: str = ""):
    """Recherche dans l'annuaire public des entreprises (nom, SIREN ou SIRET) pour pré-remplir une fiche."""
    try:
        return company_lookup.search(q)
    except company_lookup.CompanyLookupError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/companies/import", dependencies=[Depends(require_role("member"))])
def import_companies(body: CsvImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    res = _import(db, _rows(body.csv), CompanyIn, Company, key="name")
    audit(db, user.email, "companies_imported", str(res["created"]))
    return res


@router.post("/contacts/import")
def import_contacts(body: CsvImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    res = _import(db, _rows(body.csv), ContactIn, Contact, key="email")
    audit(db, user.email, "contacts_imported", str(res["created"]))
    return res


@router.get("/search")
def search(q: str = "", db: Session = Depends(get_db)):
    """Recherche globale (⌘K) : sociétés, contacts, opportunités."""
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    out = []
    for c in db.scalars(select(Company).where(Company.name.ilike(like) | Company.siret.ilike(like)).limit(6)):
        out.append({"type": "Société", "label": c.name, "sub": c.city, "to": f"/crm/societes/{c.id}"})
    for c in db.scalars(
        select(Contact)
        .where(Contact.first_name.ilike(like) | Contact.last_name.ilike(like) | Contact.email.ilike(like))
        .limit(6)
    ):
        out.append(
            {
                "type": "Contact",
                "label": f"{c.first_name} {c.last_name}".strip() or c.email,
                "sub": c.email,
                "to": f"/crm/contacts?q={c.email or c.last_name}",
            }
        )
    for o in db.scalars(select(Opportunity).where(Opportunity.title.ilike(like)).limit(5)):
        out.append(
            {"type": "Opportunité", "label": o.title, "sub": f"{o.amount:.0f} €", "to": "/crm/pipeline"}
        )
    return out
