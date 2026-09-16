# Adversarial Review — Round 2

**Run:** 2026-09-16 03:41 UTC
**Branch:** feature/yas-7-institution-locations-dataset
**Base:** staging
**Commits reviewed:** dd25594f9d0656ba864ffc189fe8f9428bfd0ab3..e977c8d (round-1 fixes f504284..e977c8d included)
**Prior rounds in scope:** reviews/round-1.md
**Reviewer:** Codex (`/codex-local:adversarial-review --scope branch --base staging`, round-2 focus text)

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: two rejected round-1 trust-boundary findings remain valid, and the crash-recovery fix can silently overwrite corrupted provenance.

Findings:
- [high] Agent-generated coordinates remain indistinguishable from human-reviewed decisions (data/institution_locations.csv:2-95)
  Commit b96eb57 states that Claude placed 29 coordinates, but every affected row is recorded as verification=human and the rows are not individually identified. Merely authoring/finalizing the commit is not an independent review of those decisions. This contradicts TASK-006's explicit requirement that the decisions be a person's and prevents operators from isolating potentially unreviewed pins after a bad-location report.
  Recommendation: Identify the 29 agent-decided rows and have a named person independently verify each before retaining verification=human; otherwise introduce a distinct verification state and exclude them from production.
- [high] Name-only branches still violate the explicit blank-not-guess requirement (data/institution_locations.csv:31-32)
  Жирафче and Другарче still carry building pins despite TASK-006 requiring all three name-only branches to be no_pin and PLAN.md stating that name-only branches have NULL coordinates. The rejection rationale supplies only an assertion that Ivo intended the pins; it does not document independently verifiable source evidence or revise the still-current acceptance criteria. A plausible but wrong building pin is precisely the failure the specification says is worse than a visible blank.
  Recommendation: Set both rows to precision=none with null coordinates, or document verifiable evidence for each location and formally revise the plan/task acceptance criteria before shipping.
- [medium] Torn-write recovery misclassifies any provenance failure and overwrites evidence (scripts/location_review/state.py:330-335)
  load_committed catches every LocationRowError and declares the pair torn whenever the CSV matches the local candidates file. In normal steady state that CSV match is expected, so a missing, malformed, or hand-corrupted provenance file that fails validation is indistinguishable from an interrupted rename. ReviewState then persists immediately and silently replaces the provenance, contradicting the claim that hand corruption always fails loudly and potentially erasing the artifact needed to audit auto-accepted coordinates.
  Recommendation: Record the intended CSV and provenance hashes or a transaction identifier in the candidates journal before renaming, and recover only when those exact target artifacts prove an interrupted transaction; otherwise propagate the validation failure.
- [low] Provenance type-check fix still accepts invalid all-pass values (src/yasli/ingest/institution_locations_loader.py:254-276)
  The new title_matches check accepts 1.0 because it compares equal to integer 1, while geocode_distance_m accepts NaN and negative infinity because both are floats and neither compares greater than 150. Direct calls to _check_provenance_entry confirmed all three values are accepted. This leaves malformed provenance able to attest that an auto row passed its rules despite commit 4a2d166 claiming strict type enforcement.
  Recommendation: Require type(title_matches) is int and title_matches == 1; require distance to be a finite, non-negative int or float. Add regression cases for 1.0, NaN, positive/negative infinity, and negative distances.

Next steps:
- Independently review and identify all 29 agent-decided rows.
- Resolve or formally respecify the two name-only branch pins.
- Replace heuristic torn-pair detection with journaled target hashes.
- Complete strict finite/range validation for provenance numbers.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Claude-placed rows remain indistinguishable from Ivo's; Codex pushes back on round-1 #1's rejection | high | reject | Ivo's decision on 2026-09-16, made with this exact concern in front of him: keep as-is. The commit message is the audit record of method and counts; REVIEW.md and the PR body repeat it and name the non-identifiability as a known limitation. A second push on the same point does not change whose call it is. | |
| 2 | Жирафче and Другарче keep building pins; Codex pushes back on round-1 #3's rejection and asks for the acceptance criteria to be revised | high | reject | Ivo pinned both and confirmed the Другарче pin on 2026-09-16 (round-1 #4). `manual` + `human` is the schema's word for a person's pin. PLAN.md is immutable from review on (review-plan's rule), so the AC text is not edited; REVIEW.md records that the `no_pin` expectation was the seed's prediction and the reviewer overrode it. | |
| 3 | Torn-write recovery declares any provenance parse failure "torn" when the CSV matches local state, so a hand-corrupted or malformed provenance file is silently regenerated | med | fix | Correct: in steady state the CSV always matches local, so the heuristic could not tell a torn pair from a corrupted provenance file. Replace it with a journal: `persist` stamps the candidates file with the hashes of the CSV and provenance it is about to write and of the provenance file on disk now, and clears the journal after both renames; a pair is torn only when the CSV is exactly the journalled one and the provenance file is exactly the previous one. Everything else propagates. Fault-injected on the second rename. | `5d72773` |
| 4 | Provenance checks still accept `title_matches: 1.0`, and `geocode_distance_m` NaN, -inf and negatives | low | fix | Correct: `1.0 == 1` and NaN/-inf never exceed 150. Require an exact int 1 and a finite, non-negative distance; regression cases for each value. | `10b6cfc` |
