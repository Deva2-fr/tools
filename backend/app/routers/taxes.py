import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user, manager_user
from app.models import TaxDeadline
from app.schemas import TaxIn, TaxOut
from app.services import google_calendar, google_drive, integrations, taxes

router = APIRouter(prefix="/taxes", tags=["impôts"], dependencies=[Depends(current_user)])
log = logging.getLogger("deva2.taxes")


def _to_calendar(db: Session, fn, *args) -> None:
    """Report vers Google Agenda « au mieux » : une erreur Google ne bloque jamais l'échéance."""
    if not google_calendar.calendar_id(db):
        return
    try:
        fn(db, *args)
    except (google_calendar.CalendarError, google_drive.GoogleNotConfigured, google_drive.DriveError) as exc:
        log.warning("Google Agenda : %s", exc)
        integrations.put(db, "google_calendar_error", str(exc)[:300])


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
    _to_calendar(db, google_calendar.push, t)
    return _out(t)


@router.put("/{tax_id}", response_model=TaxOut)
def update(tax_id: int, body: TaxIn, db: Session = Depends(get_db)):
    t = db.get(TaxDeadline, tax_id)
    if not t:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    _to_calendar(db, google_calendar.push, t)
    return _out(t)


@router.delete("/{tax_id}", status_code=204)
def delete(tax_id: int, db: Session = Depends(get_db)):
    t = db.get(TaxDeadline, tax_id)
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
    _to_calendar(db, google_calendar.remove, tax_id)


@router.post("/{tax_id}/paid", response_model=TaxOut)
def paid(tax_id: int, db: Session = Depends(get_db)):
    """Marque comme payée ; si l'échéance est récurrente, la suivante est créée automatiquement."""
    t = db.get(TaxDeadline, tax_id)
    if not t:
        raise HTTPException(404)
    nxt = taxes.mark_paid(db, t)
    _to_calendar(db, google_calendar.push, t)
    if nxt:
        _to_calendar(db, google_calendar.push, nxt)
    return _out(t)


@router.post("/generate")
def generate(year: int | None = None, db: Session = Depends(get_db)):
    """Crée les échéances types de l'année (TVA, IS, CFE…) — à vérifier avec votre comptable."""
    created = taxes.generate_year(db, year or date.today().year)
    if created:
        _to_calendar(db, google_calendar.sync_all)
    return {"created": created}


# ---------- Google Agenda ----------
class CalendarIn(BaseModel):
    calendar_id: str = ""


def _calendar_call(fn, *args):
    try:
        return fn(*args)
    except (google_calendar.CalendarError, google_drive.DriveError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except google_drive.GoogleNotConfigured as exc:
        raise HTTPException(
            400, "Renseignez d'abord la clé du compte de service Google (Paramètres > Intégrations > Google)."
        ) from exc


@router.get("/google-calendar")
def calendar_status(db: Session = Depends(get_db)):
    configured = bool(integrations.get(db, "google_service_account_json"))
    email = ""
    if configured:
        try:
            email = google_drive._service_account(db)["client_email"]
        except google_drive.GoogleNotConfigured:
            configured = False
    return {
        "google_configured": configured,
        "service_account_email": email,
        "calendar_id": google_calendar.calendar_id(db),
        "calendar_name": integrations.get(db, "google_calendar_name"),
        "last_synced_at": integrations.get(db, "google_calendar_synced_at") or None,
        "last_error": integrations.get(db, "google_calendar_error"),
    }


@router.get("/google-calendar/calendars", dependencies=[Depends(manager_user)])
def calendar_list(db: Session = Depends(get_db)):
    return _calendar_call(google_calendar.list_calendars, db)


@router.post("/google-calendar/calendars", dependencies=[Depends(manager_user)])
def calendar_add(body: CalendarIn, db: Session = Depends(get_db)):
    """Ajoute un agenda partagé avec le compte de service (par son ID) à la liste de choix."""
    return _calendar_call(google_calendar.add_calendar, db, body.calendar_id)


@router.put("/google-calendar/select", dependencies=[Depends(manager_user)])
def calendar_select(body: CalendarIn, db: Session = Depends(get_db)):
    """Choisit l'agenda (vide = arrêter la synchronisation) puis y envoie toutes les échéances."""
    cal = body.calendar_id.strip()
    if not cal:
        for key in ("google_calendar_id", "google_calendar_name", "google_calendar_error"):
            integrations.put(db, key, "")
        return calendar_status(db)
    known = {c["id"]: c["name"] for c in _calendar_call(google_calendar.list_calendars, db)}
    if cal not in known:
        raise HTTPException(400, "Agenda inconnu : ajoutez-le d'abord avec son ID.")
    integrations.put(db, "google_calendar_id", cal)
    integrations.put(db, "google_calendar_name", known[cal])
    _calendar_call(google_calendar.sync_all, db)
    return calendar_status(db)


@router.post("/google-calendar/sync", dependencies=[Depends(manager_user)])
def calendar_sync(db: Session = Depends(get_db)):
    return {"synced": _calendar_call(google_calendar.sync_all, db)} | calendar_status(db)


@router.get("/calendar.ics")
def ics(db: Session = Depends(get_db)):
    rows = db.scalars(select(TaxDeadline).order_by(TaxDeadline.due_date)).all()
    return Response(
        taxes.to_ics(list(rows)),
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="echeances-deva2.ics"'},
    )
