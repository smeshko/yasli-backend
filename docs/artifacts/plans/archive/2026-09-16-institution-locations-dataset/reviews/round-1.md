# Adversarial Review — Round 1

**Run:** 2026-09-15 19:50 UTC
**Branch:** feature/yas-7-institution-locations-dataset
**Base:** staging
**Commits reviewed:** dd25594f9d0656ba864ffc189fe8f9428bfd0ab3..97191ce4879268ef4a720a0cd1a5e1534ec4596e
**Reviewers:** Codex (`/codex-local:adversarial-review --scope branch --base staging`) and an independent `general-purpose` subagent lens, run in parallel per the `large` risk tier; findings merged and deduped before triage.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the dataset violates its human-review trust boundary, includes explicitly unsupported pins, and the review workflow can be stranded by a partial two-file write.

Findings:
- [high] Agent-generated coordinates are mislabeled as human-reviewed (data/institution_locations.csv:2-95)
  Commit b96eb57 states that Claude placed 29 rows through the review API, while the CSV records reviewed decisions only as verification=human. The governing task explicitly assigns these decisions to Ivo and says they must be a person's judgment. This obscures the actual trust level of coordinates that will drive parent-facing maps and leaves no way to isolate the 29 rows for independent review.
  Recommendation: Identify all agent-placed rows, independently review them by a named person before release, and only then mark them human. Otherwise add a distinct verification state and exclude those rows from production.
- [high] Partial two-file commit can make the review tool unrecoverable (src/yasli/ingest/institution_locations_loader.py:448-449)
  The writer replaces the CSV and provenance files separately. If the second replace fails or the process crashes after the CSV replace, the files may disagree. On restart, ReviewState strictly parses this pair before reconciliation; stale or missing provenance therefore aborts startup before the candidates state can repair it. Correcting an auto row to human directly exercises this failure mode because its provenance entry must disappear.
  Recommendation: Introduce a recoverable transaction protocol for the pair, such as versioned artifacts with an atomically switched manifest or a journal containing target hashes. Recover before strict parsing, and add fault injection that fails specifically on the second replace and verifies restart recovery.
- [high] Two branches explicitly designated unpinnable ship with coordinates (data/institution_locations.csv:31-32)
  Другарче and Жирафче have empty addresses but are assigned manual building coordinates. PLAN.md says these name-only branches cannot be pinned from available sources, and TASK-006 requires all three name-only branches to be no_pin. Unsupported building pins create exactly the plausible-but-wrong navigation outcome the blank-not-guess policy was intended to avoid.
  Recommendation: Change both rows to precision=none with null coordinates unless independently verifiable source evidence is documented and the specification is explicitly revised and approved.

Next steps:
- Complete an independent human review of all agent-generated and name-only-branch coordinates.
- Make CSV/provenance persistence crash-consistent and test failure between the two replacements.

## Subagent output (independent lens, `general-purpose`)

<!-- Pasted verbatim from the subagent's final report. Do not edit. -->

## Review: `feature/yas-7-institution-locations-dataset` vs `staging`

Outcome: no high-severity bugs. Committed data is internally consistent (37 `auto` rows all match the Overpass fixture, one `main` per institution, nothing outside the polygon). Full in-scope suite passes: 258 passed locally; the 44 Postgres-backed tests pass against `yasli_test`. Findings below, most severe first.

1. `scripts/review_locations.py:174-217` — **med** — The review server accepts cross-origin writes (no `Origin`/`Host`/`Content-Type` check, `OPTIONS` → 501).
   Scenario: while the tool is open, any web page in another tab does `fetch('http://127.0.0.1:8765/api/decision', {method:'POST', headers:{'Content-Type':'text/plain'}, body:'{"key":…,"status":"no_pin"}'})`. `text/plain` is a CORS "simple request" (no preflight), the server parses the body as JSON regardless of content type, and the decision lands in `data/institution_locations.csv`. `/api/undo` needs no body at all. Keys are guessable from the committed CSV.
   Verified: reproduced — POST with `Content-Type: text/plain`, `Origin: https://evil.example` → 200, CSV changed.

