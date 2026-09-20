"""Does this database actually answer the questions production answers?

"The seed ran" and "this database is production-like" are different
claims, and this module makes the second one. D6 keeps the seed running
against a non-empty database — no gate in front of the command — but a
dirty database must not pass verification, because stale rows are not
merely cosmetic: ``_district_rows_for_kind`` (``matching.py:222``) returns
every institution of the queried kind carrying the queried
``district_code``, and ``_address_rows`` (``matching.py:189``) joins the
catchment junction unscoped. An extra nursery, or an edge a previous
snapshot left behind, changes what ``/api/match`` answers.

So the two drifting tables — ``institutions`` and ``address_institutions``
— are reconciled against the committed artifacts by **set equality**:
missing rows and extra rows both fail, each named. Every count is derived
from ``data/seed/snapshot.json.gz`` and
``data/seed/legacy_institutions.json``, never hard-coded. 95 is today's
arithmetic (77 + 18), not a constant — ``freeze`` legitimately rewrites
both artifacts, and a literal would turn a refresh into a failure.

Checks collect rather than short-circuit: a database that has never been
seeded should report everything that is wrong with it in one pass, and
each failure names the seed step that would fix it.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from yasli.ingest import legacy_institutions_loader as legacy_loader
from yasli.ingest.match_data_validation import validate_match_data
from yasli.ingest.pipeline import DEFAULT_SNAPSHOT
from yasli.models import Address, Institution, Street, address_institutions
from yasli.services.matching import build_offerings, find_matches

# ГРАО will never cover every address — new construction, and the villages
# the Varna-city KADS file does not describe at all. `docs/OPERATIONS.md`
# treats >2% of *in-city* addresses unstamped as the staleness signal, and
# a first real seed measures 1.48% (685/46,149), so the threshold is met
# with headroom. Villages are excluded on purpose: counting them would
# measure ГРАО's scope rather than this database's health.
MAX_IN_CITY_UNSTAMPED_SHARE = 0.02

# A snapshot older than this is still usable, but local has drifted far
# enough from production that the developer should know.
SNAPSHOT_STALE_AFTER = timedelta(days=90)

# Addresses whose район is known independently, from the committed ГРАО
# archive rather than from whatever this database happens to hold. A check
# on non-null coverage alone cannot tell a correct district from a
# valid-but-wrong one.
KNOWN_DISTRICTS: tuple[tuple[str, int, str, str], ...] = (
    # (street raw_name, number, entrance, expected district)
    ("ГР.ВАРНА УЛ.Н.Й.ВАПЦАРОВ", 7, "Г", "02"),
    ("ГР.ВАРНА УЛ.Н.Й.ВАПЦАРОВ", 7, "А", "02"),
)

# YAS-21's verification case: the address that returned `null / 0 / 4 / 0`
# locally against production's `02 / 4 / 4 / 2`.
ROUTING_CASE = ("ГР.ВАРНА УЛ.Н.Й.ВАПЦАРОВ", 7, "Г", "02")

# ДГ№13 "Мир" — the detail-page case from YAS-11, four branches with pins.
BRANCHED_INSTITUTION = ("kindergarten", "46", 4)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    remedy: str | None = None
    warning: bool = False
    items: list[str] = field(default_factory=list)


@dataclass
class VerifyResult:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and not c.warning]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.warning]

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass
class Artifacts:
    """The committed files verification measures the database against."""

    snapshot: dict[str, Any]
    legacy: list[dict[str, Any]]

    @classmethod
    def load(cls) -> Artifacts:
        snapshot = json.loads(gzip.decompress(DEFAULT_SNAPSHOT.read_bytes()))
        legacy = legacy_loader.parse_file(legacy_loader.DEFAULT_PATH)
        return cls(snapshot=snapshot, legacy=legacy)

    @property
    def scraped_at(self) -> datetime | None:
        raw = self.snapshot.get("scraped_at")
        if not raw:
            return None
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))

    @property
    def snapshot_keys(self) -> set[tuple[str, str]]:
        return {
            (i["kind"], str(i["external_id"])) for i in self.snapshot["institutions"]
        }

    @property
    def legacy_keys(self) -> set[tuple[str, str]]:
        return {(r["kind"], r["external_id"]) for r in self.legacy}

    @property
    def expected_institution_keys(self) -> set[tuple[str, str]]:
        """The disjoint union the seed is supposed to produce."""
        return self.snapshot_keys | self.legacy_keys

    @property
    def legacy_without_district(self) -> set[tuple[str, str]]:
        """Fixture rows that deliberately carry no район.

        Production holds no район for any of these, so neither does the
        fixture; they are the expected, non-defective population of
        `validate-match-data`'s `nursery_without_district` counter.
        """
        return {
            (r["kind"], r["external_id"])
            for r in self.legacy
            if r["district_code"] is None
        }


Check = Callable[[Session, Artifacts], CheckResult]


def _truncate(items: list[str], limit: int = 10) -> list[str]:
    if len(items) <= limit:
        return items
    return [*items[:limit], f"… and {len(items) - limit} more"]


def _one_line(exc: BaseException) -> str:
    """The first line of an exception, without the SQL a driver appends.

    An unseeded database raises one ``UndefinedTable`` per check; printing
    each one's full statement buries the nine things actually wrong under
    a page of SQL.
    """
    first = str(exc).strip().splitlines()
    return first[0] if first else exc.__class__.__name__


# --- checks ----------------------------------------------------------------


def check_institution_set(session: Session, artifacts: Artifacts) -> CheckResult:
    """Institutions must be exactly the artifacts' union — no more, no less."""
    expected = artifacts.expected_institution_keys
    rows = session.execute(
        select(Institution.kind, Institution.external_id, Institution.district_code)
    ).all()
    actual = {(r.kind, r.external_id) for r in rows}
    districts = {(r.kind, r.external_id): r.district_code for r in rows}

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if not missing and not extra:
        return CheckResult(
            name="institution-set",
            ok=True,
            detail=(
                f"{len(actual)} institutions = snapshot {len(artifacts.snapshot_keys)} "
                f"+ fixture {len(artifacts.legacy_keys)}"
            ),
        )

    items = [f"missing {k}/{e}" for k, e in missing]
    items += [
        f"extra {k}/{e} (district {districts[(k, e)] or 'null'})" for k, e in extra
    ]
    remedy = "re-run the seed" if missing else "just db-reset && just be-seed"
    detail = f"{len(missing)} missing, {len(extra)} beyond the committed artifacts"
    if extra:
        detail += (
            " — a stale institution carrying a district shows up in /api/match, "
            "so this database answers differently from production"
        )
    return CheckResult(
        name="institution-set",
        ok=False,
        detail=detail,
        remedy=remedy,
        items=_truncate(items),
    )


