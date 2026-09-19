# Adversarial Validation — Round 1

**Run:** 2026-09-16 11:22 UTC
**Plan:** institution-profile-endpoint
**Status at start:** draft
**Reviewer:** codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not execute this plan unchanged: its final gate can validate stale location data and marks dependent work ready before the required merge/CI lifecycle completes.

Findings:
- [high] Final validation closes the epic before its own merge requirement is satisfied (docs/artifacts/plans/institution-profile-endpoint/tasks/TASK-005-final-validation.md:82-90)
  TASK-005 sets Epic 01 to Done and unblocks Epic 02 while deliberately leaving “Every phase merged” unchecked. This conflicts with EPICS.md’s workflow: each phase lands via a PR, and the row becomes Done when the last phase merges. If validation runs before create-pr/archive-plan, project state will falsely advertise the dependency as complete and allow Epic 02 to start against unmerged code. Verdict: apply — correct TASK-005-final-validation.md.
  Recommendation: Apply — keep phase/epic status In progress during TASK-005; move Done, the epic-level merged criterion, and Epic 02 unblocking to the post-merge/archive step in TASK-005-final-validation.md.
- [medium] Row counts cannot prove the validation database contains the committed location dataset (docs/artifacts/plans/institution-profile-endpoint/tasks/TASK-005-final-validation.md:23-28)
  The task calls the local data “current” after checking only migration version and counts. An older database containing 94 different location rows passes this gate, so curls and ETag evidence may validate stale coordinates or branches rather than data/institution_locations.csv. The loader is transactional and is the authoritative way to install the committed dataset; restricting it to an empty table leaves this failure undetected. Verdict: apply — strengthen TASK-005-final-validation.md and align RESEARCH.md’s validation command.
  Recommendation: Apply — in TASK-005-final-validation.md require loading the committed CSV before runtime checks, or compare every persisted location row to it; update RESEARCH.md if its dry-run command cannot prove database equality.

Next steps:
- Revise TASK-005 so epic completion and dependency promotion happen only after merge.
- Make committed-CSV-to-database equality an explicit, observable final-validation gate.

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-005 marks Epic 01 `Done` and unblocks Epic 02 before the PR merges; move those steps to a post-merge/archive step | high | reject | The create-plan final-validation template and EPICS.md §5 place exactly these edits in the final-validation task; they ride the PR and reach `staging` only through the merge, so the board is never ahead of the code; and `archive-plan` has no epic-file step to move them to (its step 5 is Linear-only) — the recommendation would leave the row never updated. The one real gap it exposed is #3 | — |
| 2 | Row counts cannot prove the local table holds the committed CSV; TASK-005 accepts any 94 rows | med | apply | The loader is idempotent (three guards, then TRUNCATE + INSERT in one transaction) and `--dry-run` runs the guards without ever comparing the table to the CSV, so an unconditional load before the curls, with its summary line captured, is the only observable gate | TASK-005; PLAN.md:Scope, Risks; RESEARCH.md:Architecture Facts, Useful Commands |
| 3 | (validator) TASK-005 hands "Every phase merged" to `archive-plan`, which has no epic-file step — the criterion would never be ticked | low | apply | Grounded in `archive-plan`'s SKILL.md (step 5 rolls up Linear only); the create-plan template says the last phase ticks the remaining epic-level criteria, and the tick lands with the very merge that makes it true | TASK-005 |
| 4 | (validator) TASK-005 tells the implementer to set `YASLI_TEST_DATABASE_URL` without naming a database; `tests/test_migrations.py` downgrades to base | med | apply | Pointing it at `yasli` would wipe the 77 institutions the same task's curls depend on; the throwaway `yasli_test` database exists for exactly this | TASK-005; RESEARCH.md:Useful Commands |
| 5 | (validator) `openspec/…` references are written as if they lived in this repo; they are in the `yasli/` parent | low | apply | Same fix the previous plan applied (its round-1 #22); a wrong path in RESEARCH.md sends the implementer to a file that does not exist | RESEARCH.md:References; PLAN.md:Out of Scope |

Findings #3–#5 were added by Claude's grounding pass during triage (the plan's
symbols, fixtures and helpers were all verified against the current code; a
`Literal` path parameter and no-default nullable fields were checked at
runtime and behave as the plan says) and are marked `(validator)`.
