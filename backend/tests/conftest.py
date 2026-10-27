import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    SECRET_KEY="test-secret-key-test-secret-key-0123",
    ENCRYPTION_KEY="test-encryption-key",
    ADMIN_EMAIL="admin@test.fr",
    ADMIN_PASSWORD="CorrectHorse-Battery-9",
    WEBHOOK_TOKEN="hook-token",
    COOKIE_SECURE="false",
    DATA_DIR=f"{_tmp}/data",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import run_migrations  # noqa: E402

H = {"X-Requested-With": "deva2"}


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    run_migrations()  # le schéma des tests vient des vraies migrations Alembic
    with SessionLocal() as session:
        from app.seed import seed

        seed(session)
        yield session


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        c.headers.update(H)
        r = c.post("/api/auth/login", json={"email": "admin@test.fr", "password": "CorrectHorse-Battery-9"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture()
def anon(db):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def as_role(client):
    """as_role('manager') -> client connecté avec ce rôle (créé par l'admin)."""
    made = []

    def make(role: str, email: str | None = None):
        email = email or f"{role}@test.fr"
        r = client.post(
            "/api/users", json={"email": email, "password": "another-long-password", "role": role}
        )
        assert r.status_code in (201, 409), r.text
        c = TestClient(app)
        c.headers.update(H)
        r = c.post("/api/auth/login", json={"email": email, "password": "another-long-password"})
        assert r.status_code == 200, r.text
        made.append(c)
        return c

    yield make
    for c in made:
        c.close()
