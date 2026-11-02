"""Regenerate the committed snapshot. Maintainer-only.

This is the one command in the seed that needs a credential: R2, for the
snapshot. The maintainer pays the cost once, so every other developer pays
none. It does not touch the database.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from yasli.ingest import r2
from yasli.ingest.pipeline import DEFAULT_SNAPSHOT, LATEST_KEY

# gzip embeds an mtime by default, so an unchanged snapshot would produce a
# different file on every run and every refresh would show a spurious diff.
GZIP_MTIME = 0
GZIP_LEVEL = 9


class FreezeError(ValueError):
    """A freeze cannot proceed. Nothing has been published."""


@dataclass
class FreezeReport:
    snapshot_path: Path
    dry_run: bool = False
    snapshot_written: bool = False
    snapshot_bytes: int = 0
    scraped_at: datetime | None = None
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
        lines.extend(f"  note: {note}" for note in self.notes)
        lines.append(
            "freeze "
            + ("dry-run complete" if self.dry_run else "done")
            + f" snapshot_written={int(self.snapshot_written)}"
        )
        return "\n".join(lines)


def compress(payload: bytes) -> bytes:
    """gzip ``payload`` deterministically — same bytes in, same bytes out."""
    return gzip.compress(payload, compresslevel=GZIP_LEVEL, mtime=GZIP_MTIME)


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


def run_freeze(
    *,
    dry_run: bool = False,
    r2_client: Any | None = None,
    snapshot_path: Path = DEFAULT_SNAPSHOT,
) -> FreezeReport:
    """Fetch the latest snapshot and publish it if its bytes differ."""
    report = FreezeReport(snapshot_path=snapshot_path, dry_run=dry_run)

    committed = snapshot_path.read_bytes() if snapshot_path.exists() else b""
    raw_snapshot = fetch_snapshot(r2_client)
    candidate = compress(raw_snapshot)

    report.scraped_at = _scraped_at(raw_snapshot)
    report.snapshot_bytes = len(candidate)
    report.snapshot_written = candidate != committed
    if not report.snapshot_written:
        report.notes.append("snapshot is byte-identical to the committed one")

    if dry_run or not report.snapshot_written:
        return report

    staging = Path(tempfile.mkdtemp(prefix="yasli-freeze-"))
    try:
        tmp = staging / snapshot_path.name
        tmp.write_bytes(candidate)
        try:
            os.replace(tmp, snapshot_path)
        except OSError as exc:
            raise FreezeError(
                f"could not publish {snapshot_path.name}: {exc}. Nothing was written."
            ) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return report
