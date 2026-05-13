"""Pipeline integration tests against a Postgres testcontainer + moto-stubbed R2."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from yasli.ingest import pipeline
from yasli.models import Address, Institution, Street, address_institutions

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "snapshot_v2_minimal.json"
V1_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "snapshot_v1_minimal.json"
BUCKET = "yasli-snapshots"
KEY = "snapshots/varna/latest.json"

# The minimal fixture has 4 institutions, 5 streets, 8 distinct addresses,
# and 9 coverage edges (one address — VV 85 — is covered by both the
# kindergarten 1004 and the preschool 1003). The standalone nursery has no
# catchment rows.
EXPECTED_INSTITUTIONS = 4
EXPECTED_STREETS = 5
EXPECTED_ADDRESSES = 8
EXPECTED_EDGES = 9
EXPECTED_ADDRESS_NULL = 1


@pytest.fixture
def snapshot_dict() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def r2_env(monkeypatch) -> dict[str, str]:
    env = {
        "R2_ACCOUNT_ID": "acc",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET": BUCKET,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env


def _put_snapshot(s3: Any, payload: dict[str, Any]) -> None:
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(
        Bucket=BUCKET,
        Key=KEY,
        Body=json.dumps(payload).encode("utf-8"),
    )


def _count(session: Session, table: Any) -> int:
    return int(session.scalar(select(text("count(*)")).select_from(table)))


@mock_aws
def test_first_run_loads_all(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)

    summary = pipeline.run(r2_client=s3)

    with Session(engine) as s:
        assert _count(s, Institution) == EXPECTED_INSTITUTIONS
        assert _count(s, Street) == EXPECTED_STREETS
        assert _count(s, Address) == EXPECTED_ADDRESSES
        assert _count(s, address_institutions) == EXPECTED_EDGES

    assert summary.institutions.inserted == EXPECTED_INSTITUTIONS
    assert summary.streets.inserted == EXPECTED_STREETS
    assert summary.addresses.inserted == EXPECTED_ADDRESSES
    assert summary.address_institutions.inserted == EXPECTED_EDGES
    assert summary.skipped_rows == 0
    assert summary.address_null == EXPECTED_ADDRESS_NULL
    assert summary.institutions_disappeared == 0


@mock_aws
def test_institution_metadata_is_persisted(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)

    pipeline.run(r2_client=s3)

    with Session(engine) as s:
        nursery = s.execute(
            select(Institution).where(Institution.external_id == "1001")
        ).scalar_one()
        assert nursery.kind == "nursery"
        assert nursery.address == "ул. Морска 1"
        assert nursery.district_code == "01"
        assert nursery.has_infant_group is False

        kindergarten = s.execute(
            select(Institution).where(Institution.external_id == "1002")
        ).scalar_one()
        assert kindergarten.address == "ул. Слънце 2"
        assert kindergarten.district_code is None
        assert kindergarten.has_infant_group is True

        null_address = s.execute(
            select(Institution).where(Institution.external_id == "1003")
        ).scalar_one()
        assert null_address.address is None


@mock_aws
def test_idempotent_second_run(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)

    pipeline.run(r2_client=s3)

    with Session(engine) as s:
        first_address_pks = {
            (r.street_id, r.number_int, r.number_suffix, r.entrance): r.id
            for r in s.execute(select(Address)).scalars()
        }
        stamped_kindergarten = s.execute(
            select(Institution).where(
                Institution.external_id == "1002",
                Institution.kind == "kindergarten",
            )
        ).scalar_one()
        stamped_kindergarten.district_code = "02"
        s.commit()
        first_edges = {
            (row.address_id, row.institution_id)
            for row in s.execute(
                select(
                    address_institutions.c.address_id,
                    address_institutions.c.institution_id,
                )
            )
        }

    summary2 = pipeline.run(r2_client=s3)

    with Session(engine) as s:
        second_address_pks = {
            (r.street_id, r.number_int, r.number_suffix, r.entrance): r.id
            for r in s.execute(select(Address)).scalars()
        }
        second_edges = {
            (row.address_id, row.institution_id)
            for row in s.execute(
                select(
                    address_institutions.c.address_id,
                    address_institutions.c.institution_id,
                )
            )
        }
        assert _count(s, Institution) == EXPECTED_INSTITUTIONS
        assert _count(s, Street) == EXPECTED_STREETS
        assert _count(s, Address) == EXPECTED_ADDRESSES
        assert _count(s, address_institutions) == EXPECTED_EDGES
        preserved = s.execute(
            select(Institution).where(
                Institution.external_id == "1002",
                Institution.kind == "kindergarten",
            )
        ).scalar_one()
        assert preserved.district_code == "02"

    # Same composite keys → same surrogate ids on the rows.
    assert first_address_pks == second_address_pks
    # Junction edges: same set of (address_id, institution_id) pairs.
    assert first_edges == second_edges
    assert summary2.institutions.inserted == 0
    assert summary2.streets.inserted == 0
    assert summary2.addresses.inserted == 0
    assert summary2.addresses.unchanged == EXPECTED_ADDRESSES
    assert summary2.address_institutions.inserted == 0
    assert summary2.address_institutions.unchanged == EXPECTED_EDGES
    assert summary2.address_null == EXPECTED_ADDRESS_NULL


@mock_aws
def test_updated_institution_name(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)
    pipeline.run(r2_client=s3)

    with Session(engine) as s:
        original = s.execute(
            select(Institution).where(Institution.external_id == "1001")
        ).scalar_one()
        original_id = original.id
        assert original.name == "ДЯ Море"

    bumped = deepcopy(snapshot_dict)
    bumped["scraped_at"] = "2026-05-11T01:00:00Z"
    bumped["institutions"][0]["name"] = "ДЯ Море (renamed)"
    s3.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps(bumped).encode("utf-8")
    )

    summary = pipeline.run(r2_client=s3)

    with Session(engine) as s:
        renamed = s.execute(
            select(Institution).where(Institution.external_id == "1001")
        ).scalar_one()
        assert renamed.id == original_id
        assert renamed.name == "ДЯ Море (renamed)"

    assert summary.institutions.updated >= 1


@mock_aws
def test_updated_institution_metadata_counts_updated(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)
    pipeline.run(r2_client=s3)

    bumped = deepcopy(snapshot_dict)
    bumped["scraped_at"] = "2026-05-11T01:00:00Z"
    bumped["institutions"][1]["address"] = "ул. Слънце 22"
    bumped["institutions"][1]["has_infant_group"] = False
    s3.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps(bumped).encode("utf-8")
    )

    summary = pipeline.run(r2_client=s3)

    with Session(engine) as s:
        row = s.execute(
            select(Institution).where(Institution.external_id == "1002")
        ).scalar_one()
        assert row.address == "ул. Слънце 22"
        assert row.has_infant_group is False

    assert summary.institutions.updated >= 1


@mock_aws
def test_disappeared_institution(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)
    pipeline.run(r2_client=s3)

    with Session(engine) as s:
        gone = s.execute(
            select(Institution).where(Institution.external_id == "1003")
        ).scalar_one()
        gone_seen_at = gone.last_seen_at
        # 1003 has 5 entries in the fixture; junction has 5 edges for it.
        survivor_edge_count = s.scalar(
            select(text("count(*)"))
            .select_from(address_institutions)
            .where(address_institutions.c.institution_id == gone.id)
        )
        assert survivor_edge_count == 5

    bumped = deepcopy(snapshot_dict)
    bumped["scraped_at"] = "2026-05-11T01:00:00Z"
    bumped["institutions"] = [
        i for i in bumped["institutions"] if i["external_id"] != "1003"
    ]
    s3.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps(bumped).encode("utf-8")
    )

    summary = pipeline.run(r2_client=s3)

    with Session(engine) as s:
        survivor = s.execute(
            select(Institution).where(Institution.external_id == "1003")
        ).scalar_one()
        assert survivor.last_seen_at == gone_seen_at  # untouched

        edge_count = s.scalar(
            select(text("count(*)"))
            .select_from(address_institutions)
            .where(address_institutions.c.institution_id == survivor.id)
        )
        # Junction rows aren't reaped on disappearance — still 5 edges.
        assert edge_count == 5

    assert summary.institutions_disappeared == 1


@mock_aws
def test_skipped_rows_do_not_abort(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    bad = deepcopy(snapshot_dict)
    bad["institutions"][0]["address_entries"].append(
        {"street": "ГР.ВАРНА УЛ.ТЕСТ", "number": "TOTALLY-NOT-A-NUMBER"}
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, bad)

    summary = pipeline.run(r2_client=s3)

    assert summary.skipped_rows == 1
    with Session(engine) as s:
        # The bad row's street ("ГР.ВАРНА УЛ.ТЕСТ") was never inserted —
        # the row was skipped before street planning consumed it.
        bad_street = s.execute(
            select(Street).where(Street.raw_name == "ГР.ВАРНА УЛ.ТЕСТ")
        ).first()
        assert bad_street is None
        # Other rows present
        assert _count(s, Address) == EXPECTED_ADDRESSES
        assert _count(s, address_institutions) == EXPECTED_EDGES


@mock_aws
def test_invalid_schema_aborts(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    bad = deepcopy(snapshot_dict)
    del bad["schema_version"]
    s3.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps(bad).encode("utf-8")
    )

    with pytest.raises(Exception):
        pipeline.run(r2_client=s3)

    with Session(engine) as s:
        assert _count(s, Institution) == 0


@mock_aws
def test_unknown_schema_version_aborts(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    bad = deepcopy(snapshot_dict)
    bad["schema_version"] = 3
    s3.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps(bad).encode("utf-8")
    )

    with pytest.raises(pipeline.UnsupportedSnapshotVersion, match="schema_version"):
        pipeline.run(r2_client=s3)

    with Session(engine) as s:
        assert _count(s, Institution) == 0


@mock_aws
def test_v1_schema_version_aborts(engine: Engine, r2_env: dict[str, str]) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    payload = json.loads(V1_FIXTURE_PATH.read_text(encoding="utf-8"))
    s3.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps(payload).encode("utf-8")
    )

    with pytest.raises(pipeline.UnsupportedSnapshotVersion, match="expected 2"):
        pipeline.run(r2_client=s3)

    with Session(engine) as s:
        assert _count(s, Institution) == 0


@mock_aws
def test_db_error_rolls_back(
    engine: Engine,
    r2_env: dict[str, str],
    snapshot_dict: dict[str, Any],
    monkeypatch,
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)

    def explode(*args, **kwargs):
        raise IntegrityError("boom", params=None, orig=Exception("forced"))

    monkeypatch.setattr(pipeline, "_insert_address_institutions", explode)

    with pytest.raises(IntegrityError):
        pipeline.run(r2_client=s3)

    with Session(engine) as s:
        # Earlier institution / street / address upserts must have rolled back.
        assert _count(s, Institution) == 0
        assert _count(s, Street) == 0
        assert _count(s, Address) == 0
        assert _count(s, address_institutions) == 0


@mock_aws
def test_search_norm_populated(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)
    pipeline.run(r2_client=s3)

    with Session(engine) as s:
        rows = s.execute(select(Street)).scalars().all()
        assert rows
        for street in rows:
            assert street.search_norm
            assert street.search_norm == street.search_norm.lower()


@mock_aws
def test_last_seen_at_stamped(
    engine: Engine, r2_env: dict[str, str], snapshot_dict: dict[str, Any]
) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    _put_snapshot(s3, snapshot_dict)
    summary = pipeline.run(r2_client=s3)

    with Session(engine) as s:
        rows = s.execute(select(Institution)).scalars().all()
        for inst in rows:
            assert inst.last_seen_at == summary.scraped_at


@mock_aws
def test_chunked_inserts_handle_large_batch(
    engine: Engine, r2_env: dict[str, str]
) -> None:
    """Synthesise 10,000 distinct addresses / 20,000 coverage edges and
    drive the upsert phase directly. Addresses-batch alone is 4 params/row
    × 10,000 = 40,000 params and the junction batch is 2 params/row ×
    20,000 = 40,000 params; both exceed Postgres' 65,535-param limit
    when sent in one statement and prove that chunking works.
    """
    address_count = 10_000
    edge_count = 20_000

    institutions = [
        {
            "external_id": f"sx-{i}",
            "name": f"Inst {i}",
            "kind": "kindergarten",
            "source_url": f"https://example.test/inst/{i}",
            "address": f"ул. Синтетична {i}",
            "district_code": None,
            "has_infant_group": False,
            "last_seen_at": datetime(2026, 5, 4, tzinfo=timezone.utc),
        }
        for i in range(2)
    ]
    streets = [
        {
            "city": "ГР.ВАРНА",
            "raw_name": f"ГР.ВАРНА УЛ.СИНТЕТИЧНА-{s}",
            "street_part": f"СИНТЕТИЧНА-{s}",
            "type_marker": None,
            "search_norm": f"гр.варна ул.синтетична-{s}",
        }
        for s in range(2)
    ]
    addresses = [
        {
            "street_raw_name": streets[i % 2]["raw_name"],
            "number_int": 1 + (i // 2),
            "number_suffix": None,
            "entrance": None,
        }
        for i in range(address_count)
    ]
    coverage_edges: list[
        tuple[
            tuple[str, int, str | None, str | None],
            tuple[str, str],
        ]
    ] = []
    # 10_000 addresses × 2 institutions = 20_000 distinct edges.
    for addr in addresses:
        addr_key = (
            addr["street_raw_name"],
            addr["number_int"],
            addr["number_suffix"],
            addr["entrance"],
        )
        for inst in institutions:
            coverage_edges.append(
                (addr_key, (inst["external_id"], inst["kind"]))
            )
    assert len(coverage_edges) == edge_count

    snapshot_payload = {
        "schema_version": 2,
        "scraped_at": "2026-05-04T01:00:00Z",
        "city": "varna",
        "institutions": [],
    }
    from yasli.snapshot_contract import Snapshot

    plan = pipeline._IngestPlan(
        snapshot=Snapshot.model_validate(snapshot_payload),
        institutions=institutions,
        streets=streets,
        addresses=addresses,
        coverage_edges=coverage_edges,
        skipped_rows=0,
        address_null=0,
    )

    with Session(engine) as session:
        with session.begin():
            inst_ids, _ = pipeline._upsert_institutions(session, plan)
            street_ids, _ = pipeline._upsert_streets(session, plan)
            address_ids, addr_counts = pipeline._upsert_addresses(
                session, plan, street_ids
            )
            edge_counts = pipeline._insert_address_institutions(
                session, plan, inst_ids, address_ids
            )

    assert addr_counts.inserted == address_count
    assert edge_counts.inserted == edge_count

    with Session(engine) as s:
        assert _count(s, Address) == address_count
        assert _count(s, address_institutions) == edge_count
