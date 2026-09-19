# Validation Summary — institution-profile-endpoint

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-09-16

Plan risk is `medium`, so every round ran Codex alone. Round 3 returned
`approve` with no findings, so the run ended there. Three of the seven
findings came from Claude's grounding pass in round 1 (marked `(validator)`
in `validation/round-1.md`): every referenced symbol, fixture and helper was
verified against the current code, and the two behaviours the plan leans on —
a `Literal` path parameter giving 422 plus an OpenAPI enum, and a no-default
`X | None` field landing in `required` with `anyOf [X, null]` — were checked
at runtime against FastAPI 0.136 / Pydantic 2.13.

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 5 (Codex 2 + validator 3) | 4 | 0 | 1 |
| 2     | 2 | 2 | 0 | 0 |
| 3     | 0 | 0 | 0 | 0 |

## Applied

### Round 1
- TASK-005; PLAN.md:Scope, Risks; RESEARCH.md:Architecture Facts, Useful Commands — the final task runs `just be-load-locations` unconditionally before any curl and keeps its summary line as evidence; a row count cannot tell a stale load from the committed CSV, and `--dry-run` runs the guards without ever comparing the table to it (round-1 #2)
- TASK-005 — the last phase ticks "Every phase merged" itself; `archive-plan` has no epic-file step, so the plan's hand-off pointed at nothing (round-1 #3, validator)
- TASK-005; RESEARCH.md:Useful Commands — `just be-test` runs with `YASLI_TEST_DATABASE_URL` pointed at the throwaway `yasli_test`, never at `yasli`: `tests/test_migrations.py` downgrades to base and would wipe the 77 institutions the same task curls (round-1 #4, validator)
- RESEARCH.md:References; PLAN.md:Out of Scope — `openspec/…` paths point at the `yasli/` parent, where the files live (round-1 #5, validator)

### Round 2
- TASK-005 — the precondition reads "TASK-001 through TASK-004 ticked"; the final task's own box is ticked by `implement-plan` after its steps pass (round-2 #1)
- TASK-001; TASK-002; TASK-003; TASK-005; RESEARCH.md:Architecture Facts, Useful Commands — no live-evidence step hard-codes an `institutions.id`; ids are resolved by `(kind, external_id)` in SQL before the by-source route exists and from the by-source body once it does, so the byte-identity check compares the same institution by construction (round-2 #2)

## Deferred

- None.

## Rejected

- (round-1 #1) TASK-005 marks Epic 01 `Done` and unblocks Epic 02 before the PR merges — the create-plan final-validation template and EPICS.md §5 place exactly these edits in the final-validation task; they ride the PR and reach `staging` only through the merge, so the board is never ahead of the code; and `archive-plan` has no epic-file step to move them to (its step 5 is Linear-only), so the recommendation would leave the row never updated. Codex accepted the rationale in rounds 2 and 3. TASK-005 now states the merge semantics explicitly.
