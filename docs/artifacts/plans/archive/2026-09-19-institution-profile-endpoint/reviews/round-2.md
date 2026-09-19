# Adversarial Review — Round 2

**Run:** 2026-09-19 04:36 UTC
**Reviewer:** Codex (`/codex-local:adversarial-review --wait --scope branch --base staging <focus>`)
**Branch:** feature/yas-8-institution-profile-endpoint
**Base:** staging
**Commits reviewed:** a242f54879fd..90eddb534146
**Prior rounds in scope:** reviews/round-1.md

**Focus text passed:** Second pass, round-1 approve treated as a hypothesis to falsify. Directed at: the LEFT OUTER JOIN on the list query (row count, ordering); `Decimal` → `float` for lat/lon; branch ordering determinism across SQLite and Postgres collations; the `""` → `null` mapping on `label`/`address`; ETag and cache-header parity between the id and by-source routes; the 404/422 boundaries on by-source; and leakage of `search_norm`, `source`, `verification`, `verified_at`, `role` into any response body or the OpenAPI schema.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: approve

The staging ref resolves to the merge base and the six-commit diff is non-empty. The review workflow now splits standards and spec checks while I separately probe the requested database and HTTP edge cases.

No material findings.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| — | No findings reported | — | — | Second pass with an explicit falsification brief returned `approve` with no material findings; nothing to triage. | — |
