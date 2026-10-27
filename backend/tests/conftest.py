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

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

H = {"X-Requested-With": "deva2"}


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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
