# Validation Summary — institution-locations-dataset

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-09-15

Plan risk is `large`, so round 1 ran Codex and an independent subagent lens in
parallel (findings merged and deduped); rounds 2 and 3 ran Codex alone. Round 3
still produced `apply` rows. Per the shared protocol no fourth round was run
automatically: the three findings were applied and the run stopped. All three
are patch-level (a hole in the round-2 recovery model, a missing pre-TRUNCATE
guard, a SQLite dialect detail) rather than structural, so the recommendation
is to proceed to `implement-plan`; running one more round or stepping back to
`create-plan` is the user's call.

Two process notes. The precondition script refused because a sibling untracked
plan dir (`docs/artifacts/plans/institution-profile-endpoint/`) exists; it was
never touched, so every edit here is still attributable to validation. And the
Codex companion was SIGKILLed (exit 137, no output, no job registered) on three
attempts with the long round-2 focus text; the shorter shared-protocol focus text
ran fine and was used for rounds 2 and 3.

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 25 (Codex 3 + lens 20, one merged, one split) | 23 | 2 (one later superseded) | 0 |
| 2     | 5 | 5 | 0 | 0 |
| 3     | 3 | 3 | 0 | 0 |

## Applied

### Round 1
- PLAN.md:Decisions, Risks, Acceptance; TASK-001; TASK-002; TASK-008 — `verification=auto` is enforced as far as a network-free parser can: `auto` ⇒ `source=osm_poi` ∧ `role=main` ∧ `precision=building`, as a CHECK and a parser rule (round-1 #1, partial; remainder became round-2 #2)
- PLAN.md:Decisions, Acceptance; TASK-001; TASK-002; TASK-008 — exactly one `main` row per institution: partial unique index `WHERE role='main'`, parser rejection with line number, final-validation evidence (round-1 #2; the redundant plain index dropped, #24)
- TASK-008 — explicit evidence steps for the three measured geocoder failures, the out-of-polygon rejection, the unresolved-`main` list, and the review-decision → CSV → parser round trip (round-1 #3, merging Codex #3 and lens #12)
- PLAN.md:Decisions; TASK-002; TASK-003; TASK-007 — `data/` is copied into the Docker image and the CSV/polygon defaults are anchored to the package via `Path(__file__)`, never the CWD (round-1 #4)
- PLAN.md:Decisions; TASK-004; TASK-005 — `pending` rows are not written to the CSV; only decided rows are (round-1 #5)
- TASK-004; TASK-005 — the candidates `key` carries `address`, matching the table's UNIQUE tuple (round-1 #6)
- TASK-004; TASK-007 — one renderer writes every decided entry, so a seed re-run never drops a human decision (round-1 #7)
- PLAN.md:Decisions; TASK-004; TASK-005; TASK-006; TASK-007 — shared helpers live in `scripts/location_review/`, not a package named after the sibling module (round-1 #8)
- TASK-004; TASK-005 — `scripts/__init__.py` + pytest `pythonpath = ["."]`, scripts run with `python -m`, CI's ruff covers them (round-1 #9)
- TASK-001 — `tests/test_migrations.py`'s hard-coded revision chain shifts to `0010`/`0009`/`0008` (round-1 #10)
- PLAN.md:Decisions; TASK-004 — the `kind → amenity` family table, confirmed against the captured Overpass fixture (round-1 #11)
- PLAN.md:Decisions; TASK-001; TASK-002; TASK-005; TASK-006; TASK-008 — `street` precision dropped as unreachable; the reviewer can mark a hand-placed pin `approximate` (round-1 #12)
- TASK-002; TASK-004; TASK-005 — `write_file` lives in the loader module; the decision → row mapping lives once in `scripts/location_review/state.py` (round-1 #13)
- PLAN.md:Decisions; TASK-007 — the epic's `justfile` recipe is added to the parent `yasli/justfile` by TASK-007, outside the PR (round-1 #14)
- TASK-008 — epic update uses `link_plan.py`; epics live in this repo since d13317d (round-1 #15)
- RESEARCH.md; TASK-001; TASK-007; TASK-008 — `just db-psql` takes no arguments; one-shot queries use `docker compose exec -T postgres psql …` from the `yasli/` parent (round-1 #16)
- TASK-002; TASK-003; TASK-006; TASK-008 — the 77/15 count check moved to TASK-006 as a committed regression test; TASK-003's real run uses a hand-made sample (round-1 #17)
- PLAN.md:Risks; TASK-002 — Звездица added to the polygon test list (round-1 #18)
- PLAN.md:Scope — flagged-row estimate aligned to 25–35 (round-1 #19)
- RESEARCH.md; TASK-003 — the SQLite session fixture is module-local, not shared (round-1 #20)
- PLAN.md:Decisions; TASK-004 — flags are per row, any flag forces `pending`, out-of-polygon candidates stay visible but are never acceptable, rule 4 compares in-polygon candidates only (round-1 #21)
- RESEARCH.md — `openspec/` references point at the `yasli/` parent (round-1 #22)

### Round 2
- PLAN.md:Decisions, Risks, Acceptance; TASK-003; TASK-005; TASK-007; TASK-008 — the loader aborts before TRUNCATE when any institution lacks a `main` row; `--allow-incomplete` for local partial loads; a partial CSV can never replace the complete table (round-2 #1)
- PLAN.md:Scope, Decisions, Risks, Acceptance; TASK-002; TASK-004; TASK-005; TASK-006; TASK-007; TASK-008 — a committed provenance file (`data/institution_locations.provenance.json`), one all-pass entry per `auto` row, cross-checked by the parser; supersedes round-1 #25 (round-2 #2)
- PLAN.md:Decisions; TASK-005 — the candidates file is the commit point within a session; the CSV and provenance file are regenerated from it, with a fault-injection test for a crash between the writes (round-2 #3; refined by round-3 #1)
- TASK-001 — composite foreign key `(external_id, kind)` → `institutions` with `ON DELETE RESTRICT`; ingest upserts by that key and never deletes, so it cannot block `just be-ingest` (round-2 #4)
- TASK-003 — idempotence defined over business columns, excluding the surrogate `id` that plain `TRUNCATE` does not reset (round-2 #5)

### Round 3
- PLAN.md:Decisions, Acceptance; TASK-004; TASK-005; TASK-007; TASK-008 — lineage rule: the committed CSV + provenance are the record across sessions; the candidates file stores a `source_hash`, and a stale or missing candidates file rebuilds decisions from the committed files instead of reverting them (round-3 #1)
- PLAN.md:Decisions, Risks, Acceptance; TASK-002; TASK-003; TASK-004; TASK-007; TASK-008 — third pre-TRUNCATE guard: a `main` row's address must match the institution's current address through `normalise_address`; `--dry-run` runs the guards without loading; the seed script re-flags drifted rows `address_changed` (round-3 #2)
- TASK-001 — the surrogate PK is `BigInteger().with_variant(Integer, "sqlite")` so the SQLite loader tests can insert without an `id`; verified empirically (round-3 #3)

## Deferred

- (round-1 #23) The openspec §3.4 revision note calls this work "Phase 1.3"; it is 1.2 — outside this repo and this plan. Filed as **YAS-19**.
- (round-1 #25) Per-row seed provenance so an `auto` row can be re-checked offline — **superseded**: Codex pushed back in round 2 and it was applied as round-2 #2.

## Rejected

- None as findings. Codex's round-2 alternative for #2 — remove auto-verification and review every row by hand — was declined because it contradicts the 2026-09-14 revision Decision that introduced tiered auto-accept; the finding itself was applied through the provenance file.
