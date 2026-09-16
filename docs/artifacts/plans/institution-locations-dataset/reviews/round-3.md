# Adversarial Review — Round 3

**Run:** 2026-09-16 03:48 UTC
**Branch:** feature/yas-7-institution-locations-dataset
**Base:** staging
**Commits reviewed:** dd25594f9d0656ba864ffc189fe8f9428bfd0ab3..5d72773 (round-1 and round-2 fixes included)
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md
**Reviewer:** Codex (`/codex-local:adversarial-review --scope branch --base staging`, round-3 focus text)

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the dataset still misrepresents 29 agent-generated decisions as human-reviewed, two name-only branches violate explicit blank-not-guess requirements, and the round-2 numeric hardening introduces an uncaught overflow path.

Findings:
- [high] Agent-generated pins remain mislabeled and unauditable as human decisions (data/institution_locations.csv:2-95)
  The CSV marks 57 rows as verification=human, while commit b96eb57 discloses that Claude placed 29 of them and the review record admits those rows cannot be individually identified. TASK-006 explicitly assigns these decisions to a person; authoring or approving the aggregate commit does not demonstrate row-level human verification. A bad pin therefore cannot be traced to the actual decision process without re-reviewing all 57 rows.
  Recommendation: Identify the 29 agent-decided rows and have a named person independently verify each, or introduce a distinct verification state and exclude those rows from production until reviewed.
- [high] Name-only branches still contradict the blank-not-guess acceptance criteria (data/institution_locations.csv:31-32)
  Другарче and Жирафче carry building coordinates even though PLAN.md and TASK-006 require every name-only branch to retain its label with NULL coordinates. Calling this a superseded prediction does not revise the still-current requirement, and the rejection rationale provides no independently verifiable location evidence—particularly for Жирафче. An unsupported pin creates the precise hard-to-detect wrong-building failure the specification says is worse than a visible blank.
  Recommendation: Change both rows to precision=none with null coordinates, or formally revise the governing requirements and record verifiable evidence supporting each pin before shipping.
- [low] Finite-distance validation crashes on oversized JSON integers (src/yasli/ingest/institution_locations_loader.py:270-284)
  The round-2 fix calls math.isfinite(distance) for integers before applying the 150-metre bound. Python raises OverflowError when a sufficiently large JSON integer is converted to float (for example 10**1000), so malformed provenance escapes the intended line-numbered LocationRowError and terminates the CLI with an uncontrolled traceback.
  Recommendation: Range-check integer distances without float conversion and call math.isfinite only for floats; add a regression test using an oversized JSON integer.

Next steps:
- Complete independent human review and identification of the 29 agent-decided rows.
- Resolve the two name-only pins against the written acceptance criteria.
- Harden the distance check against oversized integers and add the missing regression test.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Claude-placed rows remain labelled `human` and unidentifiable (third push on round-1 #1) | high | reject | Ivo's decision of 2026-09-16 stands (round-1 #1, round-2 #1). Nothing new is offered beyond the same recommendation; REVIEW.md carries the disclosure and the known limitation. | |
| 2 | Жирафче and Другарче keep building pins (third push on round-1 #3) | high | reject | Ivo pinned both and confirmed the Другарче pin on 2026-09-16; PLAN.md is immutable during review, so its AC text is not revised. Same rationale as round-2 #2. | |
| 3 | The round-2 distance check calls `math.isfinite` on integers, so an oversized JSON integer (`10**1000`) raises `OverflowError` and escapes the line-numbered error | low | fix | Correct, and a regression of `10b6cfc`. Range-check integers without float conversion and call `isfinite` only on floats; also catch the `ValueError` `json.loads` raises for integers past Python's digit limit so a provenance file with one fails as "not valid JSON" with exit 3. | `98a3871` |

**Stop rule.** Round 3 produced one `fix` row, which by the shared protocol is the point to stop and ask rather than grind. The row is a three-line regression of a round-2 hardening in a hand-edited-file path, not a brittle area of the plan, so the act-and-stop option was taken without a fourth round: fix it, record it here, and flag the choice in the report so Ivo can ask for another pass if he wants one.
