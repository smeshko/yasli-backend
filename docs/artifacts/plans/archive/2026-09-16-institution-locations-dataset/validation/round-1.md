# Adversarial Validation — Round 1

**Run:** 2026-09-15 05:12 UTC
**Plan:** institution-locations-dataset
**Status at start:** draft
**Reviewers:** Codex (`/codex-local:adversarial-review`) + independent `general-purpose` subagent lens, run in parallel per the `large`-risk rule; findings merged and deduped in the triage table

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

Do not ship the plan unchanged. The data artifact can claim auto-verification without proving the rules, duplicate main rows are not prevented, and final validation does not explicitly cover several safety-critical acceptance criteria.

Findings:
- [high] Parser cannot substantiate `verification=auto` (docs/artifacts/plans/institution-locations-dataset/PLAN.md:87-101)
  The plan makes the committed CSV the artifact of record and says the parser prevents invalid saves, but the parser requirements only validate enum values, coordinates, and polygon membership. Nothing in TASK-002 or the schema can prove that an `auto` row had a unique POI match, settlement agreement, or <=150 m geocoder agreement. A manually edited CSV can therefore mark a wrong coordinate as `verification=auto`, and TASK-003 will load it successfully. This undermines the primary safety boundary of the plan.
  Recommendation: apply — change TASK-002/TASK-003 and/or TASK-004 so auto rows are validated against the candidate decision state, or make the loader reject `verification=auto` rows unless they carry verifiable seed provenance; add a test for a forged auto row.
- [high] The schema permits multiple main rows per institution (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-001-add-the-institution-locations-table.md:37-43)
  The stated model is one `main` row per institution, and the later review/API plans select the main-role row, but TASK-001 only makes the full tuple `(kind, external_id, role, label, address)` unique. Two different main rows for the same institution are valid under that constraint. The loader only reports institutions with no main row, so it does not reject ambiguous main data; a future detail query can return nondeterministic or silently incomplete location data.
  Recommendation: apply — update TASK-001, TASK-002, TASK-003, and TASK-008 to enforce exactly one `main` per `(kind, external_id)` (database partial unique index plus parser/loader test), while retaining multiple branch rows.
- [medium] Final validation does not actually cover every plan acceptance criterion (docs/artifacts/plans/institution-locations-dataset/tasks/TASK-008-final-validation.md:17-37)
  TASK-008 delegates to a generic 'all criteria met' statement but does not explicitly validate several material guarantees: the three measured bad geocoder results are absent as pins, an outside-polygon row is rejected with its row identified, unresolved main rows are listed by name, and a review decision is persisted and reparsed successfully. The listed spot checks do not guarantee those cases, so the final task can be completed while the core wrong-pin and rollback protections remain untested.
  Recommendation: apply — update TASK-008 with explicit commands/evidence for each omitted PLAN.md criterion, especially the three failure cases, polygon rejection, unresolved-name summary, and review-tool save→parse round trip.

Next steps:
- Resolve the auto-verification trust boundary and uniqueness invariant before implementation.
- Expand TASK-008 into a criterion-by-criterion validation checklist with observable evidence.

## Subagent lens output

<!-- Independent general-purpose subagent, same adversarial framing and focus text. Verbatim. -->

# Plan review: institution-locations-dataset

Twenty findings, five high. The high ones share a root: the plan's data/script layout doesn't survive contact with the Dockerfile, the Python import system, or its own CSV semantics.

## Findings

**1. `data/` never reaches the deployed image, and the CLI default is CWD-relative** — high
- Evidence: `Dockerfile:10-13` copies only `pyproject.toml`, `README.md`, `src/`, `alembic.ini`, `migrations/`; `pyproject.toml:30-31` packages from `src/` only. `docs/OPERATIONS.md:48-50` establishes "Railway exec shell" as the reference-load pattern. `tests/ingest/test_cli.py:39-48` runs the CLI from a temp cwd, so a bare `data/institution_locations.csv` default resolves nowhere. TASK-002 puts the polygon at `data/varna_municipality.geojson` and has `src/yasli/ingest/municipality.py` "load the boundary once" — in the image that import path has no file.
- Verdict: apply. Either `COPY data ./data` in the Dockerfile + anchor both defaults via `Path(__file__)`, or ship the GeoJSON as package data under `src/yasli/geo/` (where `settlements.py` already lives) and state in the runbook that the loader runs from a checkout against a tunnelled `DATABASE_URL`.
- Files: TASK-002, TASK-003, TASK-007.

