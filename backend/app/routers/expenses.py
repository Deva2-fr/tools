import io
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import admin_user, current_user, is_manager
from app.models import Expense, ExpenseReceipt, Signature, User
from app.routers.auth import audit
from app.schemas import ExpenseIn, ExpenseOut
from app.services import expense_pdf, google_drive, integrations

router = APIRouter(prefix="/expenses", tags=["notes de frais"])

RECEIPT_MAX = 10 * 1024 * 1024
MAX_RECEIPTS = 10
RECEIPT_MAGIC = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
SIGNATURE_MAX = 2 * 1024 * 1024
# Signataires fixes des notes de frais (réglés dans Paramètres) : clé d'intégration par rôle.
SIGNER_KEYS = {"president": "expense_president_user_id", "partner": "expense_partner_user_id"}


def compute_amounts(ttc: float, vat_rate: float) -> tuple[float, float]:
    ht = round(ttc / (1 + vat_rate / 100), 2)
    return ht, round(ttc - ht, 2)


def signer_ids(db: Session) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for role, key in SIGNER_KEYS.items():
        raw = integrations.get(db, key)
        out[role] = int(raw) if raw.isdigit() else None
    return out


def _power(db: Session, user: User) -> bool:
    """Accès à toutes les notes : managers, président et associé (qui signent les notes des autres)."""
    return is_manager(user) or user.id in signer_ids(db).values()


def _out(e: Expense) -> ExpenseOut:
    out = ExpenseOut.model_validate(e)
    out.has_pdf = bool(e.pdf_path) and Path(e.pdf_path).exists()
    out.receipt_files = [{"id": r.id, "name": r.name} for r in e.receipts]
    return out


def _target_user(db: Session, user: User, user_id: int | None) -> User:
    """Utilisateur concerné : soi-même, ou n'importe quel utilisateur actif pour un manager / signataire."""
    if not user_id or user_id == user.id:
        return user
    target = db.get(User, user_id)
    if not _power(db, user):
        raise HTTPException(403, "Vous ne pouvez saisir une note de frais que pour vous-même.")
    if not target or not target.is_active:
        raise HTTPException(400, "Utilisateur introuvable.")
    return target


def _signature_for(
    db: Session, user: User, signature_id: int | None, owner_id: int | None = None, label: str = ""
) -> Signature | None:
    """Signature visible par `user` (la sienne, ou toutes pour un manager / signataire) et, si
    `owner_id` est donné, appartenant à cette personne (le demandeur, le président, l'associé)."""
    if not signature_id:
        return None
    sig = db.get(Signature, signature_id)
    if (
        not sig
        or not (_power(db, user) or sig.user_id == user.id)
        or (owner_id is not None and sig.user_id != owner_id)
    ):
        raise HTTPException(
            400, " ".join(x for x in ("Signature", label, "introuvable pour ce signataire.") if x)
        )
    return sig


def _apply(db: Session, user: User, e: Expense, body: ExpenseIn) -> None:
    target = _target_user(db, user, body.user_id)
    signers = signer_ids(db)
    _signature_for(db, user, body.signature_id, target.id, "du demandeur")
    for role, field in (("president", "president_signature_id"), ("partner", "partner_signature_id")):
        sig_id = getattr(body, field)
        if sig_id and getattr(e, field) != sig_id:  # une signature déjà posée reste valable
            if signers[role] is None:
                raise HTTPException(400, "Choisissez d'abord le président et l'associé dans Paramètres.")
            _signature_for(
                db, user, sig_id, signers[role], "du président" if role == "president" else "de l'associé"
            )
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    e.user_id, e.employee = target.id, (target.name or target.email)[:120]
    e.amount_ht, e.amount_vat = compute_amounts(body.amount_ttc, body.vat_rate)


def _get(db: Session, user: User, expense_id: int) -> Expense:
    e = db.get(Expense, expense_id)
    if not e or not (_power(db, user) or e.user_id == user.id or e.created_by == user.email):
        raise HTTPException(404)
    return e


def _dir(name: str = "") -> Path:
    d = Path(get_settings().data_dir) / "expenses" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pdf_dir() -> Path:
    return _dir()


async def _read_receipt(file: UploadFile) -> tuple[bytes, str, str]:
    original = Path(file.filename or "justificatif").name
    ext = Path(original).suffix.lower()
    if ext not in RECEIPT_MAGIC:
        raise HTTPException(400, f"Justificatif « {original} » : PDF, JPG ou PNG uniquement.")
    data = await file.read(RECEIPT_MAX + 1)
    if len(data) > RECEIPT_MAX:
        raise HTTPException(413, f"Justificatif « {original} » trop volumineux (10 Mo maximum).")
    if not data.startswith(RECEIPT_MAGIC[ext]):
        raise HTTPException(400, f"Le contenu de « {original} » ne correspond pas à son extension.")
    return data, ext, original


