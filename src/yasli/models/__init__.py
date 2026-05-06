"""ORM model registry. The `Base` declarative root lives here so future
changes (s05 onwards) can attach their tables and Alembic's `target_metadata`
keeps pointing at one place."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


__all__ = ["Base"]
