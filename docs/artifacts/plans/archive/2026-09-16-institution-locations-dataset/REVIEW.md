# Review Summary — institution-locations-dataset

**Rounds:** 3
**Fix commits:** f504284..98a3871 (11 commits)

Round 1 ran two reviewers in parallel, as the plan's `large` risk tier asks: Codex and an independent `general-purpose` subagent lens, merged and deduped before triage. Rounds 2 and 3 were Codex alone. Round files with verbatim reviewer output and the triage tables: `reviews/round-1.md`, `reviews/round-2.md`, `reviews/round-3.md`.

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 11 (3 Codex, 9 subagent, 1 shared) | 8 | 0 | 3 |
| 2     | 4 | 2 | 0 | 2 |
| 3     | 3 | 1 | 0 | 2 |

## Fixes

### Round 1
- `f504284` — A crash between `write_file`'s two renames left a new CSV next to the old provenance file, which the strict parser rejects, so neither the review tool nor the seed script could start. Both files are now staged before either rename, the CSV is always renamed first, and the state module recognises and repairs the torn pair from the candidates file. (round-1 #2; superseded in round 2 by the journal, `5d72773`)
- `4042757` — The review server accepted cross-site writes: a `text/plain` POST from any open tab skipped the CORS preflight and landed a decision in the committed CSV. It now refuses a foreign `Host` on every method, and on POST a non-JSON body or a foreign `Origin`. (round-1 #5)
- `09ad55e` — `plan_refresh` kept or dropped the `address_changed` flag depending on dict order when both the old- and new-address `main` entries were present; a moved institution could be auto-accepted instead of reviewed. Order-independent now, and a person's decision on the new address stands alone. (round-1 #6)
- `90cbe66` — The parser strips `label`/`address` but the renderer and the seed's key sites did not, so a trailing space in `institutions.address` became a second, unresolvable building on a round trip. Stripped at every point a DB string becomes a key, and in the renderer. (round-1 #7)
- `6a8f7b3` — Over-long `external_id`/`label`/`address` cells passed the parser and failed at INSERT after TRUNCATE with a bare database error. Limits are read off the model's columns and checked with a line number. (round-1 #8)
- `4a2d166` — Provenance fields were compared, not type-checked: `true` passed as `1`, a quoted distance raised a bare `TypeError`. (round-1 #9)
- `ea3e65d` — `Infinity`/`NaN`/`"inf"` coordinates reached the renderer and came back as a 500 claiming a save that never happened. Refused as a 400 before validation; persist failures are now the only thing reported as a partial save. (round-1 #10)
- `e977c8d` — `test_cli_default_path_resolves_to_repo_data_dir_from_any_cwd` could not fail once the committed file existed; it now asserts the resolved path. (round-1 #11)

### Round 2
- `10b6cfc` — The round-1 provenance checks still accepted `title_matches: 1.0` and NaN, −inf or negative distances (none of which "exceed" 150). Exact int 1 and a finite, non-negative distance are required, with a regression case per value. (round-2 #4)
- `5d72773` — The round-1 torn-pair recovery declared any provenance parse failure "torn" whenever the CSV matched local state, which in steady state it always does, so a hand-corrupted provenance file was silently regenerated. Replaced by a journal: `persist` stamps the candidates file with the hashes of the CSV and provenance it is about to write and of the provenance file on disk, and clears it once both renames land; a pair is torn only when the CSV is exactly the journalled one and the provenance file is exactly the previous one. Fault-injected on the second rename. (round-2 #3)

### Round 3
- `98a3871` — The round-2 finite check called `math.isfinite` on integers too, and `float()` of an oversized JSON integer (`10**1000`) raises `OverflowError`, escaping the line-numbered error. Integers are now compared as integers; the plain `ValueError` `json.loads` raises for an integer past Python's digit limit is caught as "not valid JSON". (round-3 #3)

**Stop rule.** Round 3 still produced a `fix` row, which by the shared protocol is the point to stop and ask rather than run a fourth round. The row is a three-line regression of round 2's own hardening on a hand-edited-file path, not a brittle area of the plan, so the act-and-stop option was taken: fixed, recorded, no fourth round. Ask for another pass if you want one.

## Deferred

- None. No finding in any round was deferred, so no Linear follow-up was filed.

## Rejected

- (round-1 #1, raised again as round-2 #1) 29 of the 57 `verification=human` rows were placed by Claude through the review tool's API (Google Maps listing checked against name and address; accept an existing candidate within 100 m, else pin the listing) and the CSV cannot tell them from Ivo's 26. Commit b96eb57 discloses the method and counts and Ivo authored and finalised it; `human` in this schema means "decided in the review tool, not by the four rules", and the commit is the audit record. Put to Ivo on 2026-09-16 with the concern in front of him: keep as-is. **Known limitation:** the 29 rows are not individually identifiable, so a spot-check of them means re-reviewing the 57 human rows.
- (round-1 #3, raised again as round-2 #2) Name-only branches Жирафче and Другарче ship with `manual`/`human` building pins although PLAN.md and TASK-006 expected `no_pin`. Ivo, the person TASK-006 assigns the decisions to, pinned them himself rather than leaving them blank (commit b96eb57); `source=manual` + `verification=human` is the schema's word for a person's pin, and overriding the seed's "no source" prediction with local knowledge is the review tool's purpose. PLAN.md is immutable from review on, so its AC text is not edited; it is a superseded prediction, not a violated rule.
- (round-1 #4) Другарче's pin is 4 m from ДГ№17's `main` pin, while every other branch sits on a distinct building. Ivo placed it and confirmed on 2026-09-16 that the branch shares the parent's building; the pin is intended.
- (round-2 #1 and #2, round-3 #1 and #2) Codex re-raised the two items above in both later rounds with the same recommendations. Each was rejected on the same grounds; the decisions were Ivo's, made with the concern in front of him.
