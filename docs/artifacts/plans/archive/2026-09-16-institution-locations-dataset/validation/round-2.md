# Adversarial Validation — Round 2

**Run:** 2026-09-15 05:38 UTC
**Plan:** institution-locations-dataset
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md
**Reviewer:** Codex (`/codex-local:adversarial-review`). Note: the first three attempts with the full round-2 focus text were SIGKILLed before the companion registered a job (exit 137, no output); the run below used the shorter shared-protocol focus text plus the sibling-plan exclusion.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not ship the plan yet. Round-1 fixed several concrete inconsistencies, but the revised plan still permits destructive partial loads, cannot substantiate its auto-verification claims, and specifies impossible cross-file atomicity.

Findings:
- [high] A half-reviewed CSV can successfully replace the complete production dataset (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-003-load-the-reference-file-idempotently-via-a-cli.md:27-34)
  The loader aborts for locations referencing unknown institutions, but a missing `main` row only appears in its success summary. The revised workflow deliberately omits pending rows from the CSV, making a half-reviewed file valid and loadable. An accidental invocation can therefore commit the TRUNCATE and replace a complete table with a partial dataset while exiting successfully, removing maps for affected institutions.
  Recommendation: Make the loader abort by default when any current institution lacks a `main` row. Keep deliberate unresolved institutions as explicit `precision=none` rows, and require an explicit `--allow-incomplete` option for development-only partial loads. Test that a partial CSV preserves the previous table.
- [high] Round-1's deferred auto-provenance risk still invalidates the acceptance claim (docs/artifacts/plans/institution-locations-dataset/PLAN.md:166-174)
  The plan admits that an in-polygon `osm_poi/main/building/auto` row can be forged and accepted, while its acceptance criteria still assert that every auto row passed all four rules. The structural checks added in round 1 cannot establish title uniqueness, settlement agreement, or geocoder distance, and the gitignored candidate state is unavailable for later review. Deferring evidence until a bad pin is reported is too reactive for the plan's primary wrong-location control.
  Recommendation: Commit a compact per-auto-row provenance manifest containing the candidate set or uniqueness result, OSM identity and amenity, polygon result, reverse settlement, rank-30 result and distance, then validate CSV auto rows against it offline. Alternatively, remove auto verification and require human review for every row.
- [high] Two independent files cannot be updated atomically with temp-file renames (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-005-build-the-location-review-tool.md:34)
  The review endpoint promises that both the candidates JSON and derived CSV are written atomically. Each rename is atomic individually, but a crash or disk failure between them leaves the files inconsistent. Restart can then show a decision missing from the CSV or regenerate the CSV from stale state, contradicting the persistence guarantee and potentially losing reviewed work.
  Recommendation: Define the candidates JSON as the sole authoritative commit point and regenerate the CSV deterministically on every startup and save. Document recovery ordering and add fault-injection tests for failure before, between, and after replacements.
- [medium] The no-foreign-key rationale ignores the stable natural key (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-001-add-the-institution-locations-table.md:109-113)
  The plan claims a real foreign key would depend on unstable serial IDs, but `institutions` already has a unique natural key and ingest upserts it. Without a composite foreign key, direct writes, future loaders, or maintenance operations can create orphan location rows that only this one loader would detect.
  Recommendation: Add a composite foreign key from `(external_id, kind)` to the existing unique institution key, with explicit restrictive delete/update behavior and migration tests. Retain the loader check for a friendlier pre-write error.
- [medium] The specified byte-identical reload cannot hold for the surrogate ID (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-003-load-the-reference-file-idempotently-via-a-cli.md:27-28)
  The table has an autoincrement surrogate ID, while the prescribed PostgreSQL operation is plain `TRUNCATE TABLE`, which does not restart its sequence. Reloading identical rows therefore assigns different IDs, so the explicit byte-identical-table acceptance criterion fails even though grouped business data remains the same.
  Recommendation: Define idempotence over business columns while excluding the explicitly unstable surrogate ID, or use `TRUNCATE ... RESTART IDENTITY` and test full-row equality on PostgreSQL. Align TASK-003 with PLAN.md's weaker 'same observable state' wording.

Next steps:
- Block implementation until incomplete loads fail safely and review-state recovery has a single authoritative commit point.
- Resolve round-1 triage item 25 now rather than accepting an unverifiable auto-verification claim.
- Add composite referential-integrity coverage and make the idempotence definition internally consistent.

## Triage

<!--
Verdict values: apply / defer / reject — see round-1.md.
Row 2 supersedes round-1 #25 (defer → apply). Codex's alternative for row 2
("remove auto verification and review every row") is rejected: it contradicts
the 2026-09-14 revision Decision that introduced tiered auto-accept.
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | A half-reviewed CSV can replace the complete dataset with exit 0 | high | apply | Direct consequence of round-1 #5 (pending rows omitted): the loader now aborts *before* TRUNCATE when any institution lacks a `main` row, with `--allow-incomplete` for local partial loads; deliberate blanks stay explicit `no_pin` rows, which count as present | PLAN.md:Decisions, PLAN.md:Risks, PLAN.md:Acceptance, TASK-003, TASK-005, TASK-007, TASK-008 |
| 2 | Round-1's deferred auto-provenance still invalidates the acceptance claim | high | apply | Supersedes round-1 #25: the seed script writes a compact committed provenance file (one all-pass entry per `auto` row: OSM id + amenity, title-match count, polygon result, settlements, rank-30 distance) and the parser rejects an `auto` row without a matching all-pass entry; the AC is narrowed to what that verifies, and the Risk is reworded as "self-attested". Removing auto-verification is rejected — it contradicts the 2026-09-14 revision Decision | PLAN.md:Scope, PLAN.md:Decisions, PLAN.md:Risks, PLAN.md:Acceptance, TASK-002, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008 |
| 3 | Two files cannot be updated atomically with temp-file renames | high | apply | The candidates file is the single commit point; the CSV and provenance file are regenerated from it on every save *and on startup*, with a fault-injection test for a crash between the writes | PLAN.md:Decisions, TASK-005 |
| 4 | The no-FK rationale ignores the stable natural key | med | apply | `institutions` has `uq_institutions_external_id_kind`; ingest upserts by it and never deletes (`pipeline.py` only counts disappeared rows), so a composite FK with `ON DELETE RESTRICT` cannot block `just be-ingest`; the Notes were reasoning about the serial `id` | TASK-001 |
| 5 | Byte-identical reload cannot hold for the surrogate id | med | apply | Plain `TRUNCATE` keeps the sequence (as `grao_loader` does); idempotence is defined over business columns, matching PLAN.md's "same observable state" | TASK-003 |