def _sig_png(db: Session, sig_id: int | None) -> tuple[bytes | None, str]:
    sig = db.get(Signature, sig_id) if sig_id else None
    if not sig or not Path(sig.image_path).exists():
        return None, ""
    owner = db.get(User, sig.user_id)
    return Path(sig.image_path).read_bytes(), (owner.name or owner.email) if owner else ""


def build_pdf(db: Session, e: Expense) -> bytes:
    """Note de frais + signatures (demandeur, président, associé) + justificatifs en annexe : un seul PDF."""
    signers = signer_ids(db)
    names = {
        role: ((u.name or u.email) if (u := db.get(User, uid)) else "") if uid else ""
        for role, uid in signers.items()
    }
    signatures = {}
    for role, sig_id in (
        ("requester", e.signature_id),
        ("president", e.president_signature_id),
        ("partner", e.partner_signature_id),
    ):
        png, owner = _sig_png(db, sig_id)
        signatures[role] = (png, owner or (e.employee if role == "requester" else names.get(role, "")))
    receipts = [(r.name, Path(r.path).read_bytes()) for r in e.receipts if Path(r.path).exists()]
    note = expense_pdf.render_pdf(e, integrations.company_info(db), signatures, [n for n, _ in receipts])
    return expense_pdf.with_receipts(note, receipts)


# ---------- Signataires (président, associé) ----------
class SignersIn(BaseModel):
    president: int | None = None
    partner: int | None = None


def _signers_out(db: Session) -> dict:
    out = {}
    for role, uid in signer_ids(db).items():
        u = db.get(User, uid) if uid else None
        out[role] = {"id": u.id, "name": u.name or u.email} if u else None
    return out


