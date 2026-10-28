"""Fabrique de routes CRUD : liste (recherche/tri), création, modification, suppression, export CSV."""

import csv
import io
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_role
from app.models import User
from app.routers.auth import audit


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def out_schema(model, schema_in: type[BaseModel], extra: dict[str, Any] | None = None) -> type[BaseModel]:
    """Schéma de sortie = schéma d'entrée + id (+ champs en lecture seule)."""
    fields: dict[str, Any] = {"id": (int, ...)}
    fields.update(extra or {})
    return create_model(f"{model.__name__}Out", __base__=(schema_in, _ORM), **fields)


def csv_response(filename: str, header: list[str], rows: list[list[Any]]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    for row in rows:
        # Neutralise l'injection de formules quand le fichier est ouvert dans Excel.
        w.writerow([("'" + v) if isinstance(v, str) and v[:1] in "=+-@" and v else v for v in row])
    return Response(
        "﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def crud_router(
    prefix: str,
    model,
    schema_in: type[BaseModel],
    *,
    tag: str,
    read: str = "member",
    write: str = "member",
    search: tuple[str, ...] = (),
    order_by=None,
    filters: tuple[str, ...] = (),
    label: Callable[[Any], str] | None = None,
    extra_out: dict[str, Any] | None = None,
) -> tuple[APIRouter, type[BaseModel]]:
    """`read`/`write` = rôle minimum. `filters` = colonnes filtrables par ?colonne=valeur."""
    schema_out = out_schema(model, schema_in, extra_out)
    router = APIRouter(prefix=prefix, tags=[tag])
    fields = list(schema_in.model_fields)
    name = prefix.strip("/")

    def _label(o) -> str:
        return label(o) if label else f"{name} #{o.id}"

    @router.get("", response_model=list[schema_out])
    def list_items(
        request: Request,
        q: str = "",
        limit: int = 500,
        db: Session = Depends(get_db),
        _: User = Depends(require_role(read)),
    ):
        stmt = select(model)
        for col in filters:  # ?company_id=3
            val = request.query_params.get(col)
            if val not in (None, ""):
                stmt = stmt.where(getattr(model, col) == (int(val) if val.lstrip("-").isdigit() else val))
        if q and search:
            stmt = stmt.where(or_(*[getattr(model, c).ilike(f"%{q}%") for c in search]))
        order = order_by if order_by is not None else [model.id.desc()]
        stmt = stmt.order_by(*(order if isinstance(order, (list, tuple)) else [order]))
        return db.scalars(stmt.limit(min(limit, 2000))).all()

    @router.post("", response_model=schema_out, status_code=201)
    def create(body: schema_in, db: Session = Depends(get_db), user: User = Depends(require_role(write))):  # type: ignore[valid-type]
        obj = model(**body.model_dump())
        db.add(obj)
        db.commit()
        audit(db, user.email, f"{name}_created", _label(obj))
        return obj

    @router.put("/{item_id}", response_model=schema_out)
    def update(
        item_id: int,
        body: schema_in,
        db: Session = Depends(get_db),
        user: User = Depends(require_role(write)),  # type: ignore[valid-type]
    ):
        obj = db.get(model, item_id)
        if not obj:
            raise HTTPException(404, "Introuvable")
        for k, v in body.model_dump().items():
            setattr(obj, k, v)
        db.commit()
        audit(db, user.email, f"{name}_updated", _label(obj))
        return obj

    @router.delete("/{item_id}", status_code=204)
    def delete(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(write))):
        obj = db.get(model, item_id)
        if not obj:
            raise HTTPException(404, "Introuvable")
        text = _label(obj)
        db.delete(obj)
        db.commit()
        audit(db, user.email, f"{name}_deleted", text)

    @router.get("/export/csv")
    def export(db: Session = Depends(get_db), _: User = Depends(require_role(read))):
        rows = db.scalars(select(model).order_by(model.id)).all()
        return csv_response(f"{name}.csv", fields, [[getattr(r, f) for f in fields] for r in rows])

    return router, schema_out
