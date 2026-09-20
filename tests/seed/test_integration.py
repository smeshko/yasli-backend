"""The whole seed, once, against a bare Postgres.

This is the test that would have caught the failure YAS-21 describes: a
seed that exits 0 having stamped no districts. It starts from an empty
database with no schema, runs every step, and asserts the row counts a
production-like local database has to carry.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine, text

from yasli import db as db_module
from yasli.seed import runner


@pytest.fixture(scope="module")
def summary(seeded: tuple[runner.SeedSummary, Engine]) -> runner.SeedSummary:
    return seeded[0]


@pytest.fixture(scope="module")
def engine(seeded: tuple[runner.SeedSummary, Engine]) -> Engine:
    return seeded[1]


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_seed_runs_every_step(summary: runner.SeedSummary) -> None:
    assert [s.name for s in summary.steps] == [
        "migrate",
        "grao",
        "ingest",
        "legacy-institutions",
        "institution-locations",
        "restamp-districts",
    ]


def test_seed_reports_the_snapshot_timestamp(summary: runner.SeedSummary) -> None:
    assert summary.scraped_at is not None


def test_institutions_reach_95(engine: Engine) -> None:
    assert _count(engine, "institutions") == 95


def test_streets_and_addresses_match_the_snapshot(engine: Engine) -> None:
    assert _count(engine, "streets") == 2289
    assert _count(engine, "addresses") == 49800


def test_grao_addresses_are_loaded(engine: Engine) -> None:
    assert _count(engine, "grao_addresses") == 47579


def test_institution_locations_are_loaded(engine: Engine) -> None:
    assert _count(engine, "institution_locations") == 94


def test_in_city_addresses_are_district_stamped(engine: Engine) -> None:
    """The headline defect: ГР.ВАРНА districts must not be NULL wholesale.

    Judged on *in-city* addresses only, and against the ~2% staleness
    threshold `docs/OPERATIONS.md` documents. The villages are excluded on
    purpose: the KADS file covers Varna city, so a village address has no
    район to be stamped with and counting it would measure ГРАО's scope
    rather than the seed's health.
    """
    with engine.connect() as conn:
        unstamped, total = conn.execute(
            text(
                "SELECT count(*) FILTER (WHERE a.district_code IS NULL), count(*) "
                "FROM addresses a JOIN settlements s ON s.code = a.settlement_code "
                "WHERE s.name = 'ГР.ВАРНА'"
            )
        ).one()
    assert total > 0
    assert unstamped < total * 0.02, (
        f"{unstamped}/{total} in-city addresses unstamped — ГРАО probably ran "
        "after ingest, or the committed archive is stale"
    )


def test_village_addresses_are_expected_to_be_unstamped(engine: Engine) -> None:
    """The other half of the above: villages are outside the KADS file."""
    with engine.connect() as conn:
        stamped_villages = conn.execute(
            text(
                "SELECT count(*) FROM addresses a "
                "JOIN settlements s ON s.code = a.settlement_code "
                "WHERE s.name <> 'ГР.ВАРНА' AND a.district_code IS NOT NULL"
            )
        ).scalar_one()
    assert stamped_villages == 0


def test_seed_is_rerunnable_over_a_seeded_database(
    engine: Engine, bare_postgres_url: str
) -> None:
    """D6: no gate in front of the command; it simply runs again."""
    os.environ["DATABASE_URL"] = bare_postgres_url
    db_module._engine = None  # type: ignore[attr-defined]
    db_module._SessionLocal = None  # type: ignore[attr-defined]
    second = runner.run_seed()
    assert [s.name for s in second.steps] == [
        s.name for s in runner.build_steps()
    ]
    assert _count(engine, "institutions") == 95
