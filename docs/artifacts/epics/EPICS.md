# Implementation Epics

This document tracks the implementation epics for **yasli-backend**. Each epic is a
self-contained unit of functionality; each phase within an epic is sized to fit a
small-to-medium pull request and maps to exactly one plan under
[`../plans/`](../plans/).

## Status legend

| Status | Meaning |
|---|---|
| Planned | Defined but not started |
| Ready for dev | All dependencies met; can be picked up |
| In progress | At least one phase has been merged |
| Done | All phases complete and validated against the acceptance criteria |
| Blocked | Waiting on a prerequisite epic |
| Deferred | Not being built; the epic file records why, and what would reopen it |

## Epic status

| # | Epic | Phases | Dependencies | Status |
|---|------|--------|--------------|--------|
| 1 | [Institution data foundation](./01-institution-data-foundation.md) | 3 | — | Done |
| 2 | [Free-places API](./02-free-places-api.md) | 1 | Epic 01 | Deferred |

## Other repos

`yasli` is three nested git repositories; each owns its own epics, and no phase
spans repos. Cross-repo dependencies are named in each epic's `Depends on:` line.

- [backend epics](../../../../backend/docs/artifacts/epics/EPICS.md)
- [scraper epics](../../../../scraper/docs/artifacts/epics/EPICS.md)
- [frontend epics](../../../../frontend/docs/artifacts/epics/EPICS.md)

## How to work with these epics

1. Confirm this epic's dependencies are `Done` in the table above.
2. Open the epic file and start with its first phase.
3. Turn a phase into a plan: `create-plan` with `--epic <NN> --phase <NN>.<M>`
   (links the plan to the phase both ways). Then `validate-plan` →
   `implement-plan` → `review-plan` → `create-pr` → `archive-plan`.
4. Each phase lands as its own pull request.
5. The plan's final-validation task ticks the phase + epic-level acceptance
   criteria and updates this table — promote the row to `In progress` after the
   first phase merges, and to `Done` when the last one does.
