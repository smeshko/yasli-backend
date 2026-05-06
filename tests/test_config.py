"""Settings: validation and Postgres URL normalisation."""

from __future__ import annotations

import pytest

from yasli.config import Settings


def test_missing_database_url_raises_with_variable_name(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError) as excinfo:
        Settings()
    assert "DATABASE_URL" in str(excinfo.value)


def test_empty_database_url_raises_with_variable_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "   ")
    with pytest.raises(ValueError) as excinfo:
        Settings()
    assert "DATABASE_URL" in str(excinfo.value)


def test_postgres_scheme_is_normalised(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://user:pass@host:5432/db?sslmode=require"
    )
    settings = Settings()
    assert (
        settings.database_url
        == "postgresql+psycopg://user:pass@host:5432/db?sslmode=require"
    )


def test_postgresql_scheme_is_normalised(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@h/d"


def test_canonical_scheme_is_left_alone(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@h/d"
