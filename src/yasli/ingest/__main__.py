"""`python -m yasli.ingest` — real R2-snapshot-to-Postgres ingest.

Replaces the s05 schema-presence stub with a call to `pipeline.run()`.
Configuration (DATABASE_URL plus the four R2_* vars) is validated up
front, before any network call. On success, the structured summary line
is printed to stdout; on any failure, an error is printed to stderr and
the process exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import sys

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from yasli.config import Settings
from yasli.ingest import pipeline, r2


def _validate_startup_config() -> None:
    """Raise ValueError if any required env var is missing/empty.

    DATABASE_URL is checked via Settings (mirrors the existing s05
    behaviour); the four R2_* vars are checked via `r2.validate_env`.
    """
    Settings()
    r2.validate_env()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.ingest",
        description=(
            "Pull snapshots/varna/latest.json from R2 and upsert into "
            "Postgres in one transaction."
        ),
    )
    parser.parse_args(argv)

    try:
        _validate_startup_config()
    except (ValueError, r2.R2ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        summary = pipeline.run()
    except pipeline.UnsupportedSnapshotVersion as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except ValidationError as exc:
        print(f"error: snapshot failed validation: {exc}", file=sys.stderr)
        return 3
    except json.JSONDecodeError as exc:
        print(f"error: snapshot is not valid JSON: {exc}", file=sys.stderr)
        return 3
    except (BotoCoreError, ClientError) as exc:
        print(f"error: R2 fetch failed: {exc}", file=sys.stderr)
        return 4
    except SQLAlchemyError as exc:
        print(f"error: database error: {exc}", file=sys.stderr)
        return 5

    pipeline.emit_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
