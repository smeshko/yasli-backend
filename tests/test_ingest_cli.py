"""yasli.ingest stub: missing DATABASE_URL fails, present succeeds, unknown
flag fails with argparse usage."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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


def test_missing_database_url_exits_nonzero_with_variable_name() -> None:
    result = _run({}, [])
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_present_database_url_exits_zero_with_stub_line() -> None:
    result = _run(
        {"DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/test"},
        [],
    )
    assert result.returncode == 0, result.stderr
    assert "yasli.ingest: stub run" in result.stdout


def test_unknown_flag_exits_nonzero_with_argparse_usage() -> None:
    result = _run(
        {"DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/test"},
        ["--no-such-flag"],
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr.lower()
