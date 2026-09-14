# Validation Summary — institution-contact-fields-contract

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-09-14

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 6        | 6       | 0        | 0        |
| 2     | 2        | 1       | 0        | 1        |
| 3     | 1        | 1       | 0        | 0        |

Round 1 combined Codex's two findings with four from a Claude grounding pass
(#3–#6). Round 3 still produced an apply; the user chose to apply it and stop
rather than run a fourth round.

## Applied

### Round 1
- TASK-001:Acceptance+Evidence — schema diff expectation fixed: the fixture differs from the scraper's schema by `minItems` **and** the four backend-only properties; scraper convergence is proven in phase 1.2 (round-1 #1)
- TASK-004:Steps — added "re-ingest twice → `unchanged`" and "changed phone → `updated`" evidence (round-1 #2)
- TASK-003:Notes; TASK-004:Steps — there is no local-file ingest path; the contact-bearing demo now calls `pipeline.run(r2_client=<stub>)` against the local DB and forbids uploading the edited file to R2 (which would overwrite the production snapshot) (round-1 #3)
- TASK-001:Files; TASK-003:Evidence+RED; TASK-004:Steps — test infrastructure corrected (testcontainers Postgres + moto R2 + `snapshot_v2_minimal.json`, no conftest snapshot factory); evidence must show ingest/migration tests `PASSED`, not silently `SKIPPED` without Docker (round-1 #4)
- TASK-002:Files+RED — `test_migrations.py` hard-codes head `"0008"` and `downgrade -2` → `"0006"`; the task now names those edits (round-1 #5)
- TASK-002:Acceptance+Evidence — `alembic check` run before/after against the local DB so pre-existing drift isn't attributed to this change (round-1 #6)
- TASK-004:Steps — added an explicit empty-string rejection demo so PLAN.md AC3 also has final-validation evidence (made alongside round-1 #2)

### Round 2
- TASK-004:Steps; TASK-003:Acceptance+Evidence — the "all four columns NULL" check now counts `phone`, `email`, `director` and `website`, not just `phone` (round-2 #2)

### Round 3
- TASK-004:Steps; TASK-001:RED — API byte-identity diff now uses a pinned baseline captured before the first code commit (base SHA, same R2 `scraped_at`, same two requests) (round-3 #1)

## Deferred

None.

## Rejected

- (round-2 #1) "The local R2 stub uses the wrong client interface" — incorrect: `r2.get_object(key, *, client=...)` uses the passed client directly and reads `client.get_object(Bucket=..., Key=...)["Body"].read()` (`src/yasli/ingest/r2.py:77-95`). Codex confirmed the rejection in round 3. TASK-003's wording was tightened to spell out the exact stub return shape.
