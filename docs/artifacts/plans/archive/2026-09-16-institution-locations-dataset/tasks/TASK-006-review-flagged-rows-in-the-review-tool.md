# TASK-006: Review flagged rows in the review tool

Depends on: TASK-005
Suggested commit: `feat(data): add institution locations`

## Goal

Every row the seed script flagged has been resolved in the review tool, and a
handful of auto-accepted rows have been spot-checked. The resulting
`data/institution_locations.csv` is committed.

**This task is Ivo's, not the implementer's.** The implementer runs the seed
script and starts the tool; the decisions are a person's. TASK-007 and TASK-008
are blocked on it.

## Files

- `data/institution_locations.csv` — the committed artifact of record
- `data/institution_locations.provenance.json` — committed with it; one
  all-pass entry per `auto` row, written by the tool, never by hand
- `tests/test_institution_locations_data.py` — parses the committed pair and
  asserts their shape; the permanent guard that a hand edit cannot break them

## Acceptance

- [ ] The `To review` tab is empty. Every flagged row is `accepted`, `pinned`
      or `no_pin`
- [ ] At least 5 `auto` rows spot-checked from the `Auto-accepted` tab, chosen
      to include one village address (`с.Каменар`) and one block-relative
      address. If any is wrong, correct it (it becomes `human`) and note which
      rule let it through
- [ ] The three measured failures are resolved to the right place:
      `бул. "Чаталджа" 111`, `кв. Виница, ул. "Лазур" №2` and
      `ж.к."Владислав Варненчик" до бл.20` are pinned in Varna, not in
      Игнатиево, Константиново or Аксаково
- [ ] The 12 addressed branch buildings have coordinates; the 3 name-only
      branches ("Жирафче", "Другарче" under ДГ№17; "Бисерче" under ДГ№18) are
      `no_pin` with their label
- [ ] ДГ№13 "Мир" has 1 `main` + 4 `branch` rows, and its main pin
      (ул. Никола Михайловски **№6**) is a different building from its branch
      pin (ул. Н. Михайловски **1А**)
- [ ] Every `main` row left `no_pin` has a reason noted in the commit message
      (target: none)
- [ ] `parse_file` accepts the finished file
- [ ] `tests/test_institution_locations_data.py` passes: 77 `main` and 15
      `branch` rows, exactly one `main` per institution, every coordinate
      inside the polygon, no `auto` row that is not `osm_poi` + `main` +
      `building`, and exactly one provenance entry per `auto` row (this count
      check moved here from TASK-002, where the file did not exist yet)

Evidence: the committed CSV diff, `parse_file` run over it cleanly, and counts
by `verification` × `source` × `precision`.

## Steps

- [ ] Implementer: `uv run python -m scripts.seed_institution_locations`, then
      `uv run python -m scripts.review_locations`
- [ ] Work the `To review` tab top to bottom. Each row: read the address and the
      flag, look at the candidates, then `1`/`2` to accept, click to place, or
      `N` for no pin
- [ ] For block-relative addresses (`ж.к. "Младост" до бл.127`), use the
      "search in Google Maps" link to find the block, then place the pin on
      the kindergarten building next to it, not on the block itself. If only
      the block can be found, pin it and press `A` so the row lands as
      `precision=approximate` rather than claiming a building
- [ ] Spot-check 5 rows in the `Auto-accepted` tab
- [ ] Run `parse_file` over the result, add the data regression test, and
      commit the CSV and the provenance file together

## Notes

Budget 20–40 minutes. TASK-004 expects 25–35 flagged rows. About half have a
good candidate that only needs one keystroke, and the rest need a pin placed by
hand.

The review exists to catch the wrong pin that looks right, not the missing
pin. A blank is visible: the loader lists it and the page renders without a
map. A pin in the wrong village is not. When unsure, `N` is the safe answer.
