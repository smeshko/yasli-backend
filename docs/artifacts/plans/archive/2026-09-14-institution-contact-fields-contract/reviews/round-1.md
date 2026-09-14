# Adversarial Review — Round 1

**Run:** 2026-09-14 11:29 UTC
**Branch:** feature/institution-contact-fields-contract
**Base:** main
**Commits reviewed:** e6508a2..87b0205
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
# Codex Adversarial Review

Target: branch diff against main
Verdict: needs-attention

Do not ship yet: the contract accepts arbitrary-length contact strings, but ingest writes them into bounded VARCHAR columns, allowing one oversized source value to abort the entire snapshot transaction.

Findings:
- [high] Unbounded contract fields can crash the whole ingest on database length limits (src/yasli/snapshot_contract/models.py:59-62)
  The new contact fields are validated only as non-empty strings and have no maximum length, while the persistence model and migration constrain them to VARCHAR(128) for phone and VARCHAR(256) for email, director, and website. A legitimate or malformed source value exceeding those limits will pass snapshot validation, reach the bulk upsert, and cause a PostgreSQL string-too-long error; because ingest runs as one transaction, this can prevent all institutions in that snapshot from being loaded. The tests explicitly require values to be persisted verbatim but do not exercise the database boundary.
  Recommendation: Align the contract limits with the database using Field(max_length=...) and add boundary/over-limit tests, or change the columns to an appropriately unbounded Text type with an explicit normalization/size policy. Ensure an over-limit record cannot silently abort the complete ingest.

Next steps:
- Add validation and integration tests for values at and above each storage limit.
- Decide whether truncation/rejection/quarantine is the intended behavior for oversized source values.
```

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Unbounded contract strings vs `VARCHAR(128/256)` columns can abort the whole ingest transaction | low | reject | Explicitly resolved in RESEARCH.md "Uncertainty" and TASK-002 Notes: overflow must fail loudly rather than truncate, and phase 1.2's live `sc-refresh` surfaces it pre-production; widths are far above observed values, and the pre-existing `name`/`address` columns follow the identical unbounded-contract/bounded-column convention. Adding `max_length` would still reject the whole snapshot (contract validation is also all-or-nothing), so it only relocates the error while forcing a scraper-schema change outside this phase. | |
