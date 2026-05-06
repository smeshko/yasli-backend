"""yasli.ingest stub: missing DATABASE_URL fails, unknown flag fails with
argparse usage, present DATABASE_URL connects and logs the institutions
row count (skipped if no Postgres is reachable)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(env_extra: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.update(env_extra)
    src = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "yasli.ingest", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _candidate_url() -> str | None:
    explicit = os.environ.get("YASLI_TEST_DATABASE_URL")
    if explicit:
        return explicit
    fallback = os.environ.get("DATABASE_URL")
    if fallback and ("postgres" in fallback):
        return fallback
    return None


def _is_reachable(url: str) -> bool:
    try:
        engine = create_engine(url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def test_missing_database_url_exits_nonzero_with_variable_name() -> None:
    result = _run({}, [])
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_unknown_flag_exits_nonzero_with_argparse_usage() -> None:
    result = _run(
        {"DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/test"},
        ["--no-such-flag"],
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr.lower()


def test_present_database_url_connects_and_logs_row_count() -> None:
    url = _candidate_url()
    if url is None or not _is_reachable(url):
        pytest.skip(
            "Postgres unavailable — set YASLI_TEST_DATABASE_URL to a reachable "
            "Postgres URL (already migrated to head) to run this test."
        )
    result = _run({"DATABASE_URL": url}, [])
    assert result.returncode == 0, result.stderr
    assert "yasli.ingest: stub run" in result.stdout
    assert "institutions row count" in result.stdout