EdgeKey = tuple[str, int, str, str, str, str]


def _blank(value: str | None) -> str:
    """Ingest's "no suffix"/"no entrance" convention is the empty string."""
    return value or ""


def _snapshot_edges(artifacts: Artifacts) -> set[EdgeKey]:
    """The (address, institution) pairs the snapshot describes.

    Derived by replaying the snapshot through the ingest planner, so the
    expectation tracks the artifact rather than a number written down
    once. Keyed on natural keys, not surrogate ids, so it compares against
    any database seeded from this snapshot.
    """
    from yasli.ingest.pipeline import _build_plan, _validate_snapshot

    snapshot = _validate_snapshot(gzip.decompress(DEFAULT_SNAPSHOT.read_bytes()))
    plan = _build_plan(snapshot)
    return {
        (
            street_raw,
            number,
            _blank(suffix),
            _blank(entrance),
            kind,
            external_id,
        )
        for (street_raw, number, suffix, entrance), (
            external_id,
            kind,
        ) in plan.coverage_edges
    }


def _database_edges(session: Session) -> set[EdgeKey]:
    rows = session.execute(
        select(
            Street.raw_name,
            Address.number_int,
            Address.number_suffix,
            Address.entrance,
            Institution.kind,
            Institution.external_id,
        )
        .select_from(address_institutions)
        .join(Address, Address.id == address_institutions.c.address_id)
        .join(Street, Street.id == Address.street_id)
        .join(
            Institution, Institution.id == address_institutions.c.institution_id
        )
    ).all()
    return {
        (raw, number, _blank(suffix), _blank(entrance), kind, external_id)
        for raw, number, suffix, entrance, kind, external_id in rows
    }