@router.get("/signers")
def get_signers(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _signers_out(db)


@router.put("/signers")
def set_signers(body: SignersIn, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    for role, key in SIGNER_KEYS.items():
        uid = getattr(body, role)
        if uid and not (db.get(User, uid) and db.get(User, uid).is_active):
            raise HTTPException(400, "Utilisateur introuvable.")
        integrations.put(db, key, str(uid) if uid else "")
    audit(db, admin.email, "expense_signers_updated", str(body.model_dump()))
    return _signers_out(db)


# ---------- Signatures ----------
def _sig_out(sig: Signature) -> dict:
    return {"id": sig.id, "user_id": sig.user_id, "name": sig.name, "created_at": sig.created_at}


@router.get("/signatures")
def list_signatures(
    user_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Ses propres signatures ; un manager (ou le président / l'associé) voit celles de tous
    (filtrables par ?user_id=)."""
    stmt = select(Signature).order_by(Signature.name)
    if not _power(db, user):
        stmt = stmt.where(Signature.user_id == user.id)
    elif user_id:
        stmt = stmt.where(Signature.user_id == user_id)
    return [_sig_out(x) for x in db.scalars(stmt)]


@router.post("/signatures", status_code=201)
async def create_signature(
    name: str = Form(..., min_length=1, max_length=120),
    file: UploadFile = File(...),
    user_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Signature dessinée dans le navigateur ou image importée : ré-encodée en PNG (aucune métadonnée gardée)."""
    owner = _target_user(db, user, user_id)
    data = await file.read(SIGNATURE_MAX + 1)
    if len(data) > SIGNATURE_MAX:
        raise HTTPException(413, "Image trop volumineuse (2 Mo maximum).")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ("PNG", "JPEG") or img.width * img.height > 16_000_000:
            raise HTTPException(400, "Signature : image PNG ou JPG uniquement.")
        img = img.convert("RGBA")
        img.thumbnail((1200, 400))
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "Image de signature illisible.") from exc
    out = io.BytesIO()
    img.save(out, "PNG")
    path = _dir("signatures") / f"{secrets.token_hex(16)}.png"
    path.write_bytes(out.getvalue())
    sig = Signature(name=name.strip(), image_path=str(path), user_id=owner.id)
    db.add(sig)
    db.commit()
    return _sig_out(sig)


@router.get("/signatures/{sig_id}/image")
def signature_image(sig_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sig = _signature_for(db, user, sig_id)
    if not Path(sig.image_path).exists():
        raise HTTPException(404)
    return FileResponse(
        sig.image_path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.delete("/signatures/{sig_id}", status_code=204)
def delete_signature(sig_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sig = _signature_for(db, user, sig_id)
    Path(sig.image_path).unlink(missing_ok=True)
    db.delete(sig)
    db.commit()


@router.get("", response_model=list[ExpenseOut])
def list_expenses(db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if not _power(db, user):  # un membre ne voit que ses notes
        stmt = stmt.where((Expense.user_id == user.id) | (Expense.created_by == user.email))
    return [_out(e) for e in db.scalars(stmt)]


@router.post("", response_model=ExpenseOut, status_code=201)
def create(body: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = Expense(created_by=user.email)
    _apply(db, user, e, body)
    db.add(e)
    db.commit()
    return _out(e)


@router.put("/{expense_id}", response_model=ExpenseOut)
def update(
    expense_id: int, body: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    e = _get(db, user, expense_id)
    _apply(db, user, e, body)
    db.commit()
    return _out(e)


@router.delete("/{expense_id}", status_code=204)
def delete(expense_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _get(db, user, expense_id)
    if e.pdf_path:
        Path(e.pdf_path).unlink(missing_ok=True)
    for r in e.receipts:
        Path(r.path).unlink(missing_ok=True)
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
    pdf = build_pdf(db, e)
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
async def save_and_download(
    data: str = Form(..., description="Champs de la note (JSON)"),
    receipts: list[UploadFile] = File(default=[]),
    remove_receipt_ids: list[int] = Form(default=[]),
    expense_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Bouton « Enregistrer » : sauvegarde la note et ses justificatifs (ajouts, retraits), génère
    le PDF, le dépose dans Drive et le renvoie."""
    try:
        body = ExpenseIn.model_validate_json(data)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(err["msg"] for err in exc.errors())) from exc
    uploads = [await _read_receipt(f) for f in receipts if f.filename]
    e = _get(db, user, expense_id) if expense_id else None
    if not e:
        e = Expense(created_by=user.email)
    _apply(db, user, e, body)  # vérifie utilisateur et signatures avant toute écriture
    db.add(e)
    removed = [r for r in e.receipts if r.id in set(remove_receipt_ids)]
    if len(e.receipts) - len(removed) + len(uploads) > MAX_RECEIPTS:
        raise HTTPException(400, f"{MAX_RECEIPTS} justificatifs maximum par note de frais.")
    for r in removed:
        e.receipts.remove(r)
    added: list[ExpenseReceipt] = []
    start = max((r.position for r in e.receipts), default=-1) + 1
    for i, (content, ext, original) in enumerate(uploads):
        path = _dir("receipts") / f"{secrets.token_hex(16)}{ext}"  # nom aléatoire
        path.write_bytes(content)
        added.append(ExpenseReceipt(path=str(path), name=original[:300], position=start + i))
    e.receipts.extend(added)
    db.commit()
    try:
        response = _generate(db, e)
    except expense_pdf.ReceiptError as exc:
        # Justificatif illisible : on annule les ajouts de cet enregistrement (la note reste enregistrée).
        for r in added:
            Path(r.path).unlink(missing_ok=True)
            e.receipts.remove(r)
        db.commit()
        raise HTTPException(400, str(exc)) from exc
    for r in removed:
        Path(r.path).unlink(missing_ok=True)
    return response


@router.get("/{expense_id}/receipts/{receipt_id}")
def download_receipt(
    expense_id: int, receipt_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    e = _get(db, user, expense_id)
    r = next((x for x in e.receipts if x.id == receipt_id), None)
    if not r or not Path(r.path).exists():
        raise HTTPException(404, "Justificatif introuvable")
    return FileResponse(r.path, filename=r.name)


@router.get("/{expense_id}/pdf")
def download(expense_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _get(db, user, expense_id)
    if not e.pdf_path or not Path(e.pdf_path).exists():
        raise HTTPException(404, "Aucun PDF pour cette note")
    return FileResponse(e.pdf_path, media_type="application/pdf", filename=expense_pdf.filename(e))


@router.post("/{expense_id}/drive", response_model=ExpenseOut)
def retry_drive(expense_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Renvoie dans Drive le PDF d'une note (après correction du réglage Google, par exemple)."""
    e = _get(db, user, expense_id)
    status = _push_to_drive(db, e, build_pdf(db, e))
    if status == "not_configured":
        raise HTTPException(
            400, "Google Drive n'est pas configuré (Paramètres > Intégrations > Google Drive)."
        )
    if status.startswith("error:"):
        raise HTTPException(502, status[6:])
    return _out(e)
