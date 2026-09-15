# TASK-007: Document the manual refresh cadence

Depends on: TASK-006
Suggested commit: `docs(ops): document the institution locations refresh`

## Goal

An operator who has never seen this dataset can tell when it needs refreshing,
how to refresh it, and what the loader's summary is telling them.

## Files

- `docs/OPERATIONS.md` — a new section mirroring the ГРАО quarterly-refresh entry
- `docs/ARCHITECTURE.md` — one line placing `institution_locations` in the data
  model, since it is the first table that is neither snapshot-derived nor ГРАО
- `../justfile` (the `yasli/` parent, outside every repo) — a
  `be-load-locations` recipe next to `be-ingest` that runs the loader CLI.
  The epic asks for a recipe; it cannot be in the PR, so this task adds it
  locally and the runbook names it

## Acceptance

- [ ] The section states the trigger conditions, not just the procedure:
      a new institution appears in the weekly ingest, or an institution's
      address changes there (either makes the next load abort until the row
      is re-reviewed; `--dry-run` shows it without loading); someone reports
      a wrong pin
- [ ] It explains the three abort conditions — an unmatched `(kind,
      external_id)`, an institution with no `main` row, a `main` row whose
      address drifted from the institution's — all checked before TRUNCATE,
      and says `--allow-incomplete` exists for local partial loads and is
      never used against production
- [ ] It says a fresh checkout is fine: the committed CSV and provenance file
      are the record, the candidates file is a local cache, and the seed
      script rebuilds decisions from the committed files when the cache is
      missing or stale
- [ ] It gives the exact CLI invocation, including the default file path, and
      says where it runs: from a Railway exec shell (the image copies `data/`)
      or from a checkout against a tunnelled `DATABASE_URL`, as the ГРАО entry
      does
- [ ] It explains the `precision`, `source` and `verification` vocabularies,
      the four auto-accept rules, and why a `human` decision must not be
      silently overwritten by a re-run of the seed script
- [ ] It gives the refresh loop end to end: seed script
      (`uv run python -m scripts.seed_institution_locations`) → review tool
      (`uv run python -m scripts.review_locations`) → commit CSV → loader, and
      notes that the candidates file is gitignored working state
- [ ] It says that a seed re-run rewrites the CSV and the provenance file from
      every decided entry in the candidates file, so `human` rows survive it —
      and that deleting the candidates file is what would lose them
- [ ] It says the provenance file is committed with the CSV, that both are
      written only by the seed script and the review tool, and what a
      provenance entry lets a reader audit about an `auto` pin
- [ ] It says explicitly that geocoder output is never accepted without review,
      and links to the measured reason (research §3.2)
- [ ] It notes that `just be-ingest` does **not** load this table, and why
- [ ] It names `just be-load-locations` and says it lives in the `yasli/`
      parent `justfile`, outside this repo — added by this task, not by the PR
- [ ] Follows the ГРАО entry's subsection structure as it stands: "When to
      refresh", "Where to get the file", "Loading the file into the database",
      "Verification after refresh", "Rollback"

Evidence: the rendered section read end-to-end against the ГРАО entry for tone
and completeness, plus the CLI invocation copy-pasted from the doc and run
successfully.

## Steps

- [ ] Draft the section against the ГРАО entry's shape
- [ ] Include the two verification queries from `RESEARCH.md` — counts by
      `role`/`precision`, and the institutions-without-a-`main`-row LEFT JOIN —
      in the `docker compose exec -T postgres psql …` form run from the `yasli/`
      parent (`just db-psql` is interactive and takes no arguments), plus
      `python -m yasli.ingest.institution_locations_loader --dry-run` as the
      drift check, since address normalisation is not expressible in SQL
- [ ] Add the `be-load-locations` recipe to `../justfile` next to `be-ingest`
      and run it once
- [ ] Add the one-line ARCHITECTURE.md placement

## Notes

The ГРАО entry's structure is worth copying closely: it leads with *why the data
matters* (it powers nursery and preschool routing) before the mechanics, which
is what makes it usable by someone deciding whether a refresh is urgent. Do the
same here — this table is what puts a pin on a parent's map, and a stale row is
a parent at the wrong building.

The most important line in the whole section is the one saying a
`verification=human` row represents human judgement the seed script cannot
reproduce. The script is resumable and keeps those decisions. Say so, so the
operator trusts re-running it instead of hand-editing the CSV.
