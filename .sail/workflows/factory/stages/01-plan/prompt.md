Write an implementation plan for the change the brief asks for. You only plan: read the code, never change it.

## 1. Explore

Gather enough context to plan without guessing:

- Read the brief at `{{brief}}` in full: the ticket, its acceptance criteria and its comments.
- Locate the entry points, types, modules and tests the change touches. Follow imports and calls far enough to see how
  the pieces connect. Read `docs/ARCHITECTURE.md` for how the repository fits together.
- Check recent history for related changes: `git log --oneline -20`.
- Note the files likely to change, the patterns to follow, the constraints, and what is still uncertain.

You read and never run: not the tests, not the gate, and no scratch file outside `$STAGE_OUT`. Reason from the code
and the tests as written: the tests take minutes, and validation runs them after implement.

## 2. Resolve every question yourself

No one answers questions during this run. Settle each open point from the ticket, the code and the conventions, and
record it as a Decision or an Assumption. Where two approaches exist, reason through both, pick one and record why.

If the ticket is too vague to plan without guessing its goal or its acceptance, end the step **blocked**, naming the
questions a human must answer. Don't plan around a guess.

## 3. Write the plan

`plan.md` in `$STAGE_OUT` holds the plan's template: complete it in place, replacing every placeholder and keeping its
headings. Reference concrete paths and function names, never vague descriptions.

Classify the risk:

| Risk | Meaning |
|---|---|
| `tiny` | under 30 min, a single file, no new tests |
| `small` | under 2 h, isolated, existing tests cover it |
| `medium` | half a day, cross-file, new tests required |
| `large` | days, an architectural change, significant test work |
| `high` | critical path, infrastructure, or a breaking change |

Break the work into tasks, numbered `TASK-001`, `TASK-002`, … in order:

- Each task is small enough to make one commit. Prefer additive, incremental steps over large rewrites.
- `impl` is code work, proven by tests; `checklist` is anything else, such as regenerating a generated file.
- A task's Acceptance items are each demonstrable at runtime, and its Evidence line names the output that proves them:
  a named test passing, a command transcript, a log excerpt.
- A task's suggested commit is a Conventional Commits subject, `feat(<scope>): <what it does>`, with no ticket
  reference: the workflow appends it.
- A task's tests are part of the task: implement writes them first, in the task's own commit. Never plan a task that
  only writes tests, or one that only makes earlier tests pass.
- Final validation is not a task: the workflow runs `.sail/lib/gate.sh` after the last task.
- Implement may write only `src/`, `tests/`, `scripts/`, `schemas/`, `migrations/`, `data/`, `public/`, `docs/`,
  `.sail/`, the root configs, `README.md` and `CLAUDE.md`. If the change needs any other path, end the step **blocked**,
  naming the path: implement would block on it.
- Implement may add a dependency with the repository's package manager, and the task that first imports it adds it.
  A program installed on the machine is not one: CI has only what the manifest and the lockfile name. A dependency
  changes a gate file, so a person merges that pull request: add one only when the ticket can't be done without it.

## 4. Plan the demonstration

Once the pull request is open, the review workflow shows the change working the way a user would see it, and checks it
against the plan's Demonstration section, which the pull request's body carries and you write now, before any code
exists. Pick the change's surface from the Demonstration section of `.sail/REPO.md`, or `none` when nothing a user runs
changes: a refactor, types, docs, tests alone. When a change shows on more than one surface, pick the one closest to the
user.

For each acceptance criterion, write one bullet: the scenario to set up and what to observe, exact enough to check
without judgment: an exit code, an output line, a response field, the text an element shows. For `none`, write why
nothing can be shown, and submit that reason.

Every scenario runs the real surface, never a test: validation has run the tests already. A criterion only a test can
observe gets no bullet: name the test in its task's Evidence.

## 5. Submit

Submit the plan's slug (kebab-case, a few words), the Conventional Commits scope its commits share, its risk, and its
tasks, each with its id, title, type and suggested commit, matching the plan's Tasks list.
