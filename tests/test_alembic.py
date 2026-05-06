"""`alembic upgrade head` against an empty SQLite DB exits 0 and
populates `alembic_version`. A second run is a no-op exit 0."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_upgrade_head(database_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    src = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_alembic_upgrade_head_creates_version_row(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"

    result = _run_upgrade_head(url)
    assert result.returncode == 0, result.stderr

    engine = create_engine(url, future=True)
    insp = inspect(engine)
    assert "alembic_version" in insp.get_table_names()
    with engine.connect() as conn:
        revs = conn.execute(text("SELECT version_num FROM alembic_version")).all()
    assert revs == [("0001",)]


def test_alembic_upgrade_head_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"

    first = _run_upgrade_head(url)
    assert first.returncode == 0, first.stderr

    second = _run_upgrade_head(url)
    assert second.returncode == 0, second.stderr

    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        revs = conn.execute(text("SELECT version_num FROM alembic_version")).all()
    assert revs == [("0001",)]
