"""Step list, ordering and failure semantics for the seed.

**Order is load-bearing and non-obvious.** ГРАО must precede ingest,
because :func:`yasli.ingest.pipeline.run` ends with the *gated*
``stamp_*_unmatched`` passes, which can only stamp what ``grao_addresses``
already holds. Running ingest first produces a seed that exits 0 with no
districts — precisely the failure YAS-21 was filed about, so
``tests/seed/test_runner.py`` asserts the order rather than trusting this
docstring.

The closing ``restamp-districts`` runs the *non-gated* passes, re-deriving
every kindergarten and preschool district against the full ГРАО table. On
a clean seed it is close to a no-op — ingest's gated passes already left
nothing NULL. It earns its place on a re-seed, where a previous ГРАО cycle
may have stamped a район differently. It does **not** stamp the legacy
nurseries: both passes exclude ``kind='nursery'`` because nursery
districts are API-sourced.

Each step owns its own transaction, so a failure leaves the steps before
it committed — the same state the individual commands would have produced
if run by hand up to that point. What the seed owes in exchange is saying
loudly where it stopped, which is what :class:`SeedStepFailed` carries and
what ``verify`` (a separate command) re-checks from the database.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest import grao_loader, institution_locations_loader, pipeline
from yasli.ingest import legacy_institutions_loader as legacy_loader
from yasli.ingest.__main__ import restamp_districts_in_session
from yasli.ingest.municipality import REPO_ROOT

ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# Exit codes follow the `yasli.ingest` convention the rest of the project
# uses, so a seed failure reads the same as the failure of the step it
# wraps: 2 config, 3 data, 4 fetch/precondition, 5 database.
EXIT_CONFIG = 2
EXIT_DATA = 3
EXIT_PRECONDITION = 4
EXIT_DATABASE = 5

_EXIT_CODES: tuple[tuple[type[BaseException], int], ...] = (
    (grao_loader.ArchiveError, EXIT_DATA),
    (pipeline.SnapshotFileError, EXIT_DATA),
    (pipeline.UnsupportedSnapshotVersion, EXIT_DATA),
    (legacy_loader.LegacyFixtureError, EXIT_DATA),
    (institution_locations_loader.LocationRowError, EXIT_DATA),
    (ValidationError, EXIT_DATA),
    (json.JSONDecodeError, EXIT_DATA),
    (institution_locations_loader.UnmatchedInstitution, EXIT_PRECONDITION),
    (institution_locations_loader.IncompleteFile, EXIT_PRECONDITION),
    (BotoCoreError, EXIT_PRECONDITION),
    (ClientError, EXIT_PRECONDITION),
    (SQLAlchemyError, EXIT_DATABASE),
    # ValueError last: several of the above subclass it, and Settings()
    # raises a bare one for a missing DATABASE_URL.
    (ValueError, EXIT_CONFIG),
)


def exit_code_for(exc: BaseException) -> int:
    """Map an exception raised by a step onto the CLI's exit code."""
    for kind, code in _EXIT_CODES:
        if isinstance(exc, kind):
            return code
    return EXIT_DATABASE


@dataclass
class SeedContext:
    """What a step may carry forward to the ones after it."""

    scraped_at: datetime | None = None


@dataclass(frozen=True)
class Step:
    """One named unit of the seed. ``run`` returns its summary detail."""

    name: str
    run: Callable[[SeedContext], str]


@dataclass
class StepResult:
    name: str
    detail: str
    elapsed_ms: int


@dataclass
class SeedSummary:
    steps: list[StepResult] = field(default_factory=list)
    scraped_at: datetime | None = None
    elapsed_ms: int = 0


class SeedStepFailed(Exception):
    """A step failed. Names the step so the operator knows where it stopped."""

    def __init__(self, step: str, exit_code: int, cause: BaseException) -> None:
        super().__init__(f"step {step!r} failed: {cause}")
        self.step = step
        self.exit_code = exit_code
        self.cause = cause


# --- the steps -------------------------------------------------------------


