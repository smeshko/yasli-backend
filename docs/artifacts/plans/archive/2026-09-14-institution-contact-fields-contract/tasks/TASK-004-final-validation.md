# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for institution-contact-fields-contract`

## Goal

Confirm the plan is fully implemented and production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] `just be-lint` passes with no issues
- [ ] `just be-test` passes in full, with Docker running — confirm the
      `tests/ingest/` and `tests/test_migrations.py` tests report `PASSED`, not
      `SKIPPED` (`uv run pytest -rs` lists skips; there must be none from those)
- [ ] `just db-reset && just be-ingest` against the real R2 snapshot succeeds;
      capture the summary line and
      `SELECT count(phone), count(email), count(director), count(website) FROM institutions`
      → `0 | 0 | 0 | 0` (AC: current snapshot ingests unchanged, all four columns NULL)
- [ ] Run `just be-ingest` a second time; capture the summary showing every
      institution row `unchanged` (AC: re-ingest is `unchanged`)
- [ ] Ingest a hand-edited local snapshot carrying all four fields — via the
      stub R2 client described in TASK-003's Notes, **never** by uploading to
      R2; show the count non-zero, spot-check one row's values against the
      edited file (AC: stored verbatim), and ingest it again to show those rows
      `unchanged`. Then change one institution's `phone` in the file, ingest,
      and show that row counted `updated` with the new value
- [ ] Show an empty-string contact value is rejected: ingest a copy of the file
      with `"phone": ""` and capture the validation error and non-zero exit;
      the DB still holds no `""` (`SELECT count(*) FROM institutions WHERE phone = ''` → `0`)
      (AC: empty string rejected)
- [ ] API bodies byte-identical, against a pinned baseline. **Before** the
      first code commit (on the plan's base commit — record its SHA), run
      `just db-reset && just be-ingest`, start `just be-api`, and save
      `curl -s localhost:8000/api/institutions` and
      `curl -s localhost:8000/api/institutions/<id>` (record the `<id>`) to the
      scratchpad. At final validation, on the branch: `just db-reset && just be-ingest`
      against the **same** R2 snapshot (confirm `scraped_at` in the summary
      matches the baseline run), repeat the same two requests, and `diff` — no
      output. If the R2 snapshot was refreshed in between, re-capture the
      baseline from the recorded SHA (`git worktree`) rather than accept a diff
- [ ] `diff ../scraper/schemas/snapshot.v2.schema.json tests/snapshot_contract/fixtures/snapshot.v2.schema.json`
      shows the four new properties present only on the backend side, plus the
      pre-existing `minItems` divergence, and nothing else
- [ ] `PLAN.md` acceptance criteria all met, each with its Evidence produced —
      no criterion ticked on "the code looks right"

### Epic update

`link_plan.py` cannot be used here: it expects the epic and the plan under one
project root, and this repo's plans live in `backend/` while the epics live in
the `yasli/` parent. Edit both sides by hand.

- [ ] Tick phase 1.1's `### Acceptance criteria` in
      `../../../../epics/01-institution-data-foundation.md`
- [ ] Set that phase's `**Plan**:` line to
      `**Plan**: [institution-contact-fields-contract](../../../backend/docs/artifacts/plans/institution-contact-fields-contract/PLAN.md) · status: done`
- [ ] Promote Epic 1's row in `../../../../epics/EPICS.md` from
      `Ready for dev` to `In progress`
- [ ] Confirm phase 1.2 is now unblocked — note in the PR description that the
      backend must be **deployed**, not merely merged, before the scraper phase
      ships
