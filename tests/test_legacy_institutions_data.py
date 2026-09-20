"""Shape of the committed ``data/seed/legacy_institutions.json``.

The fixture upserts on ``(kind, external_id)``, so the damaging failure is
not staleness but *overlap*: a fixture row whose key has since become a
live snapshot row would replace current data with a months-old copy. The
disjointness test below is the net that fails ``just be-test`` before such
a pair could be merged (DECISIONS.md D8).
"""

from __future__ import annotations

import gzip
import json

import pytest

from yasli.ingest.legacy_institutions_loader import DEFAULT_PATH, parse_file
from yasli.ingest.pipeline import DEFAULT_SNAPSHOT


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return parse_file(DEFAULT_PATH)


@pytest.fixture(scope="module")
def snapshot_keys() -> set[tuple[str, str]]:
    payload = json.loads(gzip.decompress(DEFAULT_SNAPSHOT.read_bytes()))
    return {(i["kind"], str(i["external_id"])) for i in payload["institutions"]}


def test_fixture_exists_and_parses(rows: list[dict]) -> None:
    assert DEFAULT_PATH.is_file()
    assert len(rows) == 18


def test_every_row_is_a_nursery(rows: list[dict]) -> None:
    assert {r["kind"] for r in rows} == {"nursery"}


def test_external_ids_are_the_expected_range(rows: list[dict]) -> None:
    ids = sorted(int(r["external_id"]) for r in rows)
    assert ids[0] == 39
    assert ids[-1] == 83
    assert len(set(ids)) == 18


def test_keys_are_disjoint_from_the_snapshot(
    rows: list[dict], snapshot_keys: set[tuple[str, str]]
) -> None:
    """The fixture must never shadow a live snapshot row."""
    fixture_keys = {(r["kind"], r["external_id"]) for r in rows}
    assert not fixture_keys & snapshot_keys


def test_fixture_plus_snapshot_is_the_production_institution_count(
    rows: list[dict], snapshot_keys: set[tuple[str, str]]
) -> None:
    """95, derived from the artifacts rather than asserted as a constant."""
    fixture_keys = {(r["kind"], r["external_id"]) for r in rows}
    assert len(fixture_keys | snapshot_keys) == 95


def test_district_code_is_stated_on_every_row(rows: list[dict]) -> None:
    """Present on every row, and null — which is what production carries.

    These rows predate 2026-05-10 and were never retired; production has no
    район for any of them, so neither does the fixture. A non-null value
    here would make local route nurseries production does not return, which
    is the opposite of production-like. The parser still rejects anything
    outside ``01``–``05``, so a future refresh that *does* find a район
    lands a checked value.
    """
    assert all("district_code" in r for r in rows)
    assert {r["district_code"] for r in rows} == {None}


def test_every_row_carries_a_source_url(rows: list[dict]) -> None:
    assert all(r["source_url"].startswith("https://dg.uslugi.io/") for r in rows)


def test_manifest_slugs_all_resolve_against_snapshot_plus_fixture(
    rows: list[dict], snapshot_keys: set[tuple[str, str]]
) -> None:
    """Every frontend manifest entry must be resolvable after a seed.

    The manifest lives in the frontend repository. This checkout may be a
    git worktree nested under `backend/`, so walk up looking for the
    sibling rather than assuming a fixed depth; when it is not checked out
    at all the test skips rather than failing on a missing sibling.
    """
    relative = ("frontend", "src", "data", "institutions-manifest.json")
    manifest = next(
        (
            candidate
            for parent in DEFAULT_PATH.parents
            if (candidate := parent.joinpath(*relative)).is_file()
        ),
        None,
    )
    if manifest is None:
        pytest.skip("frontend/src/data/institutions-manifest.json not checked out")
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_keys = {(e["kind"], str(e["external_id"])) for e in entries}
    fixture_keys = {(r["kind"], r["external_id"]) for r in rows}
    assert not manifest_keys - (snapshot_keys | fixture_keys)
