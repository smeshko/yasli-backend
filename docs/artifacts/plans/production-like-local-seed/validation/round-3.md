# Adversarial Validation — Round 3

**Run:** 2026-09-20 (reviewer: Codex, `/codex-local:adversarial-review --wait --scope working-tree`)
**Plan:** production-like-local-seed
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md

> First invocation of this round produced no output (exit 0, empty stdout) — the
> known silent-death failure mode. Re-run with a shorter focus text (730 chars)
> succeeded; this is that run.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: D6 still permits stale routing edges, D8 is not pair-atomic, and final validation cannot prove the restamp guarantee. A TASK-006 dependency also remains missing.

Findings:
- [high] D6 still allows artifact-external routing state to survive verification (docs/artifacts/plans/production-like-local-seed/tasks/TASK-005-verify-the-seeded-database-and-refuse-half-done.md:15-40)
  Exact institution-set verification catches stale institutions but not stale `address_institutions` edges. Ingest only inserts missing edges and never deletes obsolete ones (`src/yasli/ingest/pipeline.py:564-630`), while kindergarten and preschool matching consumes every surviving edge (`src/yasli/services/matching.py:189-218`). On a dirty rerun, an obsolete edge between valid artifact institutions and addresses can therefore change `/api/match` while all planned checks pass; the sole routing check only requires non-empty results for one address.
  Recommendation: Either reconcile `address_institutions` to the snapshot during seed, refuse dirty routing state, or make verification compare the complete artifact-derived edge set and routing projection rather than only institution keys and one non-empty result.
- [high] Two sequential os.replace calls do not atomically publish an artifact pair (docs/artifacts/plans/production-like-local-seed/tasks/TASK-006-add-the-freeze-maintainer-command.md:23-28)
  A crash, process kill, filesystem error, or failed second `os.replace` after the first succeeds still leaves one new artifact beside one old artifact. The plan's claim that back-to-back replacements eliminate that window is false. Its planned interruption test raises during fixture derivation, before either replacement, so it cannot detect the remaining failure mode.
  Recommendation: Use a recoverable pair-publication protocol, such as versioned directories with one atomic pointer swap or rollback/journaling around the replacements. Add fault injection on the second replacement and assert that readers can only observe the old or new pair.
- [medium] The restamp validation can pass when restamp is disabled (docs/artifacts/plans/production-like-local-seed/tasks/TASK-008-final-validation.md:89-94)
  The sabotage changes district `02` to another valid non-null value, but TASK-005 checks only non-null coverage, valid presence, and the one Вапцаров routing case. Existing validation likewise rejects invalid codes, not incorrect valid assignments. Unless the corrupted sample includes that exact address, the non-null ratio is unchanged; corrupted kindergarten districts are not otherwise checked. A rerun without step 6 can therefore leave the corruption intact and still pass `verify`.
  Recommendation: Choose named rows with independently known expected districts—including the verified Вапцаров address and a specific kindergarten—or compare stored values with independently recomputed restamp results. Assert those exact values before and after runs with step 6 enabled and disabled.
- [medium] TASK-007 still lacks its TASK-006 dependency (docs/artifacts/plans/production-like-local-seed/tasks/TASK-007-document-the-seed-command-and-the-local-vs-production-gap.md:3)
  TASK-007 must document the `freeze` command, explain artifact refresh behavior, and execute every documented command, but it depends only on TASK-004 and TASK-005. Dependency-aware execution can therefore complete documentation before TASK-006 creates the command whose behavior the documentation must verify.
  Recommendation: Add TASK-006 to TASK-007's dependency declaration and mirror that dependency in PLAN.md.

Next steps:
- Resolve dirty-database catchment-edge reconciliation or make it a verification failure.
- Replace the claimed pair-atomic publication with a recoverable protocol and test second-replacement failure.
- Make the restamp sabotage target exact known values.
- Correct TASK-007's dependency list.

## Triage

**Round 3 produced `apply` rows, which the shared protocol treats as a stop-and-ask
signal rather than something to grind out. The plan owner was asked and chose
"apply all four, then stop". All four were applied; no fourth round was run.**

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Verifying the institution *set* still misses stale `address_institutions` edges, which change kindergarten and preschool routing on a dirty re-run | high | apply | Confirmed: `_insert_address_institutions` (`pipeline.py:564-630`) inserts with `on_conflict_do_nothing` and never deletes, and `_address_rows` (`matching.py:189-218`) joins the junction unscoped. This is the same class as round-2 #2 one level deeper — the round-2 fix closed the institution half and left the edge half open | TASK-005, TASK-008, PLAN.md:Risks, PLAN.md:Acceptance Criteria, DECISIONS.md:D6 |
| 2 | Two sequential `os.replace` calls are not an atomic pair publish; the round-2 claim that they leave "no window" is false | high | apply | Correct as stated, and it is a defect in a round-2 edit of mine rather than in the original plan. The window is now much smaller (two renames, not a whole database derivation) but it is not zero, and the planned interruption test raises *before* either replace, so it cannot catch the remaining case | TASK-006, TASK-008, PLAN.md:Risks, DECISIONS.md:D8 |
| 3 | The round-2 restamp sabotage case corrupts districts to a *valid but wrong* value, which none of TASK-005's checks detect | medium | apply | Confirmed: TASK-005 checks non-null coverage, valid code membership and one routing case. A valid-but-wrong district passes all three, so the case cannot prove what it claims. Also a defect in a round-2 edit of mine | TASK-005, TASK-008 |
| 4 | TASK-007 documents and executes `freeze` but does not depend on TASK-006 | medium | apply | Confirmed at TASK-007:3 (`Depends on: TASK-004,TASK-005`). Round 1 fixed the same class of omission on TASK-006 without sweeping the other task files | TASK-007, PLAN.md:Tasks |