def _step_migrate(ctx: SeedContext) -> str:
    """`alembic upgrade head`, in-process.

    Idempotent, so it costs nothing on an already-migrated database — and
    from a bare one it is what makes this a single command rather than two
    (DECISIONS.md D5).
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    # alembic.ini's script_location is relative to the ini file, but the
    # seed must not assume the process CWD is `backend/`.
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")
    return "head"


def _step_grao(ctx: SeedContext) -> str:
    rows = list(grao_loader.parse_file(grao_loader.DEFAULT_ARCHIVE))
    with Session(get_engine()) as session, session.begin():
        summary = grao_loader.load_rows(rows, session)
    return f"rows={summary.rows_loaded} streets={summary.streets_parsed}"


def _step_ingest(ctx: SeedContext) -> str:
    summary = pipeline.run(snapshot_path=pipeline.DEFAULT_SNAPSHOT)
    ctx.scraped_at = summary.scraped_at
    return (
        f"institutions={summary.institutions.inserted + summary.institutions.updated + summary.institutions.unchanged} "
        f"streets={summary.streets.inserted + summary.streets.updated + summary.streets.unchanged} "
        f"addresses={summary.addresses.inserted + summary.addresses.updated + summary.addresses.unchanged} "
        f"address_institutions={summary.address_institutions.inserted + summary.address_institutions.unchanged} "
        f"addresses_district_unstamped={summary.addresses_district_stamp.remaining_null}"
    )


def _step_legacy_institutions(ctx: SeedContext) -> str:
    rows = legacy_loader.parse_file(legacy_loader.DEFAULT_PATH)
    with Session(get_engine()) as session, session.begin():
        summary = legacy_loader.load_rows(rows, session)
    return (
        f"inserted={summary.inserted} updated={summary.updated} "
        f"unchanged={summary.unchanged}"
    )


def _step_institution_locations(ctx: SeedContext) -> str:
    """Loads with ``--allow-incomplete``: the committed CSV can lag the
    snapshot's institutions, and this is a local seed. What the flag lets
    through is surfaced here and re-checked by ``verify``.
    """
    rows = list(institution_locations_loader.parse_file(
        institution_locations_loader.DEFAULT_CSV
    ))
    with Session(get_engine()) as session, session.begin():
        summary = institution_locations_loader.load_rows(
            rows, session, allow_incomplete=True, dry_run=False
        )
    return (
        f"rows={summary.rows_loaded} missing_main={len(summary.missing_main)} "
        f"address_drift={len(summary.address_drift)}"
    )


def _step_restamp_districts(ctx: SeedContext) -> str:
    with Session(get_engine()) as session, session.begin():
        addresses, institutions = restamp_districts_in_session(session)
    return (
        f"addresses_stamped={addresses.primary_stamped + addresses.fallback1_stamped + addresses.fallback2_stamped} "
        f"addresses_district_unstamped={addresses.remaining_null} "
        f"institutions_stamped={institutions.primary_stamped + institutions.fallback_stamped} "
        f"institutions_district_unstamped={institutions.remaining_null}"
    )


def build_steps() -> list[Step]:
    """The seed's steps, in the one order that works. See the module docstring."""
    return [
        Step(name="migrate", run=_step_migrate),
        Step(name="grao", run=_step_grao),
        Step(name="ingest", run=_step_ingest),
        Step(name="legacy-institutions", run=_step_legacy_institutions),
        Step(name="institution-locations", run=_step_institution_locations),
        Step(name="restamp-districts", run=_step_restamp_districts),
    ]


def run_seed(
    *,
    steps: list[Step] | None = None,
    on_step: Callable[[StepResult], None] | None = None,
) -> SeedSummary:
    """Execute every step in order, timing each one.

    ``on_step`` is called as each step finishes, so the CLI can report
    progress live rather than only at the end. The first failure raises
    :class:`SeedStepFailed`; later steps do not run.
    """
    started = time.monotonic()
    ctx = SeedContext()
    summary = SeedSummary()

    for step in steps if steps is not None else build_steps():
        step_started = time.monotonic()
        try:
            detail = step.run(ctx)
        except BaseException as exc:  # noqa: BLE001 - re-raised, named
            raise SeedStepFailed(step.name, exit_code_for(exc), exc) from exc
        result = StepResult(
            name=step.name,
            detail=detail,
            elapsed_ms=int((time.monotonic() - step_started) * 1000),
        )
        summary.steps.append(result)
        if on_step is not None:
            on_step(result)

    summary.scraped_at = ctx.scraped_at
    summary.elapsed_ms = int((time.monotonic() - started) * 1000)
    return summary


def default_paths() -> dict[str, Path]:
    """The committed artifacts the seed reads, for reporting and for tests."""
    return {
        "grao": grao_loader.DEFAULT_ARCHIVE,
        "snapshot": pipeline.DEFAULT_SNAPSHOT,
        "legacy_institutions": legacy_loader.DEFAULT_PATH,
        "institution_locations": institution_locations_loader.DEFAULT_CSV,
    }
