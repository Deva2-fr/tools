import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.core.db import get_db
from app.core.security import (
    COOKIE_NAME,
    current_user,
    hash_password,
    login_limiter,
    set_session_cookie,
    verify_password,
)
from app.models import AuditLog, User
from app.schemas import LoginIn, PasswordChange, ProfileUpdate, TotpCode, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
DUMMY_HASH = hash_password("dummy-password-for-timing")


def audit(db: Session, email: str, action: str, detail: str = "") -> None:
    db.add(AuditLog(user_email=email, action=action, detail=detail))
    db.commit()


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}|{body.email.lower()}"
    if login_limiter.blocked(key):
        raise HTTPException(429, "Trop d'essais. Réessayez dans 15 minutes.")
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    # On vérifie toujours un hash pour garder un temps de réponse identique (anti-énumération).
    password_ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not (user and user.is_active and password_ok):
        login_limiter.fail(key)
        audit(db, body.email, "login_failed")
        raise HTTPException(401, "Identifiants incorrects")
    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(401, "totp_required")
        if not pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(body.totp_code.strip(), valid_window=1):
            login_limiter.fail(key)
            audit(db, user.email, "login_failed_2fa")
            raise HTTPException(401, "Code à 6 chiffres incorrect")
    login_limiter.reset(key)
    set_session_cookie(response, user)
    audit(db, user.email, "login")
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/me/tours-done", status_code=204)
def tours_done(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Première session vue : les guides ne se lanceront plus tout seuls (bouton « ? » toujours dispo)."""
    user.tours_done = True
    db.commit()


@router.put("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdate, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Mes informations : nom et e-mail (le changement d'e-mail demande le mot de passe actuel)."""
    email = body.email.lower().strip()
    if email != user.email:
        if not verify_password(user.password_hash, body.current_password):
            raise HTTPException(400, "Mot de passe actuel incorrect")
        if db.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "Cet e-mail est déjà utilisé")
        audit(db, user.email, "email_changed", f"{user.email} → {email}")
        user.email = email
        user.session_version = (user.session_version or 0) + 1  # autres sessions fermées
        set_session_cookie(response, user)
    user.name = body.name.strip()[:120]
    db.commit()
    return user


@router.post("/password")
def change_password(
    body: PasswordChange,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Mot de passe actuel incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Le nouveau mot de passe doit être différent de l'actuel")
    user.password_hash = hash_password(body.new_password)
    # Les autres sessions sont fermées ; celle-ci reçoit un nouveau jeton.
    user.session_version = (user.session_version or 0) + 1
    db.commit()
    set_session_cookie(response, user)
    audit(db, user.email, "password_changed")
    return {"ok": True}


@router.post("/totp/setup")
def totp_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    user.totp_enabled = False
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Deva2 Hub")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/totp/enable")
def totp_enable(body: TotpCode, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.totp_secret_enc:
        raise HTTPException(400, "Lancez d'abord la configuration")
    if not pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "Code incorrect")
    user.totp_enabled = True
    db.commit()
    audit(db, user.email, "totp_enabled")
    return {"ok": True}


@router.post("/totp/disable")
def totp_disable(body: TotpCode, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.totp_enabled and not pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(
        body.code.strip(), valid_window=1
    ):
        raise HTTPException(400, "Code incorrect")
    user.totp_enabled, user.totp_secret_enc = False, None
    db.commit()
    audit(db, user.email, "totp_disabled")
    return {"ok": True}
