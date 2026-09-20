"""`yasli.seed.verify` — the claim that this database is production-like.

Every failure case is staged inside a transaction that is rolled back, so
the one seeded database the session shares stays clean. That is also the
honest shape for these tests: the defects being checked (a stale extra
institution, a leftover catchment edge) are exactly what a *dirty*
database looks like, and nothing here should leave one behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, insert, select, text
from sqlalchemy.orm import Session

from yasli.models import Address, Institution, address_institutions
from yasli.seed import verify


@pytest.fixture
def session(seeded: tuple[object, Engine]) -> Iterator[Session]:
    """A session whose work is always rolled back."""
    _, engine = seeded
    with Session(engine) as s:
        try:
            yield s
        finally:
            s.rollback()


@pytest.fixture(scope="module")
def artifacts() -> verify.Artifacts:
    return verify.Artifacts.load()


# --- the happy path --------------------------------------------------------


def test_a_fully_seeded_database_passes(session: Session) -> None:
    result = verify.run_checks(session)
    assert result.ok, verify.format_result(result)
    assert not result.failures


def test_every_check_reports_a_line(session: Session) -> None:
    result = verify.run_checks(session)
    assert len(result.checks) == len(verify.CHECKS)
    rendered = verify.format_result(result)
    for check in result.checks:
        assert check.name in rendered


def test_routing_case_reproduces_the_ticket(
    session: Session, artifacts: verify.Artifacts
) -> None:
    """YAS-21's address must return all three kinds in район 02."""
    check = verify.check_routing_case(session, artifacts)
    assert check.ok, check.detail
    assert "district=02" in check.detail
    assert "nurseries=4" in check.detail
    assert "kindergartens=4" in check.detail
    assert "preschools=2" in check.detail


# --- the institution set ---------------------------------------------------


