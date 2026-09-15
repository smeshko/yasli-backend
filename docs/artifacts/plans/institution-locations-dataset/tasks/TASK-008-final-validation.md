# TASK-008: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for institution-locations-dataset`

## Goal

Confirm the plan is fully implemented and production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] `just be-lint` passes with no issues
- [ ] `just be-test` passes in full
- [ ] `just db-reset && just be-ingest`, then load the reference file against
      that fresh database — capture the loader summary
- [ ] Run the loader a second time; `SELECT role, precision, count(*) ... GROUP BY 1,2`
      (via `docker compose exec -T postgres psql -U yasli -d yasli -c …` from
      the `yasli/` parent — `just db-psql` takes no arguments) is identical to
      the first run
- [ ] Capture the loader summary's unresolved-`main` list itself (expected
      empty), not just the counts
- [ ] Show counts by `role` (expect 77 `main`, 15 `branch`), by `precision`
      (expect 3 rows at `none`, the name-only branches, plus any listed
      unresolved `main` rows; `approximate` only where the reviewer chose it),
      and by `verification`
- [ ] Show that every `verification=auto` row is `osm_poi` + `main` +
      `building` — no `branch` row and no `nominatim`-sourced row is `auto`
- [ ] Show `SELECT kind, external_id, count(*) … WHERE role='main' GROUP BY 1,2
      HAVING count(*) > 1` returning zero rows
- [ ] `uv run pytest tests/test_institution_locations_data.py -v` passes
      against the committed files, and the provenance file has exactly as
      many entries as there are `auto` rows
- [ ] Start the review tool against the final candidates file and screenshot
      the `To review` tab empty and the `Auto-accepted` tab populated
- [ ] Against a **copy** of the candidates file and CSV, make one decision in
      the tool, show the diff of the CSV it wrote and `parse_file` accepting
      it, then discard the copy — the decision → CSV → parser round trip
- [ ] Show the institutions-without-a-`main`-row LEFT JOIN returning zero rows
- [ ] Spot-check five institutions against their source `ADDRESS`, chosen to
      span the address shapes: one street+number, one block-relative
      (`ж.к. ... до бл.`), one with no number (`с.Каменар`), one preschool, one
      nursery
- [ ] **Include the ДГ№13 "Мир" case in full** — 1 `main` + 4 `branch` rows, with
      the main and the `1А` branch resolving to different buildings on the same
      street
- [ ] Show the three measured geocoder failures by name — `бул. "Чаталджа"
      111`, `кв. Виница, ул. "Лазур" №2`, `ж.к."Владислав Варненчик" до бл.20`
      — with their final coordinates, each inside the city of Varna and not in
      Игнатиево, Константиново or Аксаково
- [ ] Feed the loader a deliberately broken file (unknown `(kind, external_id)`)
      and show it aborting with the pair named and the table unchanged
- [ ] Feed the loader a partial CSV (one `main` row removed) and show it
      aborting before TRUNCATE with the institution named and the table
      unchanged; then show the same file loading under `--allow-incomplete`
      with the missing-`main` count in the summary
- [ ] `UPDATE institutions SET address = …` for one institution in the local
      database, show `--dry-run` and a real run both aborting with the
      institution and both addresses named and the table unchanged, then
      restore the address
- [ ] Doctor a copy of the candidates file so its `source_hash` no longer
      matches, start the review tool against it, and show the committed CSV
      and provenance file byte-identical afterwards
- [ ] Feed the parser four more broken files and show each rejection naming
      the line: a coordinate outside the polygon (an Аксаково point), two
      `main` rows for one institution, an `auto` row with `source=nominatim`,
      and an `auto` row with no provenance entry
- [ ] `PLAN.md` acceptance criteria all met, each with its Evidence produced —
      no criterion ticked on "the code looks right"

### Epic update

Epics live in this repo under `docs/artifacts/epics/` (since d13317d), so
`link_plan.py` works: it roots on `git rev-parse --show-toplevel`.

- [ ] Run `python3 ~/.claude/skills/create-epic/scripts/link_plan.py 01 --phase 1.2 --plan institution-locations-dataset --status done`
      — sets the phase's `**Plan**:` line to `… · status: done`
- [ ] Tick phase 1.2's `### Acceptance criteria` in
      `../../../epics/01-institution-data-foundation.md` by hand
- [ ] Tick the epic-level criterion "The coordinate dataset is reproducible: the
      seeding script and review tool are committed, and the auto-accept rules and
      review step are documented"
- [ ] Confirm Epic 01's row in `../../../epics/EPICS.md`
      reads `In progress`
