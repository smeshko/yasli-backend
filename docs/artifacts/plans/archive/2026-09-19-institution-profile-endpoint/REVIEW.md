# Review Summary — institution-profile-endpoint

**Rounds:** 2 (Codex, plan risk `medium`)
**Fix commits:** none — no round produced a finding
**Commits reviewed:** a242f54879fd..90eddb534146 (5 commits against `staging`)

## Rounds

| Round | Reviewer | Findings | Fixed | Deferred | Rejected |
|-------|----------|----------|-------|----------|----------|
| 1     | Codex    | 0        | 0     | 0        | 0        |
| 2     | Codex    | 0        | 0     | 0        | 0        |

Round 1 was an unscoped adversarial pass over the branch diff; verdict `approve`, no
material findings. Round 2 re-ran with an explicit falsification brief — treat round 1's
approval as a hypothesis to disprove — aimed at the parts of the change with real failure
modes: the LEFT OUTER JOIN added to the list query (row count and ordering), `Decimal` →
`float` conversion for `lat`/`lon`, branch ordering determinism across SQLite and Postgres
collations, the `""` → `null` mapping on `label`/`address`, ETag and cache-header parity
between the id route and the by-source route, the 404/422 boundaries on by-source, and
leakage of `search_norm`, `source`, `verification`, `verified_at` or `role` into any
response body or the OpenAPI schema. Verdict `approve` again, no material findings.

Round files: `reviews/round-1.md`, `reviews/round-2.md` (Codex output verbatim).

## Fixes

None. No finding in either round, so no review commits sit on top of the task commits and
the plan↔commit mapping is unchanged.

## Deferred

None.

## Rejected

None.

## Verification

Re-run on the reviewed head (`90eddb5`) after both rounds:

- `just be-lint` — `ruff check .`, all checks passed
- `just be-test` — 589 passed in 63.00s
