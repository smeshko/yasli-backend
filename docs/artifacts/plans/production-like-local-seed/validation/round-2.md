# Adversarial Validation — Round 2

**Run:** 2026-09-20 (reviewer: Codex, `/codex-local:adversarial-review --wait --scope working-tree`)
**Plan:** production-like-local-seed
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the D6 and D8 revisions still allow successful publication of incorrect state, TASK-008 does not prove the sabotage criterion, and the plan gives contradictory load orders.

Findings:
- [high] D8's guard cannot keep the artifacts paired (docs/artifacts/plans/production-like-local-seed/tasks/TASK-006-add-the-freeze-maintainer-command.md:23-28)
  The guard validates before two separate writes, so it cannot prevent the snapshot write succeeding and the fixture write failing; the resulting new-snapshot/old-fixture pair can contain exactly the overlap D8 is intended to prevent. There is also no valid transition when a former legacy key reappears in the snapshot: checking against the committed fixture blocks full and snapshot-only refreshes, while deriving the candidate fixture first makes the overlap check tautological. The committed-data test only detects corruption later and does not prevent the maintainer command from leaving it on disk.
  Recommendation: Stage both candidate artifacts, validate their schemas and disjointness, then publish them with rollback on a failed second replacement; preferably seed and verify the staged pair before publication. Remove or tightly constrain single-artifact modes. D8's rejection rationale should be reversed or replaced with an equally strong transactional publication design.
- [high] D6 permits a successful seed that changes user-visible routing (docs/artifacts/plans/production-like-local-seed/tasks/TASK-005-verify-the-seeded-database-and-refuse-half-done.md:15-35)
  Extras are only warnings, but matching selects every nursery with the address district (`matching.py:222-249`). A stale or unrelated extra nursery surviving a dirty rerun therefore appears in `/api/match`, while TASK-005 merely checks that all three kinds are non-empty. The seed can exit 0 while answering the headline routing query differently from the committed artifacts or production. Reporting the extra row does not satisfy TASK-005's stated invariant that success means queries are not silently wrong.
  Recommendation: Reverse D6 by refusing a non-empty/extra-containing database by default, with an explicit dirty override if needed, or make artifact-external institutions a verification failure. Also compare the routing result to the artifact-derived expected projection instead of checking only non-emptiness.
- [medium] TASK-008 still does not cover the 'any seed step' criterion (docs/artifacts/plans/production-like-local-seed/tasks/TASK-008-final-validation.md:52-74)
  The isolated sabotage cases cover ГРАО, locations, legacy data, and snapshot ingest, but omit migration and final restamping. The generic instruction to walk acceptance criteria is not reproducible sabotage evidence. Restamp is especially problematic: on a clean database the preceding ingest already runs gated stamping, so skipping the final restamp may still pass verification. The plan therefore cannot demonstrate its claim that sabotaging any one step is detected.
  Recommendation: Add an unmigrated-database case proving the migration step, and a dirty database with deliberately wrong existing district values proving the non-gated restamp corrects them. If restamp is intentionally redundant for a clean seed, narrow PLAN.md's acceptance criterion from 'any one seed step' to independently required effects.
- [medium] PLAN.md specifies the opposite of the load-bearing execution order (docs/artifacts/plans/production-like-local-seed/PLAN.md:26-28)
  The top-level scope orders snapshot ingest before ГРАО, while TASK-004 requires ГРАО before ingest and states that this ordering is load-bearing because ingest performs gated district stamping. An implementer following PLAN.md can build a seed that misses those stamps and contradicts the task's asserted step-order test.
  Recommendation: Change the top-level sequence to migration → ГРАО → snapshot ingest → legacy institutions → locations → restamp, matching TASK-004, and keep one canonical ordering across all plan documents.

Next steps:
- Replace D8's validation-only publication with staged, recoverable pair publication.
- Make dirty-database extras blocking by default or explicitly weaken the production-like success guarantee.
- Extend TASK-008 for migration and restamp sabotage, then correct PLAN.md's seed order.


## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | D8's guard runs before two separate writes, so a crash between them still leaves a mismatched pair; and no valid transition is defined for a legacy key that reappears in the snapshot | high | apply | The crash window is real. The "no valid transition" half is overstated — a full freeze, or dropping the key, resolves it — but the spec never said so. User chose **amend, not reverse**: keep the guard, write both artifacts to temp and `os.replace` both at the end, and name the remedy in the error. Full stage-and-swap rejected again for the reasons in D8 | TASK-006, DECISIONS.md:D8 |
| 2 | D6's extras-as-warning lets a successful seed change user-visible routing: `_district_rows_for_kind` selects every nursery in the district, with no artifact scoping | high | apply | The routing consequence is confirmed at `matching.py:222-249` and is new information D6 did not weigh. User's call: **keep D6** (the seed still runs against a dirty database) but make `verify` **fail** on institutions outside the snapshot∪fixture union. Reversing D6 rejected a second time — it was already declined as D6 Option 2 | TASK-005, TASK-008, PLAN.md:Acceptance Criteria, DECISIONS.md:D6 |
| 3 | TASK-008's sabotage cases omit migration and restamp, so the "any one seed step" criterion is not demonstrated — and on a clean seed restamp is near-redundant because ingest already ran the gated passes | medium | apply | Confirmed at `pipeline.py:673-674`: ingest ends with `stamp_*_unmatched`, so skipping the final restamp on a clean database changes nothing observable. Both the missing cases and the over-broad criterion are real | TASK-008, PLAN.md:Acceptance Criteria, TASK-004 |
| 4 | PLAN.md's Scope orders ingest before ГРАО, the reverse of the order TASK-004 calls load-bearing | medium | apply | Confirmed by reading both. Pre-existing contradiction that round 1 missed; an implementer following Scope would build the exact failure YAS-21 was filed about | PLAN.md:Scope |