def check_catchment_edges(session: Session, artifacts: Artifacts) -> CheckResult:
    """`address_institutions` must hold exactly the snapshot's edge set.

    Ingest inserts with `on_conflict_do_nothing` and never deletes, while
    `_address_rows` joins the junction unscoped — so an edge left behind by
    a previous snapshot silently adds a kindergarten or preschool to
    `/api/match`. The institution set being right is not sufficient.
    """
    expected = _snapshot_edges(artifacts)
    actual = _database_edges(session)
    missing = expected - actual
    extra = actual - expected

    if not missing and not extra:
        return CheckResult(
            name="catchment-edges",
            ok=True,
            detail=f"{len(actual)} edges = the snapshot's edge set",
        )

    def _describe(edge: EdgeKey) -> str:
        raw, number, suffix, entrance, kind, external_id = edge
        place = f"{raw} {number}{suffix}" + (f" вх.{entrance}" if entrance else "")
        return f"{place} → {kind}/{external_id}"

    items = [f"missing {_describe(e)}" for e in sorted(missing)[:5]]
    items += [f"extra {_describe(e)}" for e in sorted(extra)[:5]]
    detail = (
        f"{len(actual)} edges against the snapshot's {len(expected)}: "
        f"{len(missing)} missing, {len(extra)} beyond it"
    )
    if extra:
        detail += (
            " — an edge the snapshot does not describe keeps adding a "
            "kindergarten or preschool to /api/match"
        )
    return CheckResult(
        name="catchment-edges",
        ok=False,
        detail=detail,
        remedy=(
            "just db-reset && just be-seed"
            if extra
            else "re-run the seed (ingest step)"
        ),
        items=_truncate(items),
    )


def check_grao_addresses(session: Session, artifacts: Artifacts) -> CheckResult:
    rows = session.execute(
        text(
            "SELECT count(*), count(DISTINCT district_code) FROM grao_addresses"
        )
    ).one()
    total, districts = rows
    if total > 0 and districts == 5:
        return CheckResult(
            name="grao-addresses",
            ok=True,
            detail=f"{total} rows across {districts} districts",
        )
    return CheckResult(
        name="grao-addresses",
        ok=False,
        detail=(
            f"{total} rows across {districts} districts — nurseries and "
            "preschools return nothing for every address without them"
        ),
        remedy="re-run the seed (grao step)",
    )


def check_address_districts(session: Session, artifacts: Artifacts) -> CheckResult:
    """In-city coverage only; villages are outside the KADS file by design."""
    unstamped, total = session.execute(
        text(
            "SELECT count(*) FILTER (WHERE a.district_code IS NULL), count(*) "
            "FROM addresses a JOIN settlements s ON s.code = a.settlement_code "
            "WHERE s.name = 'ГР.ВАРНА'"
        )
    ).one()
    if total == 0:
        return CheckResult(
            name="address-districts",
            ok=False,
            detail="no in-city addresses at all",
            remedy="re-run the seed (ingest step)",
        )
    share = unstamped / total
    if share <= MAX_IN_CITY_UNSTAMPED_SHARE:
        return CheckResult(
            name="address-districts",
            ok=True,
            detail=f"{unstamped}/{total} in-city unstamped ({share:.2%})",
        )
    return CheckResult(
        name="address-districts",
        ok=False,
        detail=(
            f"{unstamped}/{total} in-city addresses unstamped ({share:.2%}, "
            f"threshold {MAX_IN_CITY_UNSTAMPED_SHARE:.0%})"
        ),
        remedy="re-run the seed (grao step must precede ingest)",
    )


def check_institution_districts(
    session: Session, artifacts: Artifacts
) -> CheckResult:
    """Nurseries must carry a район — bar the fixture's deliberate nulls.

    This is a check on the *seed data*, not on the stamping pass:
    `district_stamp` excludes `kind='nursery'` on purpose because nursery
    districts are API-sourced, so a NULL here means the snapshot or the
    fixture lacks the value and re-running `restamp-districts` would do
    nothing. Nurseries are the load-bearing case because
    `_district_rows_for_kind` is the *only* way one reaches `/api/match`.

    Preschools are listed, not failed. They route through catchment edges
    with the район only as a fallback (`_preschool_rows`), and a village
    school genuinely has no район to carry — ГРАО's KADS file covers
    Varna city. Production carries the same handful, so failing on them
    would mean failing on parity with production.
    """
    allowed = artifacts.legacy_without_district
    rows = session.execute(
        select(Institution.kind, Institution.external_id, Institution.name)
        .where(Institution.kind.in_(("nursery", "preschool")))
        .where(Institution.district_code.is_(None))
    ).all()
    offenders = [
        r
        for r in rows
        if r.kind == "nursery" and (r.kind, r.external_id) not in allowed
    ]
    unstamped_preschools = [r for r in rows if r.kind == "preschool"]

    if not offenders:
        detail = (
            f"{len(allowed)} nurseries without a район, all of them the "
            "fixture's known-null legacy rows"
        )
        return CheckResult(
            name="institution-districts",
            ok=True,
            detail=detail,
            items=_truncate(
                [
                    f"preschool/{r.external_id} {r.name} "
                    "(no район; routes by catchment)"
                    for r in unstamped_preschools
                ],
                limit=3,
            ),
        )
    return CheckResult(
        name="institution-districts",
        ok=False,
        detail=(
            f"{len(offenders)} nursery rows carry no район and are not the "
            "fixture's known-null rows — the seed data lacks the value, and "
            "restamp-districts cannot supply it for a nursery. These route "
            "nowhere in /api/match"
        ),
        remedy="re-run the seed (ingest step), or refresh the artifacts",
        items=_truncate([f"{r.kind}/{r.external_id} {r.name}" for r in offenders]),
    )


