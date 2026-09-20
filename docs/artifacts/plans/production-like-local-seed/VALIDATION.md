# Validation Summary — production-like-local-seed

**Rounds:** 3 (reviewer: Codex, all rounds)
**Plan status at validation:** draft
**Run on:** 2026-09-19 → 2026-09-20

Three rounds, fourteen findings, all applied. Round 3 still produced real defects,
which the shared protocol treats as a stop-and-ask signal; the plan owner chose to
apply the four and stop rather than run a fourth round or rewrite the plan.

Two findings in round 3 were defects introduced by round-2 edits, not by the
original plan — noted individually below.

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 6        | 6       | 0        | 0        |
| 2     | 4        | 4       | 0        | 0        |
| 3     | 4        | 4       | 0        | 0        |

Two sub-claims were rejected inside otherwise-applied findings; both are listed
under **Rejected** below.

## Applied

### Round 1

- **TASK-003, TASK-004, TASK-005, TASK-008, PLAN.md, RESEARCH.md, DECISIONS.md:D7** —
  the plan's mechanism for routing the 18 legacy nurseries could not work:
  `district_stamp` excludes `kind='nursery'` in both passes by design
  (`district_stamp.py:270,291`, docstrings at `:11` and `:477-482`) because nursery
  districts are API-sourced, and `match_data_validation.py:119` counts
  `nursery_without_district` as a hard failure. The fixture now carries
  `district_code` itself. New decision **D7** records why stamping was not extended
  to nurseries instead. (round-1 #1)
- **TASK-008, TASK-005** — the "seed with step X skipped" sabotage cases ran over an
  already-seeded database, where the ГРАО and locations loaders' TRUNCATE-and-reload
  behaviour means skipping a step preserves the previous run's rows and `verify`
  passes on evidence that proves nothing. Every case now starts from `just db-reset`.
  (round-1 #2)
- **TASK-006, PLAN.md:Risks** — `freeze` could commit a snapshot and a legacy fixture
  from different epochs, and because the legacy loader upserts on
  `(kind, external_id)`, a fixture row that had since become a live snapshot row
  would overwrite current data. Added a disjointness guard and an `--allow-shrink`
  gate. (round-1 #3)
- **PLAN.md:Acceptance Criteria, TASK-005, TASK-008** — `/api/match` takes
  `address_id` (`routes/match.py:80`), not an address string, so the headline
  acceptance check was not executable; and surrogate ids do not correspond across
  databases, so "compare the payloads" was not stable evidence. Now: natural-key
  address lookup per database, compared on a normalised projection. (round-1 #4)
- **TASK-005, TASK-008, DECISIONS.md:D6** — `verify` asserting a literal 95
  institutions contradicted both D6 (stale rows survive a dirty re-run) and `freeze`
  (which legitimately changes the artifacts). Expectations are now derived from the
  committed artifacts. (round-1 #5)
- **PLAN.md:Tasks, TASK-006** — TASK-006 creates `yasli/seed/freeze.py` and edits
  `yasli/seed/__main__.py`, both created by TASK-004, without depending on it.
  (round-1 #6)

### Round 2

- **TASK-006, DECISIONS.md:D8** — the round-1 guard validated before two separate
  writes, so a crash between them still left a mismatched pair, and no valid
  transition was defined for a legacy key reappearing in the snapshot. `freeze` now
  builds both artifacts in a temp directory, checks disjointness over the candidate
  pair, and publishes both at the end; the overlap error names the remedy.
  (round-2 #1)
- **TASK-005, TASK-008, PLAN.md, DECISIONS.md:D6** — D6's "extras are visible drift"
  reading did not survive the routing code: `_district_rows_for_kind`
  (`matching.py:222-249`) selects every nursery carrying the queried district with
  no artifact scoping, so a stale row appears in `/api/match`. D6 kept (the seed
  still runs against a dirty database), but `verify` now **fails** on institutions
  outside the artifact union. (round-2 #2)
- **TASK-008, TASK-004, PLAN.md:Acceptance Criteria** — the "sabotage any one step"
  criterion was undemonstrable for `restamp-districts`: ingest ends with the gated
  stamping passes (`pipeline.py:673-674`), so on a clean seed the final restamp is
  near-redundant. The criterion is now scoped to independently required steps, and
  the restamp is proved over a dirty database instead. Missing migration case added.
  (round-2 #3)
- **PLAN.md:Scope** — Scope ordered snapshot ingest *before* ГРАО, the exact reverse
  of the order TASK-004 calls load-bearing. An implementer following Scope would have
  built the failure YAS-21 was filed about. (round-2 #4)

### Round 3

- **TASK-005, TASK-008, PLAN.md, DECISIONS.md:D6** — the round-2 fix closed the
  institution half of the dirty-database problem and left the catchment half open:
  `_insert_address_institutions` (`pipeline.py:564-630`) inserts with
  `on_conflict_do_nothing` and never deletes, while `_address_rows`
  (`matching.py:189-218`) joins the junction unscoped, so a stale edge keeps adding a
  kindergarten to `/api/match`. `verify` now reconciles the edge set too. D6 records
  the general rule: every table a dirty re-run can leave stale is a table `verify`
  must reconcile. (round-3 #1)
- **TASK-006, TASK-008, PLAN.md:Risks, DECISIONS.md:D8** — *a defect in a round-2
  edit.* The claim that back-to-back `os.replace` calls leave "no window" is false;
  an interruption between them still leaves a mismatched pair. The window is accepted
  (two syscalls, a git working tree, and the committed-data test as backstop) but the
  claim is corrected, and `freeze` now reports the ambiguity instead of claiming
  success. (round-3 #2)
- **TASK-005, TASK-008** — *a defect in a round-2 edit.* The restamp sabotage case
  corrupted districts to a valid-but-wrong value, which none of TASK-005's checks
  (non-null coverage, code membership, one routing case) can detect. The case now
  targets named rows with independently known expected districts, and TASK-005 gained
  the corresponding value check. (round-3 #3)
- **TASK-007, PLAN.md:Tasks** — TASK-007 documents and executes `freeze` but depended
  only on TASK-004 and TASK-005. Round 1 fixed this class of omission on TASK-006
  without sweeping the other task files. (round-3 #4)

## Deferred

None. Every finding across the three rounds was either applied or rejected on the
spot; nothing was parked for a follow-up ticket.

## Rejected

- **(round-1 #1, partial) Add nursery support to `district_stamp`** — proposed as an
  alternative to putting `district_code` in the fixture. Rejected: the exclusion is
  deliberate and documented in three places, address-parsing a nursery's district is
  strictly less reliable than the API value production already holds, and the change
  would widen the blast radius to the weekly ingest. Recorded as D7's rejected
  Option 2.
- **(round-1 #5, round-2 #2) Reverse D6 and refuse dirty databases** — proposed in
  round 1 and pressed again in round 2 with the `/api/match` consequence attached.
  Rejected both times: D6 Option 2 is exactly this, and it was already considered and
  declined on the grounds that a gate in front of a command whose purpose is to be
  runnable without thinking is the wrong trade. The routing consequence was addressed
  by making `verify` strict instead, which is where the "is this production-like?"
  claim belongs.
- **(round-2 #1, round-3 #2) Replace `freeze`'s guard with a full stage-and-swap** —
  proposed twice: stage both artifacts, seed and verify a throwaway database from the
  staged pair, publish only on green; round 3 escalated to versioned directories with
  an atomic pointer swap. Rejected: it makes a maintainer command depend on the entire
  seed *and* verify path (TASK-006 would gain a dependency on TASK-005) to buy down a
  residual risk that is staleness rather than corruption, in a git working tree where
  `git checkout -- data/seed/` is a complete rollback. Recorded in D8; the versioned-
  directory design is noted there as available if the residual window ever proves
  insufficient in practice.
