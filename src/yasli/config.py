"""Backend configuration loaded from environment variables.

Settings are validated at object construction time. Importing this module is
side-effect-free; callers create `Settings()` (typically once, at startup)
and a missing or empty `DATABASE_URL` raises `ValueError` immediately, before
any DB connection is attempted.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalise_database_url(raw: str) -> str:
    """Rewrite Railway's `postgres://` form to SQLAlchemy's
    `postgresql+psycopg://` form, leaving everything else untouched."""
    if raw.startswith("postgresql+psycopg://"):
        return raw
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Default to empty string so pydantic-settings doesn't raise its own
    # "Field required" error before our validator runs — we want a single,
    # consistent error message that names the env var.
    database_url: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def _require_database_url(cls, value: object) -> str:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValueError(
                "required environment variable DATABASE_URL is not set"
            )
        if not isinstance(value, str):
            raise ValueError("DATABASE_URL must be a string")
        return _normalise_database_url(value)
