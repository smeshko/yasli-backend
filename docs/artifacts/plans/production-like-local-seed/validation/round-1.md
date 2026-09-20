# Adversarial Validation — Round 1

**Run:** 2026-09-19 (reviewer: Codex, `/codex-local:adversarial-review --wait --scope working-tree`)
**Plan:** production-like-local-seed
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the core nursery-routing design contradicts current code, several validation procedures cannot prove their stated criteria, and freeze can create inconsistent seed artifacts.

Findings:
- [high] [apply] Existing restamping cannot populate the legacy nurseries (docs/artifacts/plans/production-like-local-seed/tasks/TASK-003-seed-the-18-legacy-nursery-institutions.md:14-37)
  Verdict: apply. Rationale: the fixture deliberately leaves `district_code` NULL and relies on `restamp-districts`, but `district_stamp.py:265-272,287-292,477-482` explicitly excludes nurseries. Matching requires their `Institution.district_code`, and existing validation treats NULL nursery districts as a hard failure. The planned seed therefore cannot satisfy its headline routing criterion.
  Recommendation: Add validated production `district_code` values to the fixture and loader, or explicitly design and test a new nursery-stamping path. Update PLAN.md, RESEARCH.md, DECISIONS.md, TASK-003, TASK-004, TASK-005, and TASK-008.
- [high] [apply] The half-done tests preserve the supposedly skipped data (docs/artifacts/plans/production-like-local-seed/tasks/TASK-008-final-validation.md:13-58)
  Verdict: apply. Rationale: TASK-008 first performs a successful seed, then says to "re-seed" while skipping ГРАО or locations. Omitting those loaders does not remove their existing rows, so verification can observe the previous 47k/94 rows and pass. More broadly, TASK-008 lacks explicit checks for the address-stamp ratio, standalone verification on a never-seeded database, and sabotage of every required effect; its generic assertion that all criteria were met is not reproducible evidence.
  Recommendation: Add a criterion-by-criterion validation matrix. Reset to an empty database or explicitly remove each step's effects before every sabotage case; cover snapshot, legacy, ГРАО, locations, migration/precondition, and restamp behavior, plus never-seeded verification and the measured district ratio. Update TASK-008 and TASK-005.
- [high] [apply] Freeze can publish a mismatched artifact pair (docs/artifacts/plans/production-like-local-seed/tasks/TASK-006-add-the-freeze-maintainer-command.md:14-41)
  Verdict: apply. Rationale: the workflow writes the snapshot separately from deriving the legacy fixture and permits `--snapshot-only`. A DB failure can leave artifacts from different epochs, while snapshot-only refresh can make the old legacy fixture overlap newly live snapshot rows, causing the legacy upsert to overwrite current data. The empty-diff guard does not protect against a wrong or partial database producing a destructive non-empty shrink.
  Recommendation: Stage both outputs, validate both schemas and zero natural-key overlap, seed/verify from the staged pair, then replace them together. Remove `--snapshot-only` or make it reject overlap, and require an explicit override for suspicious fixture shrinkage. Update TASK-006, TASK-003, PLAN.md risks, and DECISIONS.md.
- [medium] [apply] The API parity check does not match the current endpoint contract (docs/artifacts/plans/production-like-local-seed/tasks/TASK-008-final-validation.md:28-32)
  Verdict: apply. Rationale: `routes/match.py:79-85` requires an `address_id`; the endpoint cannot be called using the displayed address string. Local and production surrogate address and institution IDs need not match, so "the same call" and an unqualified full-payload comparison are neither executable nor stable evidence of semantic parity.
  Recommendation: Specify a natural-key lookup that resolves the address independently in each database, then compare a normalized projection such as district and sorted `(institution_kind, external_id, reception_kind)` results. Update PLAN.md, TASK-005, and TASK-008.
