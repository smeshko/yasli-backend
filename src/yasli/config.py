"""Backend configuration loaded from environment variables.

Settings are validated at object construction time. Importing this module is
side-effect-free; callers create `Settings()` (typically once, at startup)
and a missing or empty `DATABASE_URL` raises `ValueError` immediately, before
any DB connection is attempted.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CORS_ALLOWED_ORIGINS_ENV = "CORS_ALLOWED_ORIGINS"


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


def parse_cors_allowed_origins(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()

    origins: list[str] = []
    seen: set[str] = set()

    for part in raw.split(","):
        value = part.strip()

        if value == "":
            continue

        origin = _normalise_cors_origin(value)
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)

    return tuple(origins)


def _normalise_cors_origin(raw: str) -> str:
    parsed = urlsplit(raw)

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{CORS_ALLOWED_ORIGINS_ENV} entries must be absolute http(s) origins "
            "without paths, query strings, fragments, or credentials"
        )

    return f"{parsed.scheme}://{parsed.netloc}"


class CorsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    cors_allowed_origins: str = ""

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return parse_cors_allowed_origins(self.cors_allowed_origins)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

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
