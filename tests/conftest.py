"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ensure_database_url(monkeypatch):
    """Default to a placeholder DATABASE_URL so importing modules that read
    Settings doesn't blow up. Tests that exercise missing/invalid configuration
    monkeypatch this back themselves."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
