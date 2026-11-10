import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.db import SessionLocal
from app.migrate import run_migrations
from app.routers import (
    alerts,
    auth,
    billing,
    crm,
    dashboard,
    expenses,
    integrations,
    mail,
    ops,
    projects,
    public,
    security,
    taxes,
    users,
)
from app.seed import seed

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if tmp := os.environ.get("TMPDIR"):  # gros envois (vidéos) : fichiers temporaires sur disque, pas en RAM
        Path(tmp).mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = tmp
    run_migrations()
    with SessionLocal() as db:
        seed(db)
    yield


# Pas de documentation interactive publique : l'API n'est utilisable qu'après connexion.
app = FastAPI(title="Deva2 Hub", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

for r in (
    auth,
    users,
    projects,
    alerts,
    security,
    mail,
    expenses,
    taxes,
    integrations,
    dashboard,
    crm,
    billing,
    ops,
    public,
):
    app.include_router(r.router, prefix="/api")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logging.getLogger("deva2").exception("Erreur non gérée", exc_info=exc)
    return JSONResponse({"detail": "Erreur interne"}, status_code=500)