def check_institution_locations(
    session: Session, artifacts: Artifacts
) -> CheckResult:
    by_role = dict(
        session.execute(
            text(
                "SELECT role, count(*) FROM institution_locations GROUP BY role"
            )
        ).all()
    )
    kind, external_id, expected_branches = BRANCHED_INSTITUTION
    branches = session.execute(
        text(
            "SELECT count(*), count(lat) FROM institution_locations "
            "WHERE kind = :kind AND external_id = :external_id AND role = 'branch'"
        ),
        {"kind": kind, "external_id": external_id},
    ).one()
    branch_rows, with_coords = branches

    problems: list[str] = []
    if not by_role.get("main"):
        problems.append("no main rows at all")
    if not by_role.get("branch"):
        problems.append("no branch rows at all")
    if branch_rows != expected_branches:
        problems.append(
            f"{kind}/{external_id} has {branch_rows} branches, "
            f"expected {expected_branches}"
        )
    elif with_coords != expected_branches:
        problems.append(
            f"{kind}/{external_id} has {with_coords}/{branch_rows} branches "
            "with coordinates"
        )

    if not problems:
        return CheckResult(
            name="institution-locations",
            ok=True,
            detail=(
                f"main={by_role.get('main', 0)} branch={by_role.get('branch', 0)}, "
                f"{kind}/{external_id} has {branch_rows} branches with pins"
            ),
        )
    return CheckResult(
        name="institution-locations",
        ok=False,
        detail="; ".join(problems),
        remedy="re-run the seed (institution-locations step)",
        items=[],
    )


def _resolve_address(
    session: Session, street_raw: str, number: int, entrance: str
) -> Any:
    """`/api/match` is keyed by `addresses.id`, and surrogate ids do not
    correspond across databases — so resolve by natural key in *this* one.
    """
    return session.execute(
        select(Address.id, Address.district_code)
        .join(Street, Street.id == Address.street_id)
        .where(Street.raw_name == street_raw)
        .where(Address.number_int == number)
        .where(Address.entrance == entrance)
    ).one_or_none()


def check_known_districts(session: Session, artifacts: Artifacts) -> CheckResult:
    """Named addresses whose район is known from the ГРАО archive.

    Coverage and code-membership checks cannot tell a correct district from
    a valid-but-wrong one; these can.
    """
    problems: list[str] = []
    checked = 0
    for street_raw, number, entrance, expected in KNOWN_DISTRICTS:
        row = _resolve_address(session, street_raw, number, entrance)
        if row is None:
            problems.append(f"{street_raw} {number} вх.{entrance}: address not found")
            continue
        checked += 1
        if row.district_code != expected:
            problems.append(
                f"{street_raw} {number} вх.{entrance}: district "
                f"{row.district_code or 'null'}, expected {expected}"
            )
    if not problems:
        return CheckResult(
            name="known-districts",
            ok=True,
            detail=f"{checked} named addresses carry their expected район",
        )
    return CheckResult(
        name="known-districts",
        ok=False,
        detail=f"{len(problems)} named address(es) carry the wrong район",
        remedy="re-run the seed (grao step), or refresh the ГРАО archive",
        items=problems,
    )


def check_routing_case(session: Session, artifacts: Artifacts) -> CheckResult:
    """YAS-21's verification case, end to end through the match service."""
    street_raw, number, entrance, expected_district = ROUTING_CASE
    row = _resolve_address(session, street_raw, number, entrance)
    if row is None:
        return CheckResult(
            name="routing-case",
            ok=False,
            detail=f"{street_raw} {number} вх.{entrance} does not resolve to an address",
            remedy="re-run the seed (ingest step)",
        )

    match_set = find_matches(session, row.id)
    if match_set is None:
        return CheckResult(
            name="routing-case",
            ok=False,
            detail=f"address {row.id} has no match context",
            remedy="re-run the seed",
        )

    counts: dict[str, int] = {"nursery": 0, "kindergarten": 0, "preschool": 0}
    for offering in build_offerings(match_set):
        counts[offering.reception_kind] += 1

    empty = [kind for kind, n in counts.items() if n == 0]
    wrong_district = match_set.address.district_code != expected_district
    summary = (
        f"address {row.id} district={match_set.address.district_code or 'null'} "
        f"nurseries={counts['nursery']} kindergartens={counts['kindergarten']} "
        f"preschools={counts['preschool']}"
    )
    if not empty and not wrong_district:
        return CheckResult(name="routing-case", ok=True, detail=summary)

    return CheckResult(
        name="routing-case",
        ok=False,
        detail=(
            f"{summary} — YAS-21's case must return all three kinds in "
            f"район {expected_district}"
        ),
        remedy="re-run the seed (grao step must precede ingest)",
        items=[f"no {kind} offerings" for kind in empty],
    )


