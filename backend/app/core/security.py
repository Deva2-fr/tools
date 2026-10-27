import hmac
import time
from collections import defaultdict
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.models import User

COOKIE_NAME = "deva2_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "deva2"
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, Exception):
        return False


def create_session_token(user_id: int) -> str:
    s = get_settings()
    payload = {"sub": str(user_id), "exp": utcnow() + timedelta(minutes=s.session_minutes)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    # Protection CSRF : les requêtes qui modifient des données doivent porter un en-tête
    # qu'un site tiers ne peut pas ajouter sans autorisation CORS.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(403, "Requête refusée (en-tête de sécurité manquant)")
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Non connecté")
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
    except Exception:
        raise HTTPException(401, "Session invalide") from None
    if not user or not user.is_active:
        raise HTTPException(401, "Session invalide")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Réservé aux administrateurs")
    return user


def safe_equal(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


class LoginLimiter:
    """Limite les essais de connexion : 5 échecs / 15 min par IP + e-mail."""

    def __init__(self, max_fails: int = 5, window: int = 900):
        self.max_fails, self.window = max_fails, window
        self._fails: dict[str, list[float]] = defaultdict(list)

    def _clean(self, key: str) -> list[float]:
        now = time.monotonic()
        self._fails[key] = [t for t in self._fails[key] if now - t < self.window]
        return self._fails[key]

    def blocked(self, key: str) -> bool:
        return len(self._clean(key)) >= self.max_fails

    def fail(self, key: str) -> None:
        self._clean(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_limiter = LoginLimiter()
