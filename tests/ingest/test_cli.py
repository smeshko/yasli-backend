"""CLI smoke tests for `python -m yasli.ingest`.

Three of the four cases drive the CLI through subprocess so we exercise
the actual `__main__` entry point and stderr/stdout streams. The fourth
(end-to-end summary line format) calls `main()` in-process so the
moto-mocked R2 and the Postgres testcontainer in the parent process are
visible to the ingest code.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import boto3
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "snapshot_v1_minimal.json"
BUCKET = "yasli-snapshots"
KEY = "snapshots/varna/latest.json"


def _run_cli(env_extra: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        env.pop(k, None)
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


def test_missing_database_url() -> None:
    result = _run_cli({}, [])
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_missing_r2_var() -> None:
    env = {
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/test",
        "R2_ACCOUNT_ID": "acc",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
        # R2_BUCKET intentionally absent
    }
    result = _run_cli(env, [])
    assert result.returncode != 0
    assert "R2_BUCKET" in result.stderr


def test_unknown_flag() -> None:
    env = {
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/test",
        "R2_ACCOUNT_ID": "acc",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET": BUCKET,
    }
    result = _run_cli(env, ["--bogus"])
    assert result.returncode != 0
    assert "usage:" in result.stderr.lower()


@mock_aws
def test_summary_line_format(
    engine,  # provided by tests/ingest/conftest.py
    monkeypatch,
) -> None:
    """End-to-end: real Postgres + moto R2 + in-process `main()`. Stdout
    must be exactly one line containing every field named in the
    run-summary spec.
    """
    snapshot_payload: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=KEY, Body=json.dumps(snapshot_payload).encode("utf-8"))

    # Direct the ingest module to reuse the moto-stubbed client. Easiest
    # path is to monkeypatch r2.make_client to return our `s3` instance.
    from yasli.ingest import r2 as r2_module

    monkeypatch.setattr(r2_module, "make_client", lambda env=None: s3)
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", BUCKET)

    from yasli.ingest.__main__ import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([])
    output = buf.getvalue().strip()

    assert rc == 0
    assert output.count("\n") == 0  # exactly one line
    for field in (
        "ingest done",
        "snapshot=",
        "institutions={inserted:",
        "updated:",
        "unchanged:",
        "disappeared:",
        "streets={inserted:",
        "addresses={inserted:",
        "address_institutions={inserted:",
        "skipped_rows=",
        "elapsed_ms=",
    ):
        assert field in output, f"missing {field!r} in summary line: {output!r}"
