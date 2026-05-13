"""Settings: validation and Postgres URL normalisation."""

from __future__ import annotations

from pathlib import Path

import pytest

from yasli.config import CorsSettings, Settings, parse_cors_allowed_origins


def test_missing_database_url_raises_with_variable_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subproject = tmp_path / "backend"
    subproject.mkdir()
    monkeypatch.chdir(subproject)
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


def _write_env(repo_root: Path, body: str) -> None:
    (repo_root / ".env").write_text(body, encoding="utf-8")


def test_dotenv_one_level_up_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path
    subproject = repo_root / "backend"
    subproject.mkdir()
    _write_env(repo_root, "DATABASE_URL=postgres://u:p@h/d\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(subproject)

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://u:p@h/d"


def test_exported_value_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path
    subproject = repo_root / "backend"
    subproject.mkdir()
    _write_env(repo_root, "DATABASE_URL=postgres://from-file/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgres://from-env/db")
    monkeypatch.chdir(subproject)

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://from-env/db"


def test_cors_allowed_origins_are_comma_separated_and_normalised() -> None:
    assert parse_cors_allowed_origins(
        " http://localhost:4321, https://yasli.example.test/, http://localhost:4321 "
    ) == ("http://localhost:4321", "https://yasli.example.test")


def test_empty_cors_allowed_origins_defaults_to_empty_tuple() -> None:
    assert parse_cors_allowed_origins("") == ()
    assert parse_cors_allowed_origins(None) == ()


def test_invalid_cors_allowed_origin_raises_with_variable_name() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_cors_allowed_origins("localhost:4321")
    assert "CORS_ALLOWED_ORIGINS" in str(excinfo.value)


def test_cors_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:4321,http://127.0.0.1:4321",
    )

    settings = CorsSettings()

    assert settings.allowed_origins == (
        "http://localhost:4321",
        "http://127.0.0.1:4321",
    )
