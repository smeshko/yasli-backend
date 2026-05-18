"""Tests for the read-only match data validation helper and CLI."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yasli import db as db_module
from yasli.ingest import __main__ as ingest_main
from yasli.ingest.match_data_validation import (
    format_match_data_validation_result,
    validate_match_data,
)
from yasli.models import (
    Address,
    Base,
    Institution,
    Settlement,
    Street,
    address_institutions,
)

NOW = datetime(2026, 5, 17, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db_module.set_engine(engine)
    with Session(engine) as s:
        s.execute(text("PRAGMA ignore_check_constraints = ON"))
        yield s
    engine.dispose()
    db_module._engine = None  # type: ignore[attr-defined]
    db_module._SessionLocal = None  # type: ignore[attr-defined]


def _seed_clean(
    session: Session,
    *,
    has_infant_group: bool = True,
    kindergarten_edges: bool = True,
    preschool_edges: bool = True,
) -> None:
    session.add(
        Street(
            id=1,
            city="VARNA",
            raw_name="ul. Test",
            street_part="Test",
            type_marker="ul.",
            search_norm="test",
        )
    )
    session.add_all(
        [
            Settlement(code="10135", name="VARNA", locality_type="city"),
            Settlement(code="35701", name="KAMENAR", locality_type="village"),
        ]
    )
    session.add_all(
        [
            Address(
                id=1,
                street_id=1,
                number_int=1,
                district_code="01",
                settlement_code="10135",
            ),
            Address(
                id=2,
                street_id=1,
                number_int=2,
                district_code=None,
                settlement_code="35701",
            ),
        ]
    )
    session.add_all(
        [
            Institution(
                id=1,
                external_id="N1",
                name="Nursery",
                kind="nursery",
                source_url="https://example.test/n1",
                district_code="01",
                last_seen_at=NOW,
            ),
            Institution(
                id=2,
                external_id="K1",
                name="Kindergarten",
                kind="kindergarten",
                source_url="https://example.test/k1",
                district_code="01",
                has_infant_group=has_infant_group,
                last_seen_at=NOW,
            ),
            Institution(
                id=3,
                external_id="P1",
                name="Preschool",
                kind="preschool",
                source_url="https://example.test/p1",
                district_code="02",
                last_seen_at=NOW,
            ),
        ]
    )
    edges = []
    if kindergarten_edges:
        edges.append({"address_id": 1, "institution_id": 2})
    if preschool_edges:
        edges.append({"address_id": 1, "institution_id": 3})
    if edges:
        session.execute(insert(address_institutions), edges)
    session.commit()


def _add_address(
    session: Session,
    *,
    id: int,
    district_code: str | None,
    settlement_code: str | None,
) -> None:
    session.add(
        Address(
            id=id,
            street_id=1,
            number_int=id,
            district_code=district_code,
            settlement_code=settlement_code,
        )
    )


def _add_institution(
    session: Session,
    *,
    id: int,
    kind: str,
    district_code: str | None,
) -> None:
    session.add(
        Institution(
            id=id,
            external_id=f"X{id}",
            name=f"Institution {id}",
            kind=kind,
            source_url=f"https://example.test/{id}",
            district_code=district_code,
            last_seen_at=NOW,
        )
    )


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = ingest_main.main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def test_clean_fixture_returns_structured_success(session: Session) -> None:
    _seed_clean(session)

    result = validate_match_data(session)
    formatted = format_match_data_validation_result(result)

    assert result.has_hard_failures is False
    assert result.hard_failures.total == 0
    assert result.warnings.total == 0
    assert result.addresses.total == 2
    assert result.addresses.district_known == 1
    assert result.addresses.settlement_known_no_district == 1
    assert result.settlements.city == 1
    assert result.settlements.village == 1
    assert result.institutions.nursery == 1
    assert result.institutions.kindergarten == 1
    assert result.institutions.preschool == 1
    assert result.institutions.infant_group_kindergartens == 1
    assert result.coverage_edges.kindergarten == 1
    assert result.coverage_edges.preschool == 1
    assert result.coverage_edges.nursery == 0
    assert formatted.startswith("match data validation ok")
    assert "failures={" not in formatted


@pytest.mark.parametrize(
    ("case", "failure_field"),
    [
        ("no_settlement_context", "no_settlement_no_district_addresses"),
        ("unknown_settlement_code", "unknown_settlement_codes"),
        ("nursery_without_district", "nursery_without_district"),
        ("nursery_coverage_edge", "nursery_coverage_edges"),
        ("invalid_institution_kind", "invalid_institution_kinds"),
        ("invalid_address_district_code", "invalid_address_district_codes"),
    ],
)
def test_hard_failures_are_reported(
    session: Session,
    case: str,
    failure_field: str,
) -> None:
    _seed_clean(session)
    if case == "no_settlement_context":
        _add_address(session, id=10, district_code=None, settlement_code=None)
    elif case == "unknown_settlement_code":
        _add_address(session, id=10, district_code="01", settlement_code="99999")
    elif case == "nursery_without_district":
        _add_institution(session, id=10, kind="nursery", district_code=None)
    elif case == "nursery_coverage_edge":
        session.execute(
            insert(address_institutions),
            [{"address_id": 1, "institution_id": 1}],
        )
    elif case == "invalid_institution_kind":
        _add_institution(session, id=10, kind="infant", district_code="01")
    elif case == "invalid_address_district_code":
        _add_address(session, id=10, district_code="99", settlement_code="10135")
    session.commit()

    result = validate_match_data(session)
    formatted = format_match_data_validation_result(result)

    assert result.has_hard_failures is True
    assert getattr(result.hard_failures, failure_field) == 1
    assert formatted.startswith("match data validation failed")
    assert "failures={" in formatted
    assert f"{failure_field}:1" in formatted


@pytest.mark.parametrize(
    ("case", "warning_field"),
    [
        ("varna_city_without_district", "varna_city_without_district"),
        ("zero_infant_group_kindergartens", "zero_infant_group_kindergartens"),
        ("zero_kindergarten_edges", "zero_kindergarten_edges"),
        ("zero_preschool_edges", "zero_preschool_edges"),
    ],
)
def test_warning_only_cases_do_not_create_hard_failures(
    session: Session,
    case: str,
    warning_field: str,
) -> None:
    if case == "zero_infant_group_kindergartens":
        _seed_clean(session, has_infant_group=False)
    elif case == "zero_kindergarten_edges":
        _seed_clean(session, kindergarten_edges=False)
    elif case == "zero_preschool_edges":
        _seed_clean(session, preschool_edges=False)
    else:
        _seed_clean(session)
        _add_address(session, id=10, district_code=None, settlement_code="10135")
        session.commit()

    result = validate_match_data(session)

    assert result.has_hard_failures is False
    assert getattr(result.warnings, warning_field) == 1
    assert result.hard_failures.total == 0


def test_cli_success_uses_configured_database_without_r2(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    _seed_clean(session)
    for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(key, raising=False)

    rc, stdout, stderr = _run_main(["validate-match-data"])

    assert rc == 0
    assert stderr == ""
    assert stdout.startswith("match data validation ok\n")
    for block in ("addresses={", "settlements={", "institutions={", "coverage_edges={", "warnings={"):
        assert block in stdout


def test_cli_warning_only_exits_zero(session: Session) -> None:
    _seed_clean(session, has_infant_group=False)

    rc, stdout, stderr = _run_main(["validate-match-data"])

    assert rc == 0
    assert stderr == ""
    assert stdout.startswith("match data validation ok\n")
    assert "zero_infant_group_kindergartens:1" in stdout
    assert "failures={" not in stdout


def test_cli_hard_failures_exit_non_zero(session: Session) -> None:
    _seed_clean(session)
    _add_address(session, id=10, district_code=None, settlement_code=None)
    session.commit()

    rc, stdout, stderr = _run_main(["validate-match-data"])

    assert rc == 1
    assert stderr == ""
    assert stdout.startswith("match data validation failed\n")
    assert "no_settlement_no_district_addresses:1" in stdout


def test_cli_missing_database_url_returns_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")

    rc, stdout, stderr = _run_main(["validate-match-data"])

    assert rc == 2
    assert stdout == ""
    assert "DATABASE_URL" in stderr


def test_cli_database_error_returns_5(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken_get_engine():
        raise OperationalError("SELECT 1", {}, Exception("boom"))

    monkeypatch.setattr(ingest_main, "get_engine", _broken_get_engine)

    rc, stdout, stderr = _run_main(["validate-match-data"])

    assert rc == 5
    assert stdout == ""
    assert "database error" in stderr
