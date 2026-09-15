# Adversarial Validation — Round 3

**Run:** 2026-09-15 05:47 UTC
**Plan:** institution-locations-dataset
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md
**Reviewer:** Codex (`/codex-local:adversarial-review`), short shared-protocol focus text (see the round-2 header for why).

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not ship the plan yet. Round-2 closes its stated findings, but the revised recovery model can overwrite newer reviewed data, address changes remain silently stale, and the planned SQLite loader tests cannot insert the specified primary key.

Findings:
- [high] Stale gitignored review state can overwrite newer committed artifacts (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-005-build-the-location-review-tool.md:37-41)
  Startup unconditionally regenerates the CSV and provenance from the candidates file. That file is gitignored and can survive branch switches or pulls, so an older local candidates snapshot can overwrite newer committed CSV/provenance without any version or base-hash check. Conversely, a fresh checkout lacks the state needed to preserve human decisions. This makes the round-2 single-commit-point fix a data-reversion path.
  Recommendation: Store and verify a hash/version of the source CSV and provenance in candidate state. Refuse startup regeneration when they diverge, or reconstruct/merge decisions from the committed artifacts. Add stale-state and fresh-checkout recovery tests.
- [high] Institution address changes do not invalidate an old location (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-003-load-the-reference-file-idempotently-via-a-cli.md:77-81)
  The pre-TRUNCATE guard compares only natural keys and the presence of a main row. The existing ingest pipeline updates `institutions.address` on conflict, so an institution can move or receive an address correction while its old CSV row still passes and reloads successfully. The documented refresh triggers also omit changed addresses, allowing a user-visible wrong pin to persist silently.
  Recommendation: Before TRUNCATE, compare each main CSV address with the current institution address, using an explicitly defined normalization policy, and abort on drift. Add address-change tests and make address drift a runbook refresh trigger.
- [medium] BigInteger primary key cannot autogenerate in the planned SQLite loader tests (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-001-add-the-institution-locations-table.md:28-30)
  The schema specifies a bare `BigInteger` primary key while TASK-003 bulk-inserts rows without IDs into SQLite. SQLite only supplies implicit row IDs for a column declared exactly `INTEGER PRIMARY KEY`; `BIGINT PRIMARY KEY` rejects these inserts with `NOT NULL constraint failed`. `create_all` succeeding does not prove the loader can insert, so the prescribed in-memory loader tests will fail.
  Recommendation: Use an ORM type variant such as `BigInteger().with_variant(Integer, "sqlite")`, or another cross-dialect PK strategy, while retaining PostgreSQL BIGINT in the migration. Add a SQLite test that inserts a location without supplying `id`.

Next steps:
- Make candidate-state regeneration conditional on artifact lineage.
- Add address-drift detection to the loader and operations plan.
- Resolve and test cross-dialect surrogate-ID generation.

## Triage

<!--
Verdict values: apply / defer / reject — see round-1.md.
Round 3 still produced apply rows. Per the shared protocol no fourth round is
run automatically; the findings were applied and the run stopped (see
VALIDATION.md). All three are patch-level, not structural: one is a hole in
the round-2 recovery model, one a missing pre-TRUNCATE guard, one a dialect
detail — none questions the plan's approach.
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Stale gitignored candidates file can overwrite newer committed CSV/provenance on startup; a fresh checkout loses human decisions | high | apply | Introduced by round-2 #3. The committed CSV + provenance are now the record across sessions: the candidates file stores the hash of the files it last regenerated; a matching hash means it is in sync or ahead (crash window) and regenerates; a mismatch or a missing candidates file rebuilds every decision from the committed files and keeps only candidates and flags from local state. Tests for stale state, fresh checkout and the crash window | PLAN.md:Decisions, PLAN.md:Acceptance, TASK-004, TASK-005, TASK-007, TASK-008 |
| 2 | Institution address changes do not invalidate an old location | high | apply | Ingest overwrites `institutions.address` on conflict (`pipeline.py` `on_conflict_set`), so a moved institution's stale pin would reload silently — the wrong pin that looks right. Third pre-TRUNCATE guard: each `main` row's address must match the institution's, normalised by a helper in the loader module; `--allow-incomplete` ("the CSV lags the institutions table") covers it; a `--dry-run` runs the guards without loading; the seed script re-flags such rows `address_changed`; the runbook lists drift as a trigger | PLAN.md:Decisions, PLAN.md:Risks, PLAN.md:Acceptance, TASK-002, TASK-003, TASK-004, TASK-007, TASK-008 |
| 3 | `BigInteger` primary key cannot autogenerate on SQLite | med | apply | Verified 2026-09-15 in the project venv: `insert(Model), rows` without `id` fails with `NOT NULL constraint failed` on a bare `BigInteger` PK and succeeds with `BigInteger().with_variant(Integer, "sqlite")`; `grao_addresses` never hit this because it has a composite natural PK, so the precedent did not cover it | TASK-001 |
