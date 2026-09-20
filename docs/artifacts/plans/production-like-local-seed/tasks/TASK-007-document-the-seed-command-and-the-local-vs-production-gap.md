# TASK-007: Document the seed command and the local-vs-production gap

Depends on: TASK-004,TASK-005,TASK-006
Suggested commit: `docs: document the local seed command and what it does not contain`

## Goal

Someone who has never seen this repo can find the one command, run it, and know
exactly how the database it produces differs from production — without reading any
source.

## Files

- `README.md` — replace the four-step quickstart. The R2 block stops being step 4
  of getting started and becomes an optional maintainer note. Add the
  local-vs-production table. Add `python -m yasli.seed` to a new row block in the
  environment-variable table showing that it needs only `DATABASE_URL`.
- `docs/OPERATIONS.md` — a new "Local seed data" section beside the ГРАО and
  institution-locations runbooks: what the two committed artifacts are, when to
  refresh them, the `freeze` command, and the `railway run` requirement for the
  legacy rows. Cross-link from the existing ГРАО section, which currently implies
  the KADS file must be obtained by hand.
- `/Users/A1E6E98/Developer/Projects/yasli/justfile` — a `be-seed` recipe in the
  `backend` group, and a `be-verify-seed` recipe for the standalone check.

## Acceptance

- [ ] README quickstart is: start Postgres → `uv run python -m yasli.seed` → serve.
      No R2 variables anywhere in the getting-started path
- [ ] The local-vs-production table states, with numbers: institution count (95 both
      sides, and *why* 18 of them are stale), the frozen snapshot's `scraped_at` and
      that it does not move on its own, ГРАО cycle coverage, and that free-places
      (epic 02) is not local at all
- [ ] `docs/OPERATIONS.md` explains how to refresh each committed artifact and what
      happens if you never do
- [ ] The ГРАО section no longer implies a developer must download the file
      themselves for local work
- [ ] `just be-seed` and `just be-verify-seed` run from the repo root
- [ ] Every command printed in the docs was actually executed and produced the
      output shown

Evidence: the rendered README quickstart followed verbatim on a clean database,
with the console output pasted into the task's completion note.

## Steps

- [ ] Rewrite the README quickstart and environment-variable table
- [ ] Write the local-vs-production table from measured numbers, not from memory
- [ ] Add the `docs/OPERATIONS.md` section and cross-links
- [ ] Add the two `justfile` recipes
- [ ] Run the documented quickstart end to end on a `just db-reset` database and
      correct anything that does not match

## Notes

The root `justfile` is **not** in any git repository — the `yasli` root is a plain
directory containing three repos. The recipes are a local convenience and will not
appear in this task's commit; the documented entrypoint must therefore be the module
path (`uv run python -m yasli.seed`), with the recipe mentioned only as an alias.
Say this in the commit message so a reviewer is not left looking for the justfile diff.