def test_an_institution_outside_the_artifacts_fails_and_is_named(
    session: Session, artifacts: verify.Artifacts
) -> None:
    """A stale nursery carrying a район shows up in /api/match."""
    session.add(
        Institution(
            external_id="9999",
            name="ДЯ № 999 (stale)",
            kind="nursery",
            source_url="https://example.invalid/stale",
            district_code="02",
            has_infant_group=True,
            last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    session.flush()

    check = verify.check_institution_set(session, artifacts)
    assert not check.ok
    assert any("nursery/9999" in item for item in check.items)
    assert "/api/match" in check.detail
    assert check.remedy is not None and "db-reset" in check.remedy


def test_a_missing_institution_fails_and_is_named(
    session: Session, artifacts: verify.Artifacts
) -> None:
    session.execute(
        delete(Institution).where(
            Institution.kind == "nursery", Institution.external_id == "39"
        )
    )
    session.flush()

    check = verify.check_institution_set(session, artifacts)
    assert not check.ok
    assert any("missing nursery/39" in item for item in check.items)


def test_the_expectation_tracks_the_committed_fixture(
    session: Session, artifacts: verify.Artifacts
) -> None:
    """One fixture row fewer shifts the expectation, with no code change."""
    trimmed = verify.Artifacts(
        snapshot=artifacts.snapshot, legacy=artifacts.legacy[:-1]
    )
    assert len(trimmed.expected_institution_keys) == (
        len(artifacts.expected_institution_keys) - 1
    )
    # The database still holds the row the trimmed fixture no longer claims,
    # so it is now an extra rather than a silent pass.
    check = verify.check_institution_set(session, trimmed)
    assert not check.ok
    assert check.items


# --- catchment edges -------------------------------------------------------


def test_an_edge_outside_the_snapshot_fails_and_is_named(
    session: Session, artifacts: verify.Artifacts
) -> None:
    """The institution set being right is not sufficient."""
    institution_id = session.execute(
        select(Institution.id).where(Institution.kind == "kindergarten").limit(1)
    ).scalar_one()
    address_id = session.execute(
        select(Address.id).where(
            ~select(address_institutions.c.address_id)
            .where(address_institutions.c.address_id == Address.id)
            .where(address_institutions.c.institution_id == institution_id)
            .exists()
        )
        .limit(1)
    ).scalar_one()
    session.execute(
        insert(address_institutions).values(
            address_id=address_id, institution_id=institution_id
        )
    )
    session.flush()

    check = verify.check_catchment_edges(session, artifacts)
    assert not check.ok
    assert "beyond it" in check.detail
    assert any(item.startswith("extra ") for item in check.items)


def test_a_missing_edge_fails(
    session: Session, artifacts: verify.Artifacts
) -> None:
    row = session.execute(
        select(
            address_institutions.c.address_id,
            address_institutions.c.institution_id,
        ).limit(1)
    ).one()
    session.execute(
        delete(address_institutions)
        .where(address_institutions.c.address_id == row.address_id)
        .where(address_institutions.c.institution_id == row.institution_id)
    )
    session.flush()

    check = verify.check_catchment_edges(session, artifacts)
    assert not check.ok
    assert "1 missing" in check.detail


# --- districts -------------------------------------------------------------


def test_an_empty_grao_table_fails(
    session: Session, artifacts: verify.Artifacts
) -> None:
    session.execute(text("DELETE FROM grao_addresses"))
    session.flush()
    check = verify.check_grao_addresses(session, artifacts)
    assert not check.ok
    assert check.remedy is not None and "grao" in check.remedy


def test_unstamped_in_city_addresses_fail(
    session: Session, artifacts: verify.Artifacts
) -> None:
    session.execute(text("UPDATE addresses SET district_code = NULL"))
    session.flush()
    check = verify.check_address_districts(session, artifacts)
    assert not check.ok
    assert "100.00%" in check.detail


def test_a_valid_but_wrong_district_is_caught(
    session: Session, artifacts: verify.Artifacts
) -> None:
    """Coverage and code membership cannot tell right from wrong."""
    street_raw, number, entrance, expected = verify.ROUTING_CASE
    assert expected == "02"
    session.execute(
        text(
            "UPDATE addresses SET district_code = '05' WHERE id IN ("
            " SELECT a.id FROM addresses a JOIN streets s ON s.id = a.street_id"
            " WHERE s.raw_name = :raw AND a.number_int = :num AND a.entrance = :ent)"
        ),
        {"raw": street_raw, "num": number, "ent": entrance},
    )
    session.flush()

    check = verify.check_known_districts(session, artifacts)
    assert not check.ok
    assert any("expected 02" in item for item in check.items)


def test_a_nursery_without_a_district_outside_the_fixture_fails(
    session: Session, artifacts: verify.Artifacts
) -> None:
    session.execute(
        text(
            "UPDATE institutions SET district_code = NULL "
            "WHERE kind = 'nursery' AND external_id = "
            "(SELECT external_id FROM institutions WHERE kind = 'nursery' "
            " AND district_code IS NOT NULL LIMIT 1)"
        )
    )
    session.flush()
    check = verify.check_institution_districts(session, artifacts)
    assert not check.ok
    assert "route nowhere" in check.detail


def test_preschools_without_a_district_are_listed_not_failed(
    session: Session, artifacts: verify.Artifacts
) -> None:
    """They route by catchment; production carries the same handful."""
    check = verify.check_institution_districts(session, artifacts)
    assert check.ok
    assert any("preschool/" in item for item in check.items)


# --- failures collect, they do not short-circuit ---------------------------


def test_all_failures_are_collected(
    session: Session, artifacts: verify.Artifacts
) -> None:
    session.execute(text("DELETE FROM grao_addresses"))
    session.execute(text("UPDATE addresses SET district_code = NULL"))
    session.flush()

    result = verify.run_checks(session, artifacts)
    failed = {c.name for c in result.failures}
    assert {"grao-addresses", "address-districts"} <= failed
    assert len(result.failures) > 1


def test_every_failure_names_a_remedy(
    session: Session, artifacts: verify.Artifacts
) -> None:
    session.execute(text("DELETE FROM grao_addresses"))
    session.flush()
    result = verify.run_checks(session, artifacts)
    assert all(c.remedy for c in result.failures)


# --- the stale-snapshot warning --------------------------------------------


def test_a_stale_snapshot_warns_without_failing(
    session: Session, artifacts: verify.Artifacts
) -> None:
    stale = dict(artifacts.snapshot)
    stale["scraped_at"] = (
        datetime.now(UTC) - timedelta(days=120)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    aged = verify.Artifacts(snapshot=stale, legacy=artifacts.legacy)

    check = verify.check_snapshot_freshness(session, aged)
    assert check.warning
    assert not check.ok
    assert "120 days old" in check.detail

    result = verify.run_checks(session, aged)
    assert result.ok, "a stale snapshot must warn, not fail"
    assert result.warnings


def test_a_fresh_snapshot_does_not_warn(
    session: Session, artifacts: verify.Artifacts
) -> None:
    check = verify.check_snapshot_freshness(session, artifacts)
    assert check.ok
    assert not check.warning
