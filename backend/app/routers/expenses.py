from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import current_user
from app.models import Expense, User
from app.schemas import ExpenseIn, ExpenseOut
from app.services import expense_pdf, google_drive, integrations

router = APIRouter(prefix="/expenses", tags=["notes de frais"])


def compute_amounts(ttc: float, vat_rate: float) -> tuple[float, float]:
    ht = round(ttc / (1 + vat_rate / 100), 2)
    return ht, round(ttc - ht, 2)


def _out(e: Expense) -> ExpenseOut:
    out = ExpenseOut.model_validate(e)
    out.has_pdf = bool(e.pdf_path) and Path(e.pdf_path).exists()
    return out


def _apply(e: Expense, body: ExpenseIn) -> None:
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    e.amount_ht, e.amount_vat = compute_amounts(body.amount_ttc, body.vat_rate)


def _pdf_dir() -> Path:
    d = Path(get_settings().data_dir) / "expenses"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("", response_model=list[ExpenseOut])
def list_expenses(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [
        _out(e) for e in db.scalars(select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc()))
    ]


@router.post("", response_model=ExpenseOut, status_code=201)
def create(body: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = Expense(created_by=user.email)
    _apply(e, body)
    db.add(e)
    db.commit()
    return _out(e)


@router.put("/{expense_id}", response_model=ExpenseOut)
def update(expense_id: int, body: ExpenseIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    e = db.get(Expense, expense_id)
    if not e:
        raise HTTPException(404)
    _apply(e, body)
    db.commit()
    return _out(e)


@router.delete("/{expense_id}", status_code=204)
def delete(expense_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    e = db.get(Expense, expense_id)
    if not e:
        raise HTTPException(404)
    if e.pdf_path:
        Path(e.pdf_path).unlink(missing_ok=True)
    db.delete(e)
    db.commit()


def _push_to_drive(db: Session, e: Expense, pdf: bytes) -> str:
    """Dépose le PDF dans Drive. Renvoie l'état pour l'interface : ok | not_configured | error:<message>."""
    if not google_drive.is_configured(db):
        return "not_configured"
    try:
        res = google_drive.upload_pdf(db, expense_pdf.filename(e), pdf, e.drive_file_id)
    except (google_drive.DriveError, google_drive.GoogleNotConfigured) as exc:
        return f"error:{exc}"
    e.drive_file_id, e.drive_link = res.get("id", ""), res.get("webViewLink", "")
    db.commit()
    return "ok"


def _generate(db: Session, e: Expense) -> Response:
    pdf = expense_pdf.render_pdf(e, integrations.company_info(db))
    path = _pdf_dir() / f"note-de-frais-{e.id}.pdf"
    path.write_bytes(pdf)
    e.pdf_path = str(path)
    db.commit()
    drive = _push_to_drive(db, e, pdf)
    # Le PDF est toujours renvoyé, même si Drive échoue : l'état est transmis dans X-Drive-Status.
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{expense_pdf.filename(e)}"',
            "X-Expense-Id": str(e.id),
            "X-Drive-Status": quote(drive[:300]),
            "Access-Control-Expose-Headers": "X-Expense-Id, X-Drive-Status",
        },
    )


@router.post("/save")
def save_and_download(
    body: ExpenseIn,
    expense_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Bouton « Enregistrer » : sauvegarde la note, génère le PDF, le dépose dans Drive et le renvoie."""
    e = db.get(Expense, expense_id) if expense_id else None
    if expense_id and not e:
        raise HTTPException(404)
    if not e:
        e = Expense(created_by=user.email)
        db.add(e)
    _apply(e, body)
    db.commit()
    return _generate(db, e)


@router.get("/{expense_id}/pdf")
def download(expense_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    e = db.get(Expense, expense_id)
    if not e or not e.pdf_path or not Path(e.pdf_path).exists():
        raise HTTPException(404, "Aucun PDF pour cette note")
    return FileResponse(e.pdf_path, media_type="application/pdf", filename=expense_pdf.filename(e))


@router.post("/{expense_id}/drive", response_model=ExpenseOut)
def retry_drive(expense_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Renvoie dans Drive le PDF d'une note (après correction du réglage Google, par exemple)."""
    e = db.get(Expense, expense_id)
    if not e:
        raise HTTPException(404)
    pdf = expense_pdf.render_pdf(e, integrations.company_info(db))
    status = _push_to_drive(db, e, pdf)
    if status == "not_configured":
        raise HTTPException(
            400, "Google Drive n'est pas configuré (Paramètres > Intégrations > Google Drive)."
        )
    if status.startswith("error:"):
        raise HTTPException(502, status[6:])
    return _out(e)