def check_match_data(session: Session, artifacts: Artifacts) -> CheckResult:
    """Reuse `validate-match-data` rather than reimplementing its queries.

    Its `nursery_without_district` counter is expected to equal the number
    of fixture rows that deliberately carry no район — production reports
    the same population. Any *other* hard failure is a real defect.
    """
    result = validate_match_data(session)
    expected_null_nurseries = len(artifacts.legacy_without_district)
    failures = result.hard_failures
    problems = [
        f"{name}={value}"
        for name, value in vars(failures).items()
        if value
        and not (
            name == "nursery_without_district" and value == expected_null_nurseries
        )
    ]
    if not problems:
        return CheckResult(
            name="match-data-validation",
            ok=True,
            detail=(
                "no unexpected hard failures "
                f"(nursery_without_district={failures.nursery_without_district}, "
                f"the fixture's {expected_null_nurseries} known-null legacy rows)"
            ),
        )
    return CheckResult(
        name="match-data-validation",
        ok=False,
        detail="validate-match-data reports hard failures",
        remedy="python -m yasli.ingest validate-match-data for the full report",
        items=problems,
    )


def check_snapshot_freshness(session: Session, artifacts: Artifacts) -> CheckResult:
    """A warning, never a failure: stale is usable, silently stale is not."""
    scraped_at = artifacts.scraped_at
    if scraped_at is None:
        return CheckResult(
            name="snapshot-freshness",
            ok=False,
            warning=True,
            detail="the committed snapshot carries no scraped_at",
            remedy="python -m yasli.seed freeze",
        )
    age = datetime.now(UTC) - scraped_at
    if age <= SNAPSHOT_STALE_AFTER:
        return CheckResult(
            name="snapshot-freshness",
            ok=True,
            detail=f"snapshot {scraped_at.date()} ({age.days} days old)",
        )
    return CheckResult(
        name="snapshot-freshness",
        ok=False,
        warning=True,
        detail=(
            f"snapshot {scraped_at.date()} is {age.days} days old — local has "
            f"drifted from production (threshold {SNAPSHOT_STALE_AFTER.days} days)"
        ),
        remedy="python -m yasli.seed freeze",
    )


CHECKS: tuple[Check, ...] = (
    check_institution_set,
    check_catchment_edges,
    check_grao_addresses,
    check_address_districts,
    check_institution_districts,
    check_institution_locations,
    check_known_districts,
    check_routing_case,
    check_match_data,
    check_snapshot_freshness,
)


def run_checks(
    session: Session, artifacts: Artifacts | None = None
) -> VerifyResult:
    """Run every check, collecting failures rather than stopping at the first.

    A database that has never been seeded should report everything that is
    wrong with it in one pass. A check that raises is itself a failure —
    a missing table is exactly what "never seeded" looks like.
    """
    artifacts = artifacts or Artifacts.load()
    result = VerifyResult()
    for check in CHECKS:
        try:
            result.checks.append(check(session, artifacts))
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            session.rollback()
            result.checks.append(
                CheckResult(
                    name=getattr(check, "__name__", "check")
                    .removeprefix("check_")
                    .replace("_", "-"),
                    ok=False,
                    detail=f"check could not run: {_one_line(exc)}",
                    remedy="run the seed — this database looks unseeded",
                )
            )
    return result


def format_result(result: VerifyResult) -> str:
    lines: list[str] = []
    for check in result.checks:
        mark = "ok  " if check.ok else ("warn" if check.warning else "FAIL")
        lines.append(f"  [{mark}] {check.name:<22} {check.detail}")
        lines.extend(f"           - {item}" for item in check.items)
        if not check.ok and check.remedy:
            lines.append(f"           → {check.remedy}")
    failures = len(result.failures)
    warnings = len(result.warnings)
    lines.append(
        f"verify {'passed' if result.ok else 'FAILED'} "
        f"checks={len(result.checks)} failures={failures} warnings={warnings}"
    )
    return "\n".join(lines)
