# Adversarial Validation — Round 2

**Run:** 2026-09-16 11:31 UTC
**Plan:** institution-profile-endpoint
**Status at start:** draft
**Reviewer:** codex
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not execute the plan unchanged: final validation is self-blocking and relies on database IDs the plan explicitly says are unstable. The round-1 applied fixes are sufficient, and its reject rationale is supported by the repository workflow.

Findings:
- [medium] Final-validation precondition includes its own incomplete checkbox (docs/artifacts/plans/institution-profile-endpoint/tasks/TASK-005-final-validation.md:15)
  TASK-005 first requires every task checkbox in PLAN.md to be ticked, which includes TASK-005 itself. The implementation workflow marks the final task complete only after its checks pass, so this condition cannot be truthfully satisfied without prematurely declaring validation complete.
  Recommendation: Require all prior or non-final task checkboxes to be ticked; mark TASK-005 complete only after its validation steps pass.
- [medium] Final validation hardcodes serial IDs that can change on re-ingest (docs/artifacts/plans/institution-profile-endpoint/tasks/TASK-005-final-validation.md:50-60)
  The nursery check assumes nursery/1 is id 66, and the following byte-identity procedure depends on similarly predetermined IDs. The plan's goal explicitly says database serials change on re-ingest. A valid database with reassigned IDs will therefore query the wrong institution or fail validation despite correct behavior. The same brittle assumption also appears in earlier task evidence.
  Recommendation: Resolve the ID for every natural key with a database query immediately before comparing the two routes, as already prescribed for the preschool; remove fixed IDs from TASK-001 through TASK-003 evidence as well.

Next steps:
- Correct TASK-005's checkbox precondition.
- Replace all live-evidence fixed IDs with IDs resolved from (kind, external_id).

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect
-->

Codex confirmed the round-1 applies as sufficient and the round-1 #1 reject
rationale as supported by the repository workflow; no push-back to answer.

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-005's first precondition ("all task checkboxes in PLAN.md are ticked") includes TASK-005's own box, so it cannot be truthfully satisfied before the task runs | med | apply | Inherited wording from the create-plan final-validation template; `implement-plan` ticks the final task's box only after its steps pass, so the precondition means TASK-001..004 — say so | TASK-005 |
| 2 | Live-evidence steps hard-code `institutions.id` serials (13, 66) that the plan's own Goal says are reassigned when the database is rebuilt | med | apply | The ids in RESEARCH.md are a 2026-09-16 observation, not a contract; every runtime step now resolves the id by natural key (SQL before the by-source route exists, the by-source body's own `id` once it does), which also makes the byte-identity check compare the same institution by construction | TASK-001; TASK-002; TASK-003; TASK-005; RESEARCH.md:Architecture Facts, Useful Commands |
