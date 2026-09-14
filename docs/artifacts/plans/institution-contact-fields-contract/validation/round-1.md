# Adversarial Validation — Round 1

**Run:** 2026-09-14 11:00 UTC
**Plan:** institution-contact-fields-contract
**Status at start:** draft
**Reviewer:** codex (round-1 invocation with the skill's focus text crashed with exit 137; re-run with the same focus condensed to ASCII). Findings #3–#6 were added by Claude's grounding pass during triage and are marked as such.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not ship the plan unchanged: its schema-drift evidence is internally contradictory, and final validation does not explicitly prove every acceptance criterion.

Findings:
- [high] Schema-drift acceptance criteria contradict the stated two-repo rollout (docs/artifacts/plans/institution-contact-fields-contract/tasks/TASK-004-final-validation.md:22-24)
  The plan says the backend intentionally moves one phase ahead while the scraper remains unchanged, and TASK-001 explicitly requires the regenerated fixture to contain the four properties on both sides. However, TASK-004 says the same diff should show the four properties present only on the backend side. The drift test compares the backend model to the hand-edited fixture, so it cannot independently prove the scraper is still behind; the proposed evidence therefore cannot satisfy both claims and can falsely pass if the fixture is edited incorrectly.
  Recommendation: Apply: revise PLAN.md, TASK-001, and TASK-004 so the fixture's role and expected diff are unambiguous; require an independent comparison against the actual scraper schema, or explicitly defer that check to phase 1.2.
- [medium] Final validation omits explicit proof of unchanged re-ingest behavior (docs/artifacts/plans/institution-contact-fields-contract/tasks/TASK-004-final-validation.md:15-19)
  The PLAN acceptance criteria require re-ingesting the same snapshot twice to report institution rows as unchanged, because the new fields must participate in change detection. TASK-003 specifies a test for this, but TASK-004's final-validation steps never run or capture a two-run summary; full tests alone do not produce the required production-facing evidence, and the listed real R2 run only checks success and NULL phone values.
  Recommendation: Apply: update TASK-004-final-validation.md to run the current and contact-bearing snapshots twice and capture the second-run institution count as unchanged, including a changed-contact case proving updates are not misreported.

Next steps:
- Resolve the schema rollout/evidence contradiction before implementation.
- Add explicit final-validation evidence for idempotency and contact-field change detection.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-001 expects the fixture to differ from the scraper schema only by `minItems`; TASK-004 expects the four new properties on the backend side only — contradictory | high | apply | The scraper is unchanged until 1.2, so TASK-004 is right and TASK-001's acceptance/evidence is wrong; independent comparison already lives in phase 1.2 (PLAN.md Risks) || TASK-001:Acceptance+Evidence |
| 2 | Final validation never demonstrates the "re-ingest twice → unchanged" criterion (nor a changed-contact → `updated` case) | med | apply | PLAN.md AC4 has no Evidence step in TASK-004 || TASK-004:Steps |
| 3 | (Claude) No local-file ingest path exists: `pipeline.run(r2_client=...)` only reads `snapshots/varna/latest.json` via `r2.get_object`; `sc-snapshot-local` writes a file but nothing ingests it. The obvious workaround — uploading the edited file to R2 — would overwrite the production snapshot | high | apply | TASK-003 Notes and TASK-004 step prescribe a mechanism that doesn't exist; specify a stub client passed to `pipeline.run` against the local DB, and forbid R2 writes || TASK-003:Notes; TASK-004:Steps |
| 4 | (Claude) Test infra misdescribed: ingest tests use a testcontainers Postgres + `_put_snapshot` (moto R2) + `tests/ingest/fixtures/snapshot_v2_minimal.json`, not an "in-memory session fixture" or a conftest snapshot factory; and they `pytest.skip` without Docker, so a green `be-test` can hide them | med | apply | Grounded in `tests/ingest/conftest.py` and `tests/ingest/test_pipeline.py`; evidence must show ingest tests ran, not skipped || TASK-001:Files; TASK-003:Evidence+RED; TASK-004:Steps |
| 5 | (Claude) `tests/test_migrations.py::test_round_trip_upgrade_downgrade_upgrade` hard-codes head `"0008"` and `downgrade -2` → `"0006"`; adding 0009 breaks it and shifts what `-2` means | med | apply | TASK-002 says only "the up/down cycle covers the new revision" — the concrete edits are unstated || TASK-002:Files+RED |
| 6 | (Claude) `uv run alembic check` needs a live DB and its current baseline (pre-0009) is unverified, so pre-existing drift could be misread as this task's | low | apply | Cheap to pin: run it against the local DB before and after, compare || TASK-002:Acceptance+Evidence |