**2. `pending` rows written as `manual`/`none`/`human` contradict the verification contract** — high
- Evidence: TASK-005 §Decision→CSV mapping, row `pending`, and §Notes "pending rows are written to the CSV". PLAN.md §Acceptance Criteria bullet 2: `human` means "resolved in the review tool". RESEARCH.md §Constraints: `verified_at` "is the date a row was decided"; TASK-001 makes it NOT NULL. TASK-004 §Acceptance: the seed writes a CSV "containing the auto rows" — i.e. no pending rows. Two writers, two answers; and a pending `main` row becomes indistinguishable from a deliberate `no_pin`.
- Verdict: apply. Omit pending rows; the loader's missing-`main` count already surfaces them.
- Files: TASK-005, TASK-004.

**3. Candidate `key` omits `address`, so unlabeled branches collide** — high
- Evidence: TASK-004 §Candidates file: `"key": {kind, external_id, role, label}`. RESEARCH.md §1.3 table: ДГ№13 has four branches with label `—`, ДГ№2/№5/№39 have two each. TASK-001's UNIQUE is over `(kind, external_id, role, label, address)`. TASK-005 `POST /api/decision {key, …}` cannot target one of ДГ№13's four.
- Verdict: apply — add `address` to `key`.
- Files: TASK-004, TASK-005.

