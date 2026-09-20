# TASK-005: Verify the seeded database and refuse half-done

Depends on: TASK-004
Suggested commit: `feat(seed): verify the seeded database and refuse to finish half-done`

## Goal

The seed never reports success over a database that silently answers some queries
wrong: it checks its own work and exits non-zero naming every check that failed.

## Files

- `src/yasli/seed/verify.py` — new. A `Check` record (name, predicate, what it
  means when it fails) and `run_checks(session) -> VerifyResult`. Checks:
  - the institution set **equals** the disjoint union of the committed snapshot's
    and the committed fixture's `(kind, external_id)` keys. The expectation is
    *derived* from the two artifacts (77 + 18 = 95 today), never hard-coded —
    `freeze` legitimately changes both. Missing rows fail. Rows *beyond* the union
    also **fail**, named individually, with `just db-reset && just be-seed` as the
    remedy: `_district_rows_for_kind` (`matching.py:222`) returns every nursery
    carrying the queried `district_code`, so a stale extra changes what
    `/api/match` answers. D6 keeps the *seed* running against a dirty database;
    it does not make the result production-like, and verification is where that
    distinction is drawn
  - `address_institutions` holds exactly the edge set the committed snapshot
    describes. Ingest inserts with `on_conflict_do_nothing` and **never deletes**
    (`pipeline.py:564-630`), while `_address_rows` (`matching.py:189-218`) joins the
    junction unscoped — so an edge left behind by a previous snapshot silently adds
    a kindergarten or preschool to `/api/match`. Extra edges fail, named by
    `(address_id, kind, external_id)`, with `just db-reset` as the remedy; this is
    the catchment counterpart of the institution-set check above
  - `grao_addresses` is non-empty and spans districts 01–05
  - `addresses.district_code` is non-null for at least the threshold share of
    in-city addresses (`docs/OPERATIONS.md` treats >2 % unstamped as the staleness
    signal; fix the exact figure from the first real seed run)
  - every institution of kind `nursery` and `preschool` has a non-null
    `district_code`, or is listed by name if not. For nurseries this is a check on
    the *fixture and snapshot*, not on the stamping pass — `district_stamp`
    excludes nurseries, so a NULL here means bad seed data, and the failure message
    must say so rather than sending the developer to re-run `restamp-districts`
  - `institution_locations` holds both `main` and `branch` rows, and ДГ№13 "Мир"
    (`kindergarten`/`46`) has its 4 branches with coordinates
  - a set of **named addresses with independently known expected districts** — the
    ticket's Вапцаров address (district `02`, confirmed in the KADS data) plus at
    least one named kindergarten — match the values the ГРАО archive implies. A
    check on non-null coverage and valid code membership alone cannot tell a
    correct district from a valid-but-wrong one
  - the ticket's routing case. `/api/match` takes `address_id`
    (`routes/match.py:80`), not an address string, so the check resolves
    `ул. Н.Й.Вапцаров 007 вх.Г` to its `addresses.id` by natural key
    (street + number + entrance) in *this* database first, then asserts district
    `02` and a non-empty result set for all three kinds — not `0/4/0`
  - a **warning**, not a failure, when the frozen snapshot's `scraped_at` is more
    than 90 days old
- `src/yasli/seed/__main__.py` — `verify` subcommand; the default seed action runs
  the checks as its last step.
- `tests/seed/test_verify.py` — new.

## Acceptance

- [ ] `python -m yasli.seed verify` exits 0 on a fully seeded database and prints
      one line per check
- [ ] On a database that has never been seeded it exits non-zero and names every
      failing check — it does not stop at the first
- [ ] With ГРАО alone skipped **from an empty database**, it fails on the district
      checks and says so; with the locations load alone skipped, it fails on the
      branch check and says so. Each case starts from `just db-reset` — skipping a
      TRUNCATE-and-reload step over an already-seeded database leaves the previous
      run's rows in place and proves nothing (see TASK-008)
- [ ] A stale snapshot produces a warning and still exits 0
- [ ] The failure output names the seed step that would fix each failed check, not
      just the symptom
- [ ] A seed whose verification fails exits non-zero, so `just be-seed` cannot
      report success over a half-seeded database
- [ ] The institution-set check tracks the committed artifacts: a fixture with one
      row added or removed shifts the expectation with it, with no code change
- [ ] An institution outside the artifact union fails the run, is named with its
      `(kind, external_id)` and district, and the message says a stale nursery will
      show up in `/api/match` — so a seed over a dirty database cannot report
      success
- [ ] An `address_institutions` edge the committed snapshot does not describe fails
      the run and is named — the institution set being right is not sufficient
- [ ] A district that is non-null and structurally valid but *wrong* is caught,
      because the named-address checks compare against known expected values
- [ ] `nursery_without_district` is asserted at zero via the existing
      `validate-match-data` result, not by a reimplemented query

Evidence: two console transcripts side by side — `verify` passing after a full
seed, and `verify` failing after a seed with the ГРАО step deliberately skipped.

## Steps

### RED
- [ ] Test each check independently against a session fixture that satisfies or
      violates it
- [ ] Test that all failures are collected, not short-circuited
- [ ] Test the stale-snapshot warning path (exit 0, warning present)
- [ ] Test the extras failure: an institution outside the artifact union fails the
      run and is named
- [ ] Test the stale-edge failure: an `address_institutions` row absent from the
      snapshot fails the run and is named
- [ ] Test that a valid-but-wrong district on a named address fails
- [ ] Add an integration test: seed, drop `grao_addresses`, assert the exit code and
      the named check

### GREEN
- [ ] Write the checks and the result formatter
- [ ] Add the `verify` subcommand and make it the seed's final step

### REFACTOR
- [ ] Keep the checks declarative — a list of `Check`s — so a future one is a row,
      not a new branch

## Notes

Pin the `addresses.district_code` threshold to what the first real seed actually
produces, not to 100 %. ГРАО will never cover every address (new construction,
villages), and a check that can only ever fail teaches people to ignore it.

`validate-match-data` (`src/yasli/ingest/match_data_validation.py`) already asserts
routing assumptions and has a `has_hard_failures` result shape. Reuse it as one of
the checks — in particular its `nursery_without_district` and
`nursery_coverage_edges` hard-failure counters cover the legacy fixture's two
riskiest properties for free. Do not reimplement what it already covers.

**Derive counts, never hard-code them.** 95 is today's arithmetic (77 snapshot + 18
fixture), not a constant. `freeze` rewrites both artifacts and D6 permits extra
stale rows, so a literal `== 95` turns a legitimate refresh into a verification
failure. Read both committed artifacts, union their `(kind, external_id)` keys,
and check set *equality* — missing rows and extra rows both fail, each named.

**The same reasoning extends to `address_institutions`.** Round 3 caught the gap:
verifying institutions alone leaves catchment edges unchecked, and kindergarten and
preschool routing reads those edges directly. Derive the expected edge set from the
snapshot the same way, and fail on any edge outside it. Deriving 205,674 edges for
comparison is a set operation over data already in memory during verification —
compare hashes or counts plus a sampled diff if the full comparison proves slow,
but do not skip it.