2. `src/yasli/ingest/institution_locations_loader.py:446-449` (`write_file`) + `scripts/location_review/state.py:385-391` (`persist`) — **med** — The CSV and provenance file are two separate renames, so the "crash between the writes" the Decision says is repaired has a third window that is not.
   Scenario: a reviewer confirms an `auto` row (→ `osm_poi`/`human`, provenance entry must go). `persist` writes the candidates file (old hash), renames the CSV, then dies before the provenance rename. Now committed = (new CSV, old provenance) → hash mismatch → lineage rule rebuilds from committed files → `parse_file` raises `stale provenance: entries with no auto row: kindergarten/38` → both the review tool and the seed script refuse to start until someone runs `git checkout data/`. Same shape for a seed run that creates a new `auto` row (CSV has it, provenance doesn't). Decision text says "nothing is lost either way"; here recovery is manual.
   Verified: reproduced (simulated the half-write; `create_server` raised `LocationRowError`, candidates hash no longer matches).

3. `scripts/seed_institution_locations.py:504-529` (`plan_refresh`) — **low** — `address_changed` is lost or kept depending on dict iteration order when both the old-address and new-address `main` entries exist.
   Scenario: committed CSV still has the old-address row (e.g. after a pull/checkout), local candidates already has a pending new-address entry; `reconcile` yields both. If the old key is visited first, the fresh `address_changed` entry is overwritten by the plain pending one (`flags: []`), so the row can be auto-accepted on this run instead of going to review as the AC requires.
   Verified: reproduced — `('old','new')` → `[]`, `('new','old')` → `['address_changed']`.

4. `src/yasli/ingest/institution_locations_loader.py:267` vs `:402-407` — **low** — The parser strips `address`/`label`, the renderer does not, so a key with leading/trailing whitespace changes identity on a round trip.
   Scenario: an institution address with a trailing space (the snapshot contract does not strip; `_optional_strings_non_empty` only rejects `""`) is written to the CSV verbatim, parsed back stripped. On any hash mismatch `reconcile` produces two entries for the same building (stripped/decided + unstripped/pending); the pending one can never be resolved (second `main` → 422), and a seed re-run that auto-accepts the unstripped one crashes in `write_file` every run until the candidates file is deleted. Not triggered by today's data.
   Verified: round trip reproduced (`'ул. Батак 6 '` → `'ул. Батак 6'`); the downstream chain is read code path only.

5. `src/yasli/ingest/institution_locations_loader.py:264-315` — **low** — Parser/DB parity gap: column lengths (`label` 128, `address` 256, `external_id` 16) are not checked by the parser.
   Scenario: an over-long branch address passes the parser and the review tool's `validate`, so the loader TRUNCATEs and then fails at INSERT with `DataError` → exit 5 "database error", no line number. The transaction rolls back, so no data loss.
   Verified: read code path only.

6. `src/yasli/ingest/institution_locations_loader.py:242-261` (`_check_provenance_entry`) — **low** — Numeric provenance fields are not type-checked.
   Scenario: `"title_matches": true` passes (`True == 1`); `"geocode_distance_m": "999"` raises an uncaught `TypeError` (crash without a line number, exit code 1 not 3). Only reachable with a hand-edited provenance file.
   Verified: reproduced both.

7. `scripts/review_locations.py:208-214` — **low** — A non-`LocationRowError` raised inside `state.validate` (before anything is persisted) is reported as "saved to the candidates file, but regenerating the CSV failed".
   Scenario: `_read_body` uses `json.loads` defaults, so `{"lat": Infinity, …}` is accepted; `render_csv` raises `decimal.InvalidOperation` → 500 with a message claiming a save that did not happen (candidates file unchanged). `NaN` is handled (422, though the message says "outside the polygon" rather than "not a number").
   Verified: reproduced.

8. `tests/test_institution_locations_loader.py:806-817` — **low** — `test_cli_default_path_resolves_to_repo_data_dir_from_any_cwd` no longer tests its claim.
   Scenario: with the committed file present the branch taken is `assert str(tmp_path) not in result.stderr`; the CLI exits 2 on the missing `DATABASE_URL` and stderr never mentions any path, so the assertion is vacuous — it would pass even if the default resolved to the cwd.
   Verified: reproduced (ran the CLI from `/tmp`: exit 2, stderr is the `DATABASE_URL` validation error only).

9. `data/institution_locations.csv` (kindergarten/50) — **low**, data spot-check — Branch `Другарче` is pinned 4 m from ДГ№17's `main` pin (43.216930,27.923966 vs 43.216893,27.923951); every other branch is on a distinct building. Looks like the parent building was pinned for a name-only branch. Either it genuinely shares the yard, or it should be `no_pin` like `Бисерче`.
   Verified: reproduced with haversine over the committed rows.

### Coverage by category

1. Parser/loader — items 2, 4, 5, 6. Quoting/Cyrillic normalisation, empty/NaN/inf coordinates, `precision=none`, duplicate `main`, three guards, `--allow-incomplete`/`--dry-run`, transaction boundary and idempotency all behave as specified. Forged `auto` rows: a row without a pair fails; a forged *pair* parses (accepted in Risks) — note the parser could cheaply also check `settlement_from_address(row.address) == entry.address_settlement`, which it does not.
2. Model/migration/CHECK parity — item 5 only. CHECKs, partial unique index, FK (`RESTRICT` is safe: ingest never deletes institutions), downgrade all correct and verified on Postgres.
3. Point-in-polygon — nothing found (lon/lat order correct, holes handled, ring closure irrelevant to the algorithm; on-edge ambiguity is documented).
4. Seed auto-accept rules — item 3. Rules 1–4 are applied to the right candidate sets (uniqueness within family from both sides, rule 4 on in-polygon geocodes only); service failures fail safe (row flagged, or run aborts before persisting).
5. Review tool security/integrity — items 1, 2, 7. No path traversal or arbitrary write; untrusted OSM/Nominatim strings are escaped in `index.html`; a stale candidates file cannot revert a committed decision.
6. Tests — item 8. Everything else asserts on the code path it claims.
7. Committed data — item 9 only; parses under the current parser, every `auto` row has an all-pass entry matching the fixture POI, exactly one `main` per institution, all inside the polygon.

## Triage

<!--
Verdict values:
  fix    — real bug; address now in this branch
  defer  — has merit but out of scope; capture as a follow-up
  reject — contradicts an explicit Decision in PLAN.md, or is taste/speculation

Findings from both reviewers merged and deduped; the source column names the
originals (C = Codex, S = subagent). Rows marked `ask` were put to Ivo
before round 2 and carry his verdict below.
-->

| # | Finding | Source | Severity | Verdict | Rationale | Commit |
|---|---------|--------|----------|---------|-----------|--------|
| 1 | 29 rows that Claude placed through the review tool's API (Google Maps listing checked against name + address) are recorded as `verification=human`; the CSV cannot tell them from Ivo's 26 | C1 | high | reject | TASK-006 assigns the decisions to a person; commit b96eb57 discloses that Claude placed 29 rows through the tool's API, with the method (Google Maps listing checked against name and address, accept a candidate within 100 m else pin the listing) and counts, and Ivo authored and finalised that commit. `human` here means "decided in the review tool, not by the four rules", and the commit is the audit record. Put to Ivo on 2026-09-16: keep as-is; REVIEW.md and the PR body repeat the disclosure. The rows are not individually identifiable, which stays a known limitation. | |
| 2 | Torn CSV/provenance write: a crash between the two renames leaves a pair the strict parser rejects, so the review tool and the seed script refuse to start until someone runs `git checkout data/` | C2, S2 | high | fix | The Decision says "nothing is lost either way"; today this window needs manual recovery. Stage both files before renaming so the window is two syscalls, always rename the CSV first, and recognise the one torn shape that leaves (the CSV byte-identical to what the candidates file regenerates; the provenance file is not evidence, a stale candidates file would match the old half too) and regenerate from the candidates file. A hand-corrupted file still fails loudly. | `f504284` |
| 3 | Name-only branches Жирафче and Другарче ship with `manual`/`human` building pins although PLAN.md and TASK-006 expected `no_pin` | C3 | high | reject | Commit b96eb57 records that Ivo, the person TASK-006 assigns these decisions to, pinned them himself rather than leaving them blank. `source=manual` + `verification=human` is exactly what the schema means by a person's pin, and overriding the seed's "no source" prediction with local knowledge is the review tool's purpose. The AC text in PLAN.md is now a superseded prediction, not a violated rule. | |
| 4 | Другарче's pin is 4 m from ДГ№17's `main` pin; every other branch sits on a distinct building | S9 | low | reject | Ivo placed it. Put to him on 2026-09-16: the pin is intended — the branch shares the parent's building/yard. | |
| 5 | Review server accepts cross-origin writes: no `Content-Type`/`Origin`/`Host` check, and a `text/plain` POST is a CORS simple request that skips preflight | S1 | med | fix | Reproduced: any open tab can write decisions into the committed CSV while the tool runs. Require `application/json` (forces a preflight the server refuses), and reject foreign `Origin`/`Host`. | `4042757` |
| 6 | `plan_refresh` keeps or drops `address_changed` depending on dict iteration order when both the old- and new-address `main` entries exist | S3 | low | fix | Order-dependent code on the path that decides whether a moved institution is re-reviewed; a row could be auto-accepted instead. Merge the flag whichever key is visited first. | `09ad55e` |
| 7 | Parser strips `address`/`label`; the renderer and the seed's key sites do not, so a trailing space in `institutions.address` changes a building's identity on a round trip | S4 | low | fix | Not triggered by today's data, but the snapshot contract does not strip and the failure mode is a row that can never be resolved. Strip where DB strings become keys and in the renderer. | `90cbe66` |
| 8 | Parser does not check column lengths, so an over-long cell passes `validate` and fails at INSERT after TRUNCATE with a bare database error | S5 | low | fix | Parser/DB parity is a stated Decision. Derive the limits from the model's columns so they cannot drift. | `6a8f7b3` |
| 9 | Provenance numeric fields are not type-checked: `true` passes as `1`, a string distance raises a bare `TypeError` | S6 | low | fix | Cheap hardening; a hand-edited provenance file should fail with a line number and exit 3, not a traceback. | `4a2d166` |
| 10 | `Infinity` in a decision body reaches `render_csv`, and the 500 claims the decision was saved to the candidates file when nothing was written | S7 | low | fix | Reject non-finite coordinates and JSON `NaN`/`Infinity` with 400 before validation. | `ea3e65d` |
| 11 | `test_cli_default_path_resolves_to_repo_data_dir_from_any_cwd` asserts nothing once the committed file exists | S8 | low | fix | A test that cannot fail. Assert the resolved default path directly. | `e977c8d` |
