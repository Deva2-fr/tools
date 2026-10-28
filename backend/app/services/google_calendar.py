"""Échéances fiscales → Google Agenda, via le compte de service Google (celui des notes de frais).

L'agenda choisi doit être partagé avec l'e-mail du compte de service, avec le droit
« Apporter des modifications aux événements ». Chaque échéance devient un événement « journée
entière » dont l'identifiant est dérivé de celui de l'échéance : la synchronisation est
idempotente (création, mise à jour, suppression), sans rien stocker de plus.
"""

from datetime import timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import TaxDeadline
from app.services import google_drive, integrations

API = "https://www.googleapis.com/calendar/v3"
SETTING = "google_calendar_id"
REMINDER_DAYS = (7, 1)  # rappels Google : 7 jours et 1 jour avant


class CalendarError(RuntimeError):
    """Erreur affichable telle quelle."""


def calendar_id(db: Session) -> str:
    return integrations.get(db, SETTING).strip()


def event_id(tax_id: int) -> str:
    # Identifiant d'événement Google : caractères a-v et 0-9 uniquement (base32hex).
    return f"deva2t{tax_id:06d}"


def _cal(cal: str) -> str:
    return quote(cal, safe="@.")  # ex. ...@group.calendar.google.com


def _client(db: Session) -> httpx.Client:
    token = google_drive._access_token(db)  # même compte de service que Google Drive
    return httpx.Client(base_url=API, timeout=20, headers={"Authorization": f"Bearer {token}"})


def _email(db: Session) -> str:
    return google_drive._service_account(db)["client_email"]


def _check(r: httpx.Response, db: Session) -> httpx.Response:
    if r.status_code in (403, 404):
        raise CalendarError(
            f"Agenda introuvable ou en lecture seule : dans Google Agenda, partagez-le avec {_email(db)} "
            "(« Apporter des modifications aux événements »), et vérifiez que l'API Google Calendar est activée."
        )
    if r.status_code >= 400:
        raise CalendarError(f"Erreur Google Agenda ({r.status_code}) : {r.text[:200]}")
    return r


def _request(c: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    try:
        return c.request(method, url, **kw)
    except httpx.HTTPError as exc:
        raise CalendarError("Google Agenda est injoignable pour le moment.") from exc


def list_calendars(db: Session, client: httpx.Client | None = None) -> list[dict]:
    """Agendas sur lesquels le compte de service peut écrire (ajoutés via add_calendar)."""
    c = client or _client(db)
    try:
        r = _check(_request(c, "GET", "/users/me/calendarList", params={"minAccessRole": "writer"}), db)
    finally:
        if client is None:
            c.close()
    return [
        {"id": x["id"], "name": x.get("summaryOverride") or x.get("summary") or x["id"]}
        for x in r.json().get("items", [])
    ]


def add_calendar(db: Session, cal_id: str, client: httpx.Client | None = None) -> dict:
    """Ajoute à la liste du compte de service un agenda qu'on lui a partagé (sinon il n'y apparaît pas)."""
    cal_id = cal_id.strip()
    if not cal_id:
        raise CalendarError(
            "Indiquez l'ID de l'agenda (Google Agenda > Paramètres de l'agenda > Intégrer l'agenda)."
        )
    c = client or _client(db)
    try:
        r = _request(c, "POST", "/users/me/calendarList", json={"id": cal_id})
        if r.status_code == 409:  # déjà dans la liste
            r = _request(c, "GET", f"/users/me/calendarList/{_cal(cal_id)}")
        x = _check(r, db).json()
    finally:
        if client is None:
            c.close()
    return {"id": x["id"], "name": x.get("summary") or x["id"]}


def _event(t: TaxDeadline) -> dict:
    amount = f" – {t.amount:.2f} €".replace(".", ",") if t.amount else ""
    paid = t.status == "paid"
    return {
        "id": event_id(t.id),
        "summary": f"{'✓ ' if paid else ''}{t.title}{amount}",
        "description": "\n".join(
            x
            for x in (
                "Échéance suivie dans le Hub Deva2 (Impôts, TVA & déclarations).",
                "Statut : payée." if paid else "Statut : à faire.",
                t.notes,
            )
            if x
        ),
        "start": {"date": t.due_date.isoformat()},
        "end": {"date": (t.due_date + timedelta(days=1)).isoformat()},
        "transparency": "transparent",  # n'occupe pas l'agenda
        "colorId": "2" if paid else "11",  # vert si payée, rouge sinon
        "reminders": {
            "useDefault": False,
            "overrides": [] if paid else [{"method": "popup", "minutes": d * 24 * 60} for d in REMINDER_DAYS],
        },
        "status": "confirmed",
    }


def _upsert(c: httpx.Client, db: Session, cal: str, t: TaxDeadline) -> None:
    body = _event(t)
    r = _request(c, "PUT", f"/calendars/{_cal(cal)}/events/{body['id']}", json=body)
    if r.status_code == 404:  # pas encore créé
        r = _request(c, "POST", f"/calendars/{_cal(cal)}/events", json=body)
    _check(r, db)


def push(db: Session, t: TaxDeadline) -> None:
    """Met à jour (ou crée) l'événement d'une échéance. Ne fait rien si aucun agenda n'est choisi."""
    cal = calendar_id(db)
    if not cal:
        return
    with _client(db) as c:
        _upsert(c, db, cal, t)


def remove(db: Session, tax_id: int) -> None:
    cal = calendar_id(db)
    if not cal:
        return
    with _client(db) as c:
        r = _request(c, "DELETE", f"/calendars/{_cal(cal)}/events/{event_id(tax_id)}")
        if r.status_code not in (404, 410):
            _check(r, db)


def sync_all(db: Session, client: httpx.Client | None = None) -> int:
    """Envoie toutes les échéances (sauf celles payées depuis plus d'un an). Renvoie leur nombre."""
    cal = calendar_id(db)
    if not cal:
        raise CalendarError("Choisissez d'abord l'agenda à synchroniser.")
    since = utcnow().date() - timedelta(days=365)
    rows = db.scalars(select(TaxDeadline).where(TaxDeadline.due_date >= since)).all()
    c = client or _client(db)
    try:
        for t in rows:
            _upsert(c, db, cal, t)
    except CalendarError as exc:
        integrations.put(db, "google_calendar_error", str(exc)[:300])
        raise
    finally:
        if client is None:
            c.close()
    integrations.put(db, "google_calendar_synced_at", utcnow().isoformat())
    integrations.put(db, "google_calendar_error", "")
    return len(rows)
