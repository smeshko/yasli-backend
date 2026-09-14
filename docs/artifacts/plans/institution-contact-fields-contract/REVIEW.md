# Review Summary — institution-contact-fields-contract

**Rounds:** 1
**Fix commits:** none

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 1        | 0     | 0        | 1        |

Round 1 produced no `fix` rows, so no second round was run — the reviewed diff
would have been unchanged.

## Fixes

None.

## Deferred

None.

## Rejected

- (round-1 #1) Unbounded contract strings vs `VARCHAR(128/256)` columns can
  abort the whole ingest — Resolved deliberately in RESEARCH.md "Uncertainty"
  and TASK-002 Notes: an overflow should fail loudly rather than truncate, and
  phase 1.2's live `sc-refresh` surfaces it before production. Column widths are
  far above observed source values, and `name`/`address` already follow the same
  convention. A contract `max_length` would still reject the whole snapshot, so
  it would only move the error earlier while forcing a scraper-schema change
  outside this phase.
