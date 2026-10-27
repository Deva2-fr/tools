import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Project, User

log = logging.getLogger("deva2.seed")

DEFAULT_PROJECTS = [
    {
        "name": "Deva2",
        "url": "https://deva2.fr",
        "environment": "prod",
        "description": "Site de la société Deva2",
    },
    {
        "name": "Formasyl",
        "url": "https://formasyl.org",
        "environment": "prod",
        "description": "Site Formasyl",
    },
    {
        "name": "IceTheaters (dev)",
        "url": "https://dev.icetheaters.deva2.fr",
        "environment": "dev",
        "description": "Environnement de développement IceTheaters",
        # un site de dev est souvent protégé : 401/403 reste « en ligne »
        "expected_status": None,
    },
]


def seed(db: Session) -> None:
    s = get_settings()
    if not db.scalar(select(func.count()).select_from(User)):
        password = s.admin_password
        if not password:
            password = secrets.token_urlsafe(16)
            log.warning("ADMIN_PASSWORD absent : mot de passe admin généré une seule fois : %s", password)
        email = (s.admin_email or "admin@deva2.fr").lower()
        db.add(User(email=email, name="Administrateur", role="admin", password_hash=hash_password(password)))
        db.commit()
        log.warning("Compte administrateur créé : %s", email)
    if not db.scalar(select(func.count()).select_from(Project)):
        for p in DEFAULT_PROJECTS:
            db.add(Project(**p))
        db.commit()
