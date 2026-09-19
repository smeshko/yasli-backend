# TASK-005: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for institution-profile-endpoint`

## Goal

Confirm the plan is fully implemented and production-ready: every acceptance
criterion in `PLAN.md` is demonstrated against the local database and the
running API, the frontend's type generator consumes the schema, and epic 01
is closed out.

## Steps

- [ ] TASK-001 through TASK-004 are ticked in `PLAN.md`; TASK-005's own box
      is ticked by `implement-plan` only after every step below has its
      evidence
- [ ] `just be-lint` passes with no issues
- [ ] `just be-test` passes in full. Run it with
      `YASLI_TEST_DATABASE_URL=postgresql+psycopg://yasli:yasli@localhost:5432/yasli_test`
      so the Postgres-backed tests run — and **never** point that variable at
      the `yasli` database: `tests/test_migrations.py` downgrades to base and
      would wipe the 77 ingested institutions every curl below depends on. If
      `yasli_test` is missing, create it from `yasli/` with
      `docker compose exec -T postgres psql -U yasli -d yasli -c "CREATE DATABASE yasli_test"`.
      Without a reachable Postgres, list the migration tests as CI-pending per
      implement-plan's "When CI is the test gate"
- [ ] Module/import boundaries respected: `routes/institutions.py` imports
      `yasli.db`, `yasli.models.*` and `yasli.models.types` only — nothing
      from `yasli.ingest` or `scripts`
- [ ] Local data is current — from `yasli/`: `just db-up`, then
      `docker compose exec -T postgres psql -U yasli -d yasli -tAc "SELECT version_num FROM alembic_version"`
      prints `0010` and `SELECT count(*) FROM institutions` prints `77`
- [ ] The table holds the committed CSV, not an older load — run
      `just be-load-locations` **unconditionally** (idempotent: the three
      guards, then TRUNCATE + INSERT in one transaction) and capture its
      summary line, expected
      `rows=94 main=77 branch=17 … missing_main=0 address_drift=0 unresolved_main=0 dry_run=0`;
      then `SELECT count(*) FROM institution_locations` prints `94`. A row
      count alone cannot tell a stale load from the committed file, and
      `--dry-run` checks the CSV against `institutions` without comparing it
      to the table, so the load itself is the gate. Every curl below is
      evidence only because this step ran first
- [ ] `just be-api` running on `:8000` for the curls below; every payload and
      header dump goes into the task report
- [ ] **ДГ№13 "Мир"** — `curl -s localhost:8000/api/institutions/by-source/kindergarten/46 | python3 -m json.tool`:
      `location.precision` is `building`; exactly 4 `branches`, each with a
      `location`; the `ул. Н. Михайловски 1А` branch sits on the main
      building's street; `phone`, `email`, `director` non-null; `website`
      null; `district_code` null locally (see RESEARCH.md — the kindergarten
      stamp needs ГРАО rows); `coverage` non-empty
- [ ] **A nursery** (`nursery/1`) on both routes:
      `district_code` `"01"`, `coverage: []`, `branches: []`, `location`
      present
- [ ] **A preschool** (pick one with
      `SELECT external_id FROM institutions WHERE kind = 'preschool' LIMIT 1`)
      on both routes: `website` non-null, `location` present
- [ ] **Byte identity** for each of the three — serials are reassigned when
      the database is rebuilt, so the id route's id comes from the by-source
      body, never from a number written down in advance:
      `curl -s -D /tmp/h1 -o /tmp/a.json localhost:8000/api/institutions/by-source/{kind}/{external_id}`,
      `ID=$(python3 -c 'import json; print(json.load(open("/tmp/a.json"))["id"])')`,
      `curl -s -D /tmp/h2 -o /tmp/b.json localhost:8000/api/institutions/$ID`;
      `cmp /tmp/a.json /tmp/b.json` is silent and the two `ETag` header lines
      are equal
- [ ] **Errors** — `curl -s -o /dev/null -w '%{http_code}\n'` prints `404`
      for `…/by-source/kindergarten/999` (body
      `{"error":"institution_not_found"}`), `422` for
      `…/by-source/school/46`, `405` for `-X POST …/by-source/kindergarten/46`
- [ ] **Conditional GET** — the same curl with `-H 'If-None-Match: …'` set to
      the ETag captured for `kindergarten/46` prints `304`
- [ ] **List** —
      `curl -s localhost:8000/api/institutions | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d), sum(1 for i in d if i["location"]), sum(1 for i in d if i["has_infant_group"]))'`
      prints `77`, then `77` pinned (the committed CSV has no unpinned
      `main` rows), then the infant-group count; and the id sequence
      `[i["id"] for i in d]` equals
      `SELECT id FROM institutions ORDER BY CASE kind WHEN 'nursery' THEN 0 WHEN 'kindergarten' THEN 1 WHEN 'preschool' THEN 2 ELSE 3 END, name, external_id, id`
- [ ] **Server-only names** —
      `curl -s localhost:8000/openapi.json | grep -c -E '"(search_norm|verification|verified_at|source|role)"'`
      prints `0`
- [ ] **Frontend types round trip** (from `yasli/`):
      `git -C frontend status --short src/lib/api/types.ts` is empty
      **before** starting — if it is not, stop and ask; never overwrite a
      hand edit. Then `just fe-api-types` exits 0;
      `git -C frontend diff --stat src/lib/api/types.ts` shows the file
      changed; `grep -n -E 'by-source|"Location"|has_infant_group|branches' frontend/src/lib/api/types.ts | head`
      shows the new names; then `git -C frontend checkout -- src/lib/api/types.ts`
      and the status is empty again. The diff stat and the grep go into the
      task report
- [ ] `PLAN.md` acceptance criteria all met, each with its Evidence produced
      (test output, curl payloads, header dumps, the types diff stat) — no
      criterion ticked on "the code looks right"

### Epic update

- [ ] Tick phase 1.3's `### Acceptance criteria` in
      `docs/artifacts/epics/01-institution-data-foundation.md`
- [ ] Mark the phase done:
      `python3 ~/.claude/skills/create-epic/scripts/link_plan.py 01 --phase 1.3 --plan institution-profile-endpoint --status done`
- [ ] Phase 1.3 is epic 01's last phase. Tick both remaining epic-level
      criteria — "Every phase merged and its acceptance criteria met" and "A
      single API call returns everything a detail page needs for any of the
      77 institutions" — and set the epic file's `Status:` to `done`.
      `archive-plan` has no epic-file step (it only rolls up Linear), so
      nothing is left for it
- [ ] Update Epic 01's row in `docs/artifacts/epics/EPICS.md` to `Done` and
      tick the epic's "Status row in EPICS.md updated to `Done`" criterion;
      Epic 02 (Free-places API) depended only on Epic 01, so move its row from
      `Blocked` to `Ready for dev`
- [ ] These status edits are the branch's final commit and reach `staging`
      only through the PR merge itself — the moment the row says `Done` on
      `staging`, every phase has merged. Nothing in the epic files or
      `EPICS.md` is edited on `staging` directly, so the board is never ahead
      of the code
