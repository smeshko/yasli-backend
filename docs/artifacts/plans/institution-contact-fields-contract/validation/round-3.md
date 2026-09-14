# Adversarial Validation — Round 3

**Run:** 2026-09-14 11:20 UTC
**Plan:** institution-contact-fields-contract
**Status at start:** draft
**Reviewer:** codex
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Needs attention: the R2 stub rejection is correctly triaged, and the NULL-count fix is present, but final API compatibility evidence remains non-reproducible and can produce a false pass.

Findings:
- [medium] API byte-identity check has no pinned baseline (docs/artifacts/plans/institution-contact-fields-contract/tasks/TASK-004-final-validation.md:32-33)
  TASK-004 requires diffing responses against “the same two responses from main,” but it does not specify a commit, database snapshot, request parameters, or captured baseline artifacts. A main-branch response can differ because of data refreshes, ordering, serialization, or environment state, so equality/non-equality cannot reliably establish that this plan introduced no API change. The existing key-set tests only prove shape, not byte identity. Apply: define a pinned baseline revision and fixture/database, or commit the before-response artifacts and compare against those exact bytes.
  Recommendation: Apply; revise TASK-004 and preferably PLAN.md to require a reproducible pre-change response baseline with identical database contents and request conditions.

Next steps:
- Keep round-2 finding #1 rejected: src/yasli/ingest/r2.py:77-95 confirms the documented stub shape.
- Apply the baseline requirement before implementation and final sign-off.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | API byte-identity check has no pinned baseline (commit, DB contents, requests) | med | apply | Real gap — a refreshed R2 snapshot between runs would make the diff meaningless. Round 3 still yielded an apply, so per protocol the user was asked; they chose "apply and stop" (no round 4) | TASK-004:Steps; TASK-001:RED |
