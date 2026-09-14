# Projects

Umbrella groupings of related epics for **backend**. A **project** bundles
several epics under one theme (e.g. a redesign spanning many screens) and maps
to a **Linear Project**. A lone, feature-bound epic does not need one — it stays
project-less. Projects are additive: epics without a project behave exactly as
before.

> **Naming:** the product itself is the Linear **team**, not a project. The
> projects listed here are groupings *inside* that team.

## Status legend

| Status | Meaning |
|---|---|
| Planned | Defined but no epic started |
| In progress | At least one member epic is in progress |
| Done | Every member epic is Done |

## Projects

| Project | Epics | Linear | Status |
|---|---|---|---|
| [Institution profiles](./institution-profiles.md) | 2 | [link](https://linear.app/ivo-tsonev/project/institution-profiles-f2b615f2efd2) | Planned |

## How to work with projects

1. `create-project` scaffolds a charter here and (optionally) a Linear Project.
2. File an epic under it with `create-epic --project <slug>` — the epic becomes a
   Linear **parent issue** whose `project` is set to this Linear Project.
3. Phases (sub-issues) and their PRs roll up into the Linear Project automatically.
4. Closing the Linear Project when the last epic ships is a **manual** call — the
   boundary is editorial.
