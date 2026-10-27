"""Applique les migrations Alembic au démarrage (et rattrape les bases créées par la v1 sans Alembic)."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from app.core.db import engine

ROOT = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    tables = set(inspect(engine).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        # Base de la v1 (tables créées sans Alembic) : on la déclare au niveau « schema v1 ».
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")
