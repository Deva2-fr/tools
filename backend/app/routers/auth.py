import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.db import get_db
from app.core.security import (
    COOKIE_NAME,
    create_session_token,
    current_user,
    hash_password,
    login_limiter,
    verify_password,
)
from app.models import AuditLog, User
from app.schemas import LoginIn, PasswordChange, TotpCode, UserOut

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
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user.id),
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",  # « lax » est nécessaire pour revenir de la page de connexion Microsoft
        max_age=s.session_minutes * 60,
        path="/",
    )
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


@router.post("/password")
def change_password(body: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Mot de passe actuel incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
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