- [medium] [apply] Exact 18/95 checks contradict both refresh and dirty-database policy (docs/artifacts/plans/production-like-local-seed/tasks/TASK-005-verify-the-seeded-database-and-refuse-half-done.md:13-20)
  Verdict: apply. Rationale: runtime verification requires exactly 95 institutions, while `freeze` intentionally regenerates a variable production-minus-snapshot set and D6 permits extra stale rows to survive dirty reruns. A legitimate snapshot addition/removal or one pre-existing extra row therefore makes an otherwise valid seed fail verification.
  Recommendation: Keep 77/18/95 as current-artifact regression evidence for a clean seed, but derive runtime expectations from the disjoint union of the committed snapshot and legacy fixture. Either warn and name unrelated extras or reverse D6 and refuse dirty databases. Update DECISIONS.md, TASK-003, TASK-004, TASK-005, TASK-006, and TASK-008.
- [medium] [apply] TASK-006 omits the task that creates its package and CLI (docs/artifacts/plans/production-like-local-seed/tasks/TASK-006-add-the-freeze-maintainer-command.md:1-23)
  Verdict: apply. Rationale: TASK-006 depends only on TASK-002 and TASK-003 but adds `yasli.seed.freeze` and modifies `yasli.seed.__main__`, both of which are created by TASK-004. Dependency-aware execution can start TASK-006 before its target package exists.
  Recommendation: Add TASK-004 as a dependency of TASK-006 and reflect that dependency in PLAN.md.

Next steps:
- Resolve the nursery district-source design before implementation.
- Rewrite TASK-008 as explicit, isolated validation cases mapped one-to-one to PLAN.md acceptance criteria.
- Make freeze publish and validate the snapshot and legacy fixture as one coherent artifact set.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | `restamp-districts` can never stamp the 18 legacy nurseries — `district_stamp` excludes `kind='nursery'` by design, and `match_data_validation` counts `nursery_without_district` as a hard failure | high | apply | Confirmed at `district_stamp.py:270,291,481` and `match_data_validation.py:119`. Nursery district is API-sourced, so the fixture must carry `district_code` itself. Building a nursery stamping path is rejected — it would undo a deliberate architectural exclusion | TASK-003, TASK-004, TASK-005, TASK-008, PLAN.md:Research Summary, PLAN.md:Risks, RESEARCH.md, DECISIONS.md:D4+D7 |
| 2 | TASK-008's "re-seed with step X skipped" sabotage cases do not remove the rows a prior successful seed already loaded, so `verify` can pass on evidence that proves nothing | high | apply | Real: the ГРАО and locations loaders TRUNCATE-and-reload, so *skipping* them preserves the previous run's rows. Also adds the missing never-seeded and district-ratio cases. The "criterion matrix" restructure is presentation, applied in substance not in ceremony | TASK-008, TASK-005 |
| 3 | `freeze` writes the two artifacts independently, so a partial run or `--snapshot-only` can commit a mismatched pair whose legacy rows overwrite live snapshot rows | high | apply | Real hazard. Scoped by the user to a validation guard: zero-key-overlap check (including on `--snapshot-only`) plus a shrink guard, rather than a full stage-and-swap pipeline — TASK-003's committed-data test is the second net | TASK-006, PLAN.md:Risks |
| 4 | `GET /api/match` is specified with an address string, but the endpoint takes `address_id`; and local/production surrogate ids do not correspond, so "compare the payloads" is not executable | medium | apply | Confirmed at `routes/match.py:80` (`address_id: int = Query(..., ge=1)`). Needs a natural-key address lookup per database and a normalised projection to compare | PLAN.md:Acceptance Criteria, TASK-005, TASK-008 |
| 5 | `verify` asserting exactly 95 institutions contradicts D6 (stale rows survive a dirty re-run) and breaks whenever `freeze` legitimately changes the artifact contents | medium | apply | The count half is right — derive expectations from the committed artifacts and name extras as a warning. Codex's alternative of reversing D6 to refuse dirty databases is **rejected**: D6 was explicitly chosen by the user | TASK-005, TASK-008, DECISIONS.md:D6 |
| 6 | TASK-006 creates `yasli/seed/freeze.py` and edits `yasli/seed/__main__.py`, both of which TASK-004 creates, but does not depend on TASK-004 | medium | apply | Confirmed by reading both task files; a straight dependency omission | PLAN.md:Tasks, TASK-006 |
