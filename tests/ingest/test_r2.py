"""Cover the three paths through `yasli.ingest.r2`: successful fetch,
missing-key boto error, and missing R2_* env var."""

from __future__ import annotations

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from yasli.ingest import r2


@pytest.fixture
def r2_env(monkeypatch) -> dict[str, str]:
    env = {
        "R2_ACCOUNT_ID": "acc",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET": "yasli-snapshots",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env


def test_validate_env_passes_when_all_set(r2_env: dict[str, str]) -> None:
    r2.validate_env()


@pytest.mark.parametrize(
    "missing",
    ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"],
)
def test_validate_env_names_missing_variable(missing: str, monkeypatch) -> None:
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(r2.R2ConfigError) as excinfo:
        r2.validate_env()
    assert missing in str(excinfo.value)


def test_validate_env_rejects_blank_values(monkeypatch) -> None:
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("R2_BUCKET", "   ")
    with pytest.raises(r2.R2ConfigError) as excinfo:
        r2.validate_env()
    assert "R2_BUCKET" in str(excinfo.value)


@mock_aws
def test_get_object_returns_body_bytes(r2_env: dict[str, str]) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="yasli-snapshots")
    s3.put_object(
        Bucket="yasli-snapshots",
        Key="snapshots/varna/latest.json",
        Body=b'{"hello":"world"}',
    )
    got = r2.get_object("snapshots/varna/latest.json", client=s3)
    assert got == b'{"hello":"world"}'


@mock_aws
def test_get_object_propagates_missing_key_error(r2_env: dict[str, str]) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="yasli-snapshots")
    with pytest.raises(ClientError) as excinfo:
        r2.get_object("snapshots/varna/latest.json", client=s3)
    assert excinfo.value.response["Error"]["Code"] in {"NoSuchKey", "404"}
