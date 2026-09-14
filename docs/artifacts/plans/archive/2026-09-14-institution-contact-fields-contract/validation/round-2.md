# Adversarial Validation — Round 2

**Run:** 2026-09-14 11:10 UTC
**Plan:** institution-contact-fields-contract
**Status at start:** draft
**Reviewer:** codex
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not ship the plan yet: the prescribed local contact-bearing validation cannot call the actual ingest R2 seam, and final evidence still does not prove the full NULL-state acceptance criterion.

Findings:
- [high] The local stub demo uses the wrong R2 client interface (docs/artifacts/plans/institution-contact-fields-contract/tasks/TASK-003-map-contact-fields-through-ingest.md:77-84)
  The plan says the stub should expose `get_object(Bucket=, Key=)` and return the shape used by an SDK client, but `pipeline.run()` delegates to `r2.get_object(LATEST_KEY, client=client)`, where `r2` is the project wrapper and `client` is only passed through. A stub implementing the documented interface will therefore either never be called or fail on the unexpected `client` keyword/positional contract, making the only safe contact-bearing validation path unworkable. Apply: document and test the actual `yasli.r2.get_object` seam (or require a stub matching its exact signature), and update the one-off example in TASK-003 and TASK-004.
  Recommendation: Specify the exact callable patched or stubbed, including its arguments and return type, and add a small executable test/demo proving `pipeline.run(r2_client=stub)` reads the edited local bytes without contacting R2.
- [medium] Final validation checks only phone for the all-four-NULL acceptance criterion (docs/artifacts/plans/institution-contact-fields-contract/tasks/TASK-004-final-validation.md:17-20)
  PLAN.md requires that ingesting the current production snapshot leaves all four new columns NULL, but TASK-004 only captures `count(*) WHERE phone IS NOT NULL`. A production snapshot could contain email, director, or website while this evidence still passes, so the stated acceptance criterion is not actually verified. The contract's fields are independent and the plan explicitly treats website as conditionally populated, making this omission observable rather than theoretical. Apply: change the validation query to report all four columns (or a combined count proving none is non-NULL), and add the same assertion to the ingest test.
  Recommendation: Query all four contact columns and assert each count is zero; mirror that assertion in tests/ingest/test_pipeline.py for the field-omitting fixture.

Next steps:
- Correct the local R2 stub instructions against the actual `r2.get_object` implementation.
- Extend NULL-state evidence and tests to cover phone, email, director, and website.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Local stub demo uses the wrong R2 client interface | high | reject | Demonstrably incorrect: `r2.get_object(key, *, client=...)` assigns `s3 = client` and calls `s3.get_object(Bucket=..., Key=...)["Body"].read()` (`src/yasli/ingest/r2.py:77-95`) — the plan's stub shape is right. Wording in TASK-003 Notes was tightened to spell out the exact return shape and the `R2_BUCKET` env dependency, no change in approach | |
| 2 | Final validation checks only `phone` for the "all four columns NULL" criterion | med | apply | AC1 names all four columns; `website` is conditionally populated at the source, so a phone-only check is a real gap | TASK-004:Steps; TASK-003:Acceptance+Evidence |