**4. Seed re-run drops human decisions from the committed CSV** — high
- Evidence: TASK-004 §Acceptance: resumable, "keeps every entry whose decision is accepted/pinned/no_pin" but "writes `data/institution_locations.csv` containing the `auto` rows". TASK-007 §Notes tells the operator to "trust re-running it instead of hand-editing the CSV". The JSON keeps the decisions; the CSV as specified would not.
- Verdict: apply. One renderer, CSV = every non-pending entry (fixes #2 with the same edit).
- Files: TASK-004, TASK-007.

**5. `scripts/review_locations.py` beside `scripts/review_locations/` is un-importable** — high
- Evidence: TASK-005 §Files lists both. Verified at runtime in the scratchpad: the module wins, `import review_locations.state` fails with "'review_locations' is not a package"; adding `__init__.py` makes the package shadow the script instead.
- Verdict: apply — rename the directory (or collapse to a single script plus a sibling `.html`).
- Files: TASK-005.

**6. No stated mechanism for tests to import anything under `scripts/`** — med
- Evidence: `pyproject.toml:37-39` has no pytest `pythonpath`; `tests/conftest.py:8-13` only sets `DATABASE_URL`; no existing test imports from outside `src/`. TASK-004 (`tests/test_seed_institution_locations.py`) and TASK-005 (`tests/test_review_locations.py`) both need it. Also unstated: `ci.yml:45` `ruff check .` will lint `scripts/`.
- Verdict: apply — specify `scripts/__init__.py` + `python -m scripts.<name>`, or a conftest `sys.path` insert.
- Files: TASK-004, TASK-005.

**7. `tests/test_migrations.py` hard-codes the revision chain; 0010 breaks it three ways** — med
- Evidence: head asserted `"0009"` at `:123` and `:184`; `downgrade -1` → `"0008"` with contact columns gone `:150-157`; `downgrade -2` → `"0006"` with no `settlements` `:159-173`. With 0010, `-1` lands on 0009 (columns present) and `-2` on 0007 (settlements present). The archived plan's TASK-002:15-21 spelled this out for 0009; TASK-001 lists the file but not the change.
- Verdict: apply.
- Files: TASK-001.

**8. "Right amenity family" is never defined** — med
- Evidence: PLAN.md §Decisions rule 1 says "within the right amenity family"; TASK-004 §Acceptance rule 1 drops the qualifier; openspec §3.3 uses the phrase without a mapping. Which of `{kindergarten, childcare, nursery, school}` is "right" for `preschool` (Bulgarian ПГ sit inside schools) vs `nursery` decides whether a school POI with the same title auto-accepts.
- Verdict: apply — define the `kind → amenity set` table and cover it in the auto-accept table test.
- Files: TASK-004.

**9. `street` and `approximate` precision values are unreachable; `pinned` is always `building`** — med
- Evidence: TASK-005 mapping table emits only `building`/`none`; TASK-001 CHECK admits four values; RESEARCH.md §Uncertainty says the value "drives presentation in frontend epic 01". TASK-006 has the reviewer placing pins for block-relative addresses with no way to say "approximate".
- Verdict: apply — drop the two dead values, or give the `pinned` action a precision choice.
- Files: TASK-001, TASK-005, PLAN.md.

**10. The CSV writer/decision mapping has two homes and a dependency inversion** — med
- Evidence: TASK-004 §Files: "`src/yasli/ingest/institution_locations_loader.py` — reuse its writer/validator". TASK-005 §REFACTOR: "the CSV mapping exists once, in `state.py`, and the seed script's … writer (TASK-004) calls it too". TASK-004 depends only on TASK-002 yet would import a module TASK-005 creates.
- Verdict: apply — put the dict→CSV writer in the loader module (symmetric with `parse_rows`) and the decision→row mapping in one shared `scripts/` helper created in TASK-004.
- Files: TASK-004, TASK-005.

**11. The epic's `justfile` recipe deliverable is silently dropped** — med
- Evidence: `docs/artifacts/epics/01-institution-data-foundation.md:95` "A `justfile` recipe to run the loader". PLAN.md §Decisions: "not part of the PR". No task adds it to `../justfile`; TASK-007 AC says the runbook "records that the `just` recipe is a local convenience living in the `yasli/` parent" — a recipe that will not exist.
- Verdict: apply — add a step to TASK-007 to add the recipe to `yasli/justfile` (verified: `justfile` exists there, parent has no `.git`), or amend the epic in TASK-008.
- Files: TASK-007 or TASK-008.

**12. TASK-008 doesn't demonstrate two PLAN acceptance criteria** — med
- Evidence: PLAN.md AC "The three measured geocoder failures do not appear as pins" and "A row … outside the municipality polygon is rejected by the parser" have no TASK-008 step; the only broken-file run is the unmatched-pair case, and the spot-check is by address shape, not by those three addresses.
- Verdict: apply — add the three addresses to the spot-check and a second broken file with an out-of-polygon row.
- Files: TASK-008.

**13. TASK-008's `link_plan.py` prose is stale after d13317d** — med
- Evidence: TASK-008 §Epic update: "epics live in the `yasli/` parent". Commit `d13317d` moved them to `docs/artifacts/epics/` (present). `~/.claude/skills/create-epic/scripts/link_plan.py:37-48,160-166` roots on `git rev-parse --show-toplevel` and reads `docs/artifacts/epics` — it works now. The `../../../epics/` paths do resolve from `tasks/`; only the justification and "edit both sides by hand" are wrong. Text is copy-pasted from the archived plan's TASK-004:49-53.
- Verdict: apply — use `link_plan.py 01 --phase 1.2 --plan institution-locations-dataset --status done`; hand-tick only the criteria.
- Files: TASK-008.

**14. `just db-psql -c "…"` does not work** — low
- Evidence: `../justfile:210` `db-psql:` takes no parameters; `just --dry-run db-psql -c "SELECT 1"` → `error: justfile does not contain recipe '-c'`. Used in RESEARCH.md §Useful Commands, TASK-001 Evidence, and TASK-007 Steps (copies those queries into the runbook).
- Verdict: apply — `docker compose exec -T postgres psql -U yasli -d yasli -c "…"` (the pattern at `justfile:218`).
- Files: RESEARCH.md, TASK-001, TASK-007.

**15. Two acceptance items depend on artifacts produced by later tasks** — low
- Evidence: TASK-002 AC "Parsing the committed file (once TASK-006 produces it) yields 77 `main` / 15 `branch`"; TASK-003 Evidence "a real run against a migrated local database" — no committed CSV exists until TASK-006.
- Verdict: apply — move the count check to TASK-006 as a permanent regression test; have TASK-003 use a hand-made sample.
- Files: TASK-002, TASK-003, TASK-006.

**16. Polygon test list omits Звездица** — low
- Evidence: `src/yasli/geo/settlements.py:42-47` lists five villages; PLAN.md §Risks and TASK-002 AC name four (Каменар, Константиново, Тополи, Казашко).
- Verdict: apply.
- Files: TASK-002, PLAN.md.

**17. Flagged-row estimate inconsistent** — low
- Evidence: PLAN.md §Scope "~20–30"; RESEARCH.md, TASK-004, TASK-006 and the epic all say 25–35.
- Verdict: apply.
- Files: PLAN.md.

**18. "The in-memory session fixture" is not shared** — low
- Evidence: RESEARCH.md §Key Files and TASK-003 §Files refer to it as a given; `tests/conftest.py:8-13` only sets `DATABASE_URL`; the SQLite fixture is local to `tests/test_grao_loader.py:24-35` (a different shape in `tests/test_models.py:230-240`).
- Verdict: apply — say the new test module defines its own, copied from `test_grao_loader.py`.
- Files: RESEARCH.md, TASK-003.

**19. Flag semantics: per-row vs per-candidate, and rule 4 against a discarded candidate** — low
- Evidence: TASK-004 AC expects Игнатиево/Аксаково rows flagged `outside_municipality`, but the out-of-polygon candidate is the geocode, not the POI. If those rows also have a clean POI, PLAN rule 4 ("≤150 m … if a rank-30 hit also exists") is ambiguous about whether a polygon-rejected geocode still "exists".
- Verdict: apply — state that out-of-polygon candidates are dropped before rule 4 and that any flag forces `pending`.
- Files: TASK-004, PLAN.md.

**20. Cross-doc nits** — low, defer
- RESEARCH.md §References uses `openspec/docs/…`, a parent-repo path (the epic uses `../../../../openspec/…`). The openspec §3.4 revision note calls this "Phase 1.3" (it is 1.2) — not a plan file. TASK-001's index on `(kind, external_id)` duplicates the UNIQUE's leading columns; harmless at 92 rows.

## Checked and found correct

- `grao_loader.py`: `parse_file` (:314), `load(path, session)` (:324), `main(argv)` (:345), `LoaderSummary` dataclass (:112), exit 2/3 (:362, :369), TRUNCATE-vs-`delete()` branch (:331-334).
- `tests/ingest/test_cli.py` exists with subprocess style (:31-48); exit-0 summary test needs the testcontainers `engine` from `tests/ingest/conftest.py:88-98`.
- All four CHECK expressions are enforced by SQLite via `create_all`; the name-only branch row (`none`/`manual`/`human`, NULL coords) passes; no `Numeric` warning (run in-memory).
- Latest migration is 0009 → `0010` with `down_revision="0009"` is right; `alembic>=1.13` has `alembic check`; archived TASK-002 is the precedent.
- `institution.py:30-34` UNIQUE + `KIND_VALUES` CHECK pattern; `types.py:20`; `grao_address.py:12-13` `''` convention; `settlements.py:23-60` `VARNA_SETTLEMENTS`.
- RESEARCH numbers match openspec §1.3 table (15 rows, 8 kindergartens, ДГ№13 1+4), §3.1, §3.2 (17/16/35/6, 3 wrong), §3.3 (53/77, 7/53), §3.4 revision; §5 and §5.1 say what PLAN §Out of Scope claims.
- Epic phase 1.2 rules, counts and criteria agree with PLAN; EPICS.md row already `In progress`; TASK-008's `status: done` line matches `link_plan.py:91` output; PLAN's `../../epics/` link resolves.
- `../justfile` has `be-test`, `be-lint`, `be-ingest`, `be-migrate`, `db-reset` (:95, :100, :85, :80, :203); parent `yasli/` has no `.git`.
- CI (`ci.yml:45-49`) runs `ruff check .` and `pytest` with a Postgres service, so `test_constraints.py`/`test_migrations.py` execute there; `pytest testpaths=["tests"]` keeps `scripts/` out of collection.
- `.gitignore` has no `data/` rule; adding the candidates file is necessary and sufficient.
- Not verifiable offline: OSM relation 1404291's `admin_level`, the municipality bbox, and the seasonal free-places row count — the plan already flags all three as risks with mitigations.

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect

Sources: "Codex #n" = Codex output above; "lens #n" = subagent lens output above.
Codex #3 and lens #12 are the same finding and share row 3. Codex #1 is split
into row 1 (the part the parser *can* enforce) and row 25 (the remainder).
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | (Codex #1) Parser cannot substantiate `verification=auto`; a hand-edited CSV can forge an auto row | high | apply (partial) | The four rules need the gitignored candidates file and the network, so no parser can re-prove them; apply the invariants that *are* checkable — `auto` ⇒ `source=osm_poi` ∧ `role=main` ∧ `precision=building` — as a CHECK + parser rule, and record the trust boundary as a Risk. Remainder is row 25 | PLAN.md:Decisions, PLAN.md:Risks, PLAN.md:Acceptance, TASK-001, TASK-002, TASK-008 |
| 2 | (Codex #2) Schema permits multiple `main` rows per institution | high | apply | The UNIQUE tuple includes `label`/`address`, so two `main` rows with different addresses both insert; add a partial unique index, a parser rule, and final-validation evidence | PLAN.md:Decisions, PLAN.md:Acceptance, TASK-001, TASK-002, TASK-008 |
| 3 | (Codex #3 + lens #12) TASK-008 does not demonstrate several PLAN.md criteria | med | apply | Three-failures-absent, out-of-polygon rejection, unresolved-`main` listing and the review-decision → CSV → parser round trip had no explicit evidence step | TASK-008 |
| 4 | (lens #1) `data/` never reaches the image; CLI and polygon defaults are CWD-relative | high | apply | Dockerfile copies only `src/`, `migrations/`; anchor both defaults to the package via `Path(__file__)`, copy `data/` into the image, state where the loader runs | PLAN.md:Decisions, TASK-002, TASK-003, TASK-007 |
| 5 | (lens #2) `pending` rows written as `manual`/`none`/`human` | high | apply | Contradicts PLAN.md AC ("`human` = resolved in the review tool") and makes a pending row indistinguishable from a deliberate `no_pin`; omit pending rows, the loader's missing-`main` count surfaces them | PLAN.md:Decisions, TASK-004, TASK-005 |
| 6 | (lens #3) Candidate `key` omits `address`, so unlabeled branches collide | high | apply | ДГ№13 has four label-less branches; the key must be the table's full UNIQUE tuple | TASK-004, TASK-005 |
| 7 | (lens #4) Seed re-run drops human decisions from the CSV | high | apply | "CSV containing the `auto` rows" loses `accepted`/`pinned`/`no_pin`; one renderer writes every decided entry | TASK-004, TASK-007 |
| 8 | (lens #5) `scripts/review_locations.py` beside `scripts/review_locations/` is un-importable | high | apply | Module/package name collision; shared helpers move to `scripts/location_review/` | PLAN.md:Decisions, TASK-004, TASK-005, TASK-006, TASK-007 |
| 9 | (lens #6) No mechanism for tests to import from `scripts/`; `ruff check .` lints it | med | apply | `scripts/__init__.py` + pytest `pythonpath = ["."]`, run the scripts with `-m`, state that CI's ruff covers them | TASK-004, TASK-005 |
| 10 | (lens #7) `tests/test_migrations.py` hard-codes the 0009 chain | med | apply | Head / `-1` / `-2` assertions all shift with 0010; TASK-001 must update them | TASK-001 |
| 11 | (lens #8) "Right amenity family" is never defined | med | apply | Define the `kind → amenity` table, confirm it against the captured Overpass fixture, cover it in the decision table test | PLAN.md:Decisions, TASK-004 |
| 12 | (lens #9) `street`/`approximate` unreachable; `pinned` is always `building` | med | apply | Drop `street` (rank 26–27 hits are discarded, nothing can produce it); give `pinned` a precision toggle so a block-level pin can be `approximate` | PLAN.md:Decisions, TASK-001, TASK-002, TASK-005, TASK-006, TASK-008 |
| 13 | (lens #10) CSV writer / decision mapping has two homes and a dependency inversion | med | apply | `write_file` lives in the loader module (TASK-002, symmetric with `parse_rows`); the decision → row mapping lives in `scripts/location_review/state.py`, created in TASK-004 and extended in TASK-005 | TASK-002, TASK-004, TASK-005 |
| 14 | (lens #11) The epic's `justfile` recipe deliverable is dropped | med | apply | Honour both the epic and the Decision: TASK-007 adds `be-load-locations` to the parent `yasli/justfile` (outside the PR) and the runbook names it | PLAN.md:Decisions, TASK-007 |
| 15 | (lens #13) TASK-008's `link_plan.py` prose is stale after d13317d | med | apply | Epics now live in this repo; `link_plan.py` roots on the git toplevel and works | TASK-008 |
| 16 | (lens #14) `just db-psql -c "…"` does not work | low | apply | The recipe takes no arguments; use `docker compose exec -T postgres psql …` from the `yasli/` parent | RESEARCH.md, TASK-001, TASK-007, TASK-008 |
| 17 | (lens #15) Two acceptance items depend on later tasks' artifacts | low | apply | Move the 77/15 count check to TASK-006 as a committed regression test; TASK-003's real run uses a hand-made sample | TASK-002, TASK-003, TASK-006, TASK-008 |
| 18 | (lens #16) Polygon test list omits Звездица | low | apply | `VARNA_SETTLEMENTS` has five villages | PLAN.md:Risks, TASK-002 |
| 19 | (lens #17) Flagged-row estimate inconsistent | low | apply | PLAN.md says ~20–30, everything else 25–35 | PLAN.md:Scope |
| 20 | (lens #18) "The in-memory session fixture" is not shared | low | apply | It is local to `tests/test_grao_loader.py`; say the new module defines its own | RESEARCH.md, TASK-003 |
| 21 | (lens #19) Flag semantics and rule 4 against a polygon-rejected candidate | low | apply | State: flags are per row, any flag ⇒ pending, an out-of-polygon candidate stays visible but is never acceptable, rule 4 compares in-polygon candidates only | PLAN.md:Decisions, TASK-004 |
| 22 | (lens #20a) RESEARCH.md references use `openspec/docs/…` without `../` | low | apply | `openspec/` lives in the `yasli/` parent, not this repo | RESEARCH.md |
| 23 | (lens #20b) openspec §3.4 revision note says "Phase 1.3" | low | defer | Outside this repo and this plan; filed as a backlog issue | — |
| 24 | (lens #20c) Plain index on `(kind, external_id)` duplicates the UNIQUE's leading columns | low | apply | Folded into row 2: the partial unique index on `main` plus the UNIQUE tuple cover phase 1.3's lookup; drop the plain index | TASK-001 |
| 25 | (Codex #1, remainder) Per-row seed provenance so an `auto` row could be re-checked offline | low | defer | Would need committed candidate snapshots or network at parse time — contradicts "parsing stays network-free" and "candidates file is gitignored"; worth a follow-up if a bad `auto` pin is ever reported | — |

Round-2 note: #25 was superseded — Codex pushed back in round 2 and it was applied as round-2 #2 (committed provenance file, cross-checked by the parser).
