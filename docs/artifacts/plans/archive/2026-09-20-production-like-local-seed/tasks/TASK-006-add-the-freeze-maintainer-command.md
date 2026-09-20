# TASK-006: Add the freeze maintainer command

Depends on: TASK-002,TASK-003,TASK-004
Suggested commit: `feat(seed): add the freeze command that regenerates the committed seed data`

## Goal

Refreshing the committed seed artifacts is one command a maintainer runs, not a
sequence of ad-hoc shell steps nobody wrote down — so the frozen snapshot stays
refreshable instead of drifting until it is useless.

## Files

- `src/yasli/seed/freeze.py` — new. Two operations under one command:
  - fetch `snapshots/varna/latest.json` from R2 and write
    `data/seed/snapshot.json.gz` (gzip `-9`, deterministic: no embedded mtime or
    filename, so an unchanged snapshot produces an unchanged file)
  - read the configured `DATABASE_URL` and rewrite
    `data/seed/legacy_institutions.json` with the institutions present there but
    absent from the snapshot just fetched, each carrying the `district_code`
    production holds for it (TASK-003 — the value is API-sourced and no stamping
    pass will supply it)
  - **a pairing guard over the candidate pair, and an atomic publish.** Both
    artifacts are built into a temp directory first; the `(kind, external_id)` keys
    of the candidate fixture and the candidate snapshot must be disjoint; only then
    are both moved into `data/seed/` with `os.replace`, back to back, as the last
    thing the command does. Nothing is published unless both are ready — a failure
    while deriving the fixture cannot leave a new snapshot beside an old fixture.
    This narrows the mismatch window to the gap between two renames; it does not
    eliminate it (see Notes).
    The check runs on `--snapshot-only` too, there against the *already committed*
    fixture, because a snapshot refresh that promotes one of the 18 to a live row
    would otherwise leave a fixture whose upsert overwrites current data. On
    overlap, publish nothing, exit 3, name the colliding keys, and state the
    remedy: run a full `freeze`, or drop those keys from
    `legacy_institutions.json` first
- `src/yasli/seed/__main__.py` — `freeze` subcommand with `--snapshot-only`,
  `--legacy-only`, `--dry-run` and `--allow-shrink`. Requires the four `R2_*` vars
  unless `--legacy-only`. The subcommand is added to the CLI TASK-004 creates.
- `data/seed/README.md` — extend with the refresh procedure and the
  `railway run` caveat.
- `tests/seed/test_freeze.py` — new.

## Acceptance

- [ ] `python -m yasli.seed freeze` rewrites both artifacts and reports the byte
      size and `scraped_at` of each
- [ ] Freezing an unchanged snapshot produces a byte-identical file — no gratuitous
      diff, no mtime churn in git
- [ ] When the configured database holds **no** institutions absent from the
      snapshot, `legacy_institutions.json` is left untouched and the command says so
      — a maintainer pointed at their own local DB cannot blank the fixture
- [ ] A derived fixture with **fewer** rows than the committed one is refused
      unless `--allow-shrink` is passed, naming the rows that would disappear — a
      partial or wrong database shrinks the fixture without emptying it, and the
      empty-diff guard alone does not catch that
- [ ] Overlapping keys between the fixture and the snapshot abort the command with
      exit 3 and publish **neither** file, including under `--snapshot-only`, and
      the message names both the colliding keys and the two ways out (full freeze,
      or drop the keys from the fixture)
- [ ] A failure anywhere before the publish step — fetch, derivation, validation —
      leaves `data/seed/` byte-for-byte unchanged
- [ ] A failure *between* the two renames is reported honestly: the command exits
      non-zero and names both files as possibly mismatched, telling the maintainer
      to `git checkout -- data/seed/` and re-run. It does not claim success
- [ ] No temp files are left behind in `data/seed/` on any failure path
- [ ] Every row the legacy derivation writes carries a `district_code` in `01`–`05`;
      a production row without one aborts rather than emitting an unroutable fixture
- [ ] `--dry-run` reports what would change and writes nothing
- [ ] Missing R2 variables exit 2 with the same message `python -m yasli.ingest`
      already produces
- [ ] Seeding from freshly frozen artifacts reproduces the same row counts as
      seeding from the committed ones

Evidence: `freeze --dry-run` output against the current artifacts showing no drift,
plus `git status` clean after a real `freeze` over an unchanged snapshot.

## Steps

### RED
- [ ] Test that freezing the same bytes twice produces an identical file
- [ ] Test that an empty legacy diff leaves the file untouched and reports it
- [ ] Test that a shrinking diff is refused without `--allow-shrink` and permitted
      with it
- [ ] Test that key overlap aborts with exit 3 and publishes neither file, both in
      the full run and under `--snapshot-only`
- [ ] Test the interrupted-derivation case: make the fixture derivation raise after
      a successful snapshot fetch, and assert both committed files are unchanged
- [ ] Test the interrupted-*publish* case: make the second `os.replace` raise, and
      assert the command exits non-zero with the mismatch warning naming both files
- [ ] Test `--dry-run` writes nothing
- [ ] Test the missing-R2-vars exit code

### GREEN
- [ ] Write the two freeze operations and the subcommand
- [ ] Document the procedure in `data/seed/README.md`

### REFACTOR
- [ ] Reuse `yasli.ingest.r2.get_object` and `LATEST_KEY`; freeze must not grow its
      own idea of where snapshots live

## Notes

This is the one command in the plan that **does** need credentials — that is the
point: the maintainer pays the credential cost once so every other developer pays
none. Deriving the legacy rows additionally needs read access to production, so the
README documents `railway run python -m yasli.seed freeze`.

The "leave the fixture untouched when the diff is empty" rule is a safety property,
not a convenience: without it, a maintainer running `freeze` against their own local
database would silently delete all 18 rows and the deletion would look like a
legitimate refresh in review. `--allow-shrink` extends the same reasoning to the
partial case, where the diff is non-empty but smaller than what is committed.

**The two artifacts are a pair, and the guard is what keeps them one.** The command
writes them in separate steps, so a failure between the two, or a deliberate
`--snapshot-only`, can leave a snapshot from one epoch beside a fixture from
another. The consequence that matters is not staleness but corruption: the legacy
loader upserts on `(kind, external_id)`, so a fixture row that has since become a
live snapshot row overwrites current data with a months-old copy. The disjointness
check over the candidate pair is the guard, and publishing both files at the very
end shrinks the exposure from "the whole database derivation" to "the gap between
two renames".

**It does not make the pair publish atomic, and the plan should not claim it
does.** Round 3 was right about this: two sequential `os.replace` calls can still
be interrupted between the first and the second, leaving one new file beside one
old one. Three things make that acceptable here rather than worth a
versioned-directory pointer swap: the window is two syscalls wide, the target is a
git working tree where `git checkout -- data/seed/` is a complete rollback, and
TASK-003's committed-data test fails `just be-test` before a mismatched pair could
reach a commit. What the command owes the maintainer is honesty — if the second
rename fails, say both files may now disagree and name the rollback, rather than
reporting a successful freeze. A full
stage-and-swap (seed and verify a throwaway database from the staged pair before
publishing either file) was considered twice and deliberately not taken — see
DECISIONS.md D8.

**Building the candidate fixture makes the disjointness check trivially true on the
full path** — it is derived as *production minus the snapshot*. Keep the assertion
anyway: it costs nothing and it is the only check on the `--snapshot-only` path,
where it is doing real work.

Pass `mtime=0` to `gzip.GzipFile` (and omit the filename) or the output differs on
every run and every refresh shows a spurious diff.
