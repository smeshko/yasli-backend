"""Cloudflare R2 client wrapper for the ingest pipeline.

Mirrors `yasli/scraper/src/yasli_scraper/r2.py` configuration: same env vars,
same endpoint construction, same boto3 version. The backend variant exposes
just one read path — `get_object(key)` returns the body bytes — because
ingest only ever reads `snapshots/varna/latest.json`.

Configuration is validated lazily inside `get_object` rather than at import
time, so importing this module is side-effect-free (mirrors `yasli.config`).
The CLI entrypoint validates the env vars at startup before the first call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv


_REQUIRED_VARS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)

REPO_ENV_PATH = Path("../.env")


class R2ConfigError(ValueError):
    """Raised when one of the four required R2_* env vars is missing or empty."""


def _require_env(name: str, env: dict[str, str]) -> str:
    value = env.get(name, "")
    if value is None or value.strip() == "":
        raise R2ConfigError(
            f"required environment variable {name} is not set"
        )
    return value


def _env_source(env: dict[str, str] | None = None) -> dict[str, str]:
    if env is None:
        load_dotenv(REPO_ENV_PATH)
        return dict(os.environ)
    return env


def validate_env(env: dict[str, str] | None = None) -> None:
    """Raise R2ConfigError if any of the four R2_* vars is missing/empty."""
    source = _env_source(env)
    for name in _REQUIRED_VARS:
        _require_env(name, source)


def _endpoint_url(account_id: str) -> str:
    return f"https://{account_id}.r2.cloudflarestorage.com"


def make_client(env: dict[str, str] | None = None) -> Any:
    """Build a boto3 S3 client pointed at the configured R2 account."""
    source = _env_source(env)
    validate_env(source)
    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(source["R2_ACCOUNT_ID"]),
        aws_access_key_id=source["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=source["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def get_object(
    key: str,
    *,
    client: Any | None = None,
    bucket: str | None = None,
    env: dict[str, str] | None = None,
) -> bytes:
    """Fetch ``key`` from the configured R2 bucket and return the body bytes.

    No streaming, no resume — the snapshot fits comfortably in memory. Any
    boto error (network, missing key, permission denied) propagates to the
    caller so the CLI can map it to a non-zero exit and the original message.
    """
    source = _env_source(env)
    s3 = client if client is not None else make_client(source)
    bucket_name = bucket if bucket is not None else _require_env("R2_BUCKET", source)
    response = s3.get_object(Bucket=bucket_name, Key=key)
    return response["Body"].read()
