"""Regenerate the committed seed artifacts. Maintainer-only.

This is the one command in the seed that needs credentials — R2 for the
snapshot, and read access to production for the legacy fixture. That is
the point: the maintainer pays the credential cost once, so every other
developer pays none.

**The two artifacts are a pair.** The legacy loader upserts on
``(kind, external_id)``, so a fixture row whose key has since become a
live snapshot row would overwrite current data with a months-old copy.
That, not staleness, is the failure that costs data. Both candidates are
therefore built in a temp directory, checked for key overlap *as a pair*,
and only then published — so a failure while deriving the fixture cannot
leave a new snapshot beside an old fixture.

**The publish is not atomic, and this module does not pretend otherwise.**
Two sequential ``os.replace`` calls can be interrupted between the first
and the second. The window is two syscalls wide, ``data/seed/`` is a git
working tree where ``git checkout -- data/seed/`` is a complete rollback,
and the committed-data test fails ``just be-test`` before a mismatched
pair could be committed. What the command owes in exchange is honesty: a
failed second rename exits non-zero and names both files as possibly
disagreeing, rather than reporting a successful freeze (DECISIONS.md D8).
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasli.db import get_engine
from yasli.ingest import legacy_institutions_loader as legacy_loader
from yasli.ingest import r2
from yasli.ingest.pipeline import DEFAULT_SNAPSHOT, LATEST_KEY
from yasli.models import Institution

# gzip embeds an mtime by default, so an unchanged snapshot would produce a
# different file on every run and every refresh would show a spurious diff.
GZIP_MTIME = 0
GZIP_LEVEL = 9


class FreezeError(ValueError):
    """A freeze cannot proceed. Nothing has been published."""


class FreezeOverlapError(FreezeError):
    """The candidate fixture and snapshot claim the same keys."""


class FreezePublishError(Exception):
    """A rename failed *after* another succeeded — the pair may disagree."""


@dataclass
class FreezeReport:
    snapshot_path: Path
    legacy_path: Path
    dry_run: bool = False
    snapshot_written: bool = False
    snapshot_bytes: int = 0
    scraped_at: datetime | None = None
    legacy_written: bool = False
    legacy_bytes: int = 0
    legacy_rows: int = 0
    notes: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines: list[str] = []
        scraped = self.scraped_at.isoformat() if self.scraped_at else "unknown"
        verb = "would write" if self.dry_run else "wrote"
        lines.append(
            f"  snapshot  {verb if self.snapshot_written else 'unchanged'} "
            f"{self.snapshot_path.name} bytes={self.snapshot_bytes} "
            f"scraped_at={scraped}"
        )
        lines.append(
            f"  legacy    {verb if self.legacy_written else 'unchanged'} "
            f"{self.legacy_path.name} bytes={self.legacy_bytes} "
            f"rows={self.legacy_rows}"
        )
        lines.extend(f"  note: {note}" for note in self.notes)
        lines.append(
            "freeze "
            + ("dry-run complete" if self.dry_run else "done")
            + f" snapshot_written={int(self.snapshot_written)} "
            f"legacy_written={int(self.legacy_written)}"
        )
        return "\n".join(lines)


def compress(payload: bytes) -> bytes:
    """gzip ``payload`` deterministically — same bytes in, same bytes out."""
    return gzip.compress(payload, compresslevel=GZIP_LEVEL, mtime=GZIP_MTIME)


def _keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(r["kind"], str(r["external_id"])) for r in rows}


def _snapshot_institutions(payload: bytes) -> list[dict[str, Any]]:
    return json.loads(payload)["institutions"]


def _scraped_at(payload: bytes) -> datetime | None:
    raw = json.loads(payload).get("scraped_at")
    if not raw:
        return None
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def fetch_snapshot(r2_client: Any | None = None) -> bytes:
    """The raw (uncompressed) snapshot bytes from R2.

    Reuses `r2.get_object` and `LATEST_KEY` — freeze must not grow its own
    idea of where snapshots live.
    """
    return r2.get_object(LATEST_KEY, client=r2_client)


def derive_legacy_rows(
    session: Session, snapshot_payload: bytes
) -> list[dict[str, Any]]:
    """Institutions the database holds that the snapshot does not describe.

    Each row is a faithful copy of what production carries, including a
    NULL ``district_code``: that column is API-sourced and no stamping pass
    supplies it for a nursery, so production genuinely holds none for these
    rows. A *non-null* value outside ``01``–``05`` is a real defect and
    aborts, rather than emitting a fixture the loader would reject.
    """
    snapshot_keys = _keys(_snapshot_institutions(snapshot_payload))
    rows = session.execute(
        select(
            Institution.kind,
            Institution.external_id,
            Institution.name,
            Institution.source_url,
            Institution.address,
            Institution.district_code,
            Institution.has_infant_group,
            Institution.last_seen_at,
        ).order_by(Institution.kind, Institution.external_id)
    ).all()

    derived: list[dict[str, Any]] = []
    for row in rows:
        if (row.kind, row.external_id) in snapshot_keys:
            continue
        if row.district_code is not None and (
            row.district_code not in legacy_loader.DISTRICT_CODES
        ):
            raise FreezeError(
                f"{row.kind}/{row.external_id} carries district_code "
                f"{row.district_code!r}, which is outside 01-05 — refusing to "
                "write a fixture the loader would reject"
            )
        derived.append(
            {
                "kind": row.kind,
                "external_id": row.external_id,
                "name": row.name,
                "source_url": row.source_url,
                "address": row.address,
                "district_code": row.district_code,
                "has_infant_group": bool(row.has_infant_group),
                "last_seen_at": row.last_seen_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    derived.sort(key=lambda r: (r["kind"], int(r["external_id"])))
    return derived


def render_legacy(rows: list[dict[str, Any]]) -> bytes:
    """Serialise fixture rows exactly as the committed file stores them.

    Rows arrive from two places — freshly derived (``last_seen_at`` already
    a string) and parsed back out of the committed file by the loader
    (``last_seen_at`` a ``datetime``). Normalising here is what lets the
    caller compare candidate bytes against committed bytes to decide
    whether anything actually changed.
    """
    normalised = [
        {
            key: (
                value.strftime("%Y-%m-%dT%H:%M:%SZ")
                if isinstance(value, datetime)
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    ]
    return (
        json.dumps(normalised, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _assert_disjoint(
    snapshot_payload: bytes, legacy_rows: list[dict[str, Any]]
) -> None:
    """The one check that costs data if skipped. See the module docstring."""
    overlap = _keys(_snapshot_institutions(snapshot_payload)) & _keys(legacy_rows)
    if not overlap:
        return
    named = ", ".join(f"{k}/{e}" for k, e in sorted(overlap))
    raise FreezeOverlapError(
        f"the candidate fixture and snapshot both claim {named}. The fixture "
        "upserts on (kind, external_id), so publishing this pair would "
        "overwrite current data with a months-old copy. Nothing was written. "
        "Either run a full freeze (which derives the fixture as production "
        "minus the snapshot), or drop those keys from "
        f"{legacy_loader.DEFAULT_PATH.name} first."
    )


def run_freeze(
    *,
    snapshot_only: bool = False,
    legacy_only: bool = False,
    dry_run: bool = False,
    allow_shrink: bool = False,
    r2_client: Any | None = None,
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    legacy_path: Path = legacy_loader.DEFAULT_PATH,
    session_factory: Callable[[], Session] | None = None,
) -> FreezeReport:
    """Build both candidates, check them as a pair, then publish both."""
    report = FreezeReport(
        snapshot_path=snapshot_path, legacy_path=legacy_path, dry_run=dry_run
    )

    committed_snapshot = (
        snapshot_path.read_bytes() if snapshot_path.exists() else b""
    )
    committed_legacy_rows = (
        legacy_loader.parse_file(legacy_path) if legacy_path.exists() else []
    )

    # --- candidate snapshot ---
    if legacy_only:
        if not committed_snapshot:
            raise FreezeError(
                f"--legacy-only needs the committed {snapshot_path.name}, which "
                "is not there"
            )
        raw_snapshot = gzip.decompress(committed_snapshot)
        candidate_snapshot = committed_snapshot
    else:
        raw_snapshot = fetch_snapshot(r2_client)
        candidate_snapshot = compress(raw_snapshot)

    report.scraped_at = _scraped_at(raw_snapshot)
    report.snapshot_bytes = len(candidate_snapshot)
    report.snapshot_written = candidate_snapshot != committed_snapshot
    if not legacy_only and not report.snapshot_written:
        report.notes.append("snapshot is byte-identical to the committed one")

    # --- candidate fixture ---
    candidate_legacy_rows = committed_legacy_rows
    if snapshot_only:
        report.notes.append(
            "--snapshot-only: the committed fixture was kept and re-checked "
            "against the new snapshot"
        )
    else:
        factory = session_factory or (lambda: Session(get_engine()))
        with factory() as session:
            derived = derive_legacy_rows(session, raw_snapshot)
        if not derived:
            # Without this a maintainer pointed at their own local database
            # would silently delete all 18 rows, and the deletion would look
            # like a legitimate refresh in review.
            report.notes.append(
                "the configured database holds no institutions absent from the "
                f"snapshot — {legacy_path.name} was left untouched"
            )
        else:
            shrink = _keys(committed_legacy_rows) - _keys(derived)
            if shrink and not allow_shrink:
                named = ", ".join(f"{k}/{e}" for k, e in sorted(shrink))
                raise FreezeError(
                    f"the derived fixture loses {len(shrink)} row(s) the "
                    f"committed one has: {named}. A partial or wrong database "
                    "shrinks the fixture without emptying it. Nothing was "
                    "written; pass --allow-shrink if this is intended."
                )
            candidate_legacy_rows = derived

    candidate_legacy = render_legacy(candidate_legacy_rows)
    committed_legacy = (
        legacy_path.read_bytes() if legacy_path.exists() else b""
    )
    report.legacy_bytes = len(candidate_legacy)
    report.legacy_rows = len(candidate_legacy_rows)
    report.legacy_written = candidate_legacy != committed_legacy

    # --- the pairing guard, over the candidate pair ---
    _assert_disjoint(raw_snapshot, candidate_legacy_rows)

    if dry_run:
        if not report.snapshot_written and not report.legacy_written:
            report.notes.append("no drift: both artifacts are already current")
        return report

    _publish(
        report=report,
        snapshot_bytes=candidate_snapshot if report.snapshot_written else None,
        legacy_bytes=candidate_legacy if report.legacy_written else None,
    )
    return report


def _publish(
    *,
    report: FreezeReport,
    snapshot_bytes: bytes | None,
    legacy_bytes: bytes | None,
) -> None:
    """Move both candidates into place, back to back, as the last act.

    Everything before this point is reversible by doing nothing. A failure
    here, between the two renames, is the residual window D8 accepts — so
    it is reported as a possible mismatch, never as success.
    """
    if snapshot_bytes is None and legacy_bytes is None:
        return

    staging = Path(tempfile.mkdtemp(prefix="yasli-freeze-"))
    published: list[Path] = []
    try:
        staged: list[tuple[Path, Path]] = []
        if snapshot_bytes is not None:
            tmp = staging / report.snapshot_path.name
            tmp.write_bytes(snapshot_bytes)
            staged.append((tmp, report.snapshot_path))
        if legacy_bytes is not None:
            tmp = staging / report.legacy_path.name
            tmp.write_bytes(legacy_bytes)
            staged.append((tmp, report.legacy_path))

        for source, destination in staged:
            try:
                os.replace(source, destination)
            except OSError as exc:
                if published:
                    raise FreezePublishError(
                        f"published {published[0].name} but failed to publish "
                        f"{destination.name}: {exc}. These two files may now "
                        "disagree — run `git checkout -- data/seed/` and try "
                        "again."
                    ) from exc
                raise FreezeError(
                    f"could not publish {destination.name}: {exc}. Nothing was "
                    "written."
                ) from exc
            published.append(destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
