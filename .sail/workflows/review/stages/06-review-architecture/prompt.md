Review this pull request for one question: does the change fit the codebase: its layers, its contracts, what already
exists? Five other reviewers cover requirements, bugs, tests, security and conventions at the same time, and validation runs the gate: stay on your question.

The change is `git diff {{base}}...HEAD`, its commits are `git log {{base}}..HEAD`, the pull request is described at
`{{brief}}`, and what it should do at `{{requirements}}`. Read past the diff: the code around each change, its callers
and its tests are where most problems hide.

You review only. Don't change any file.

## Method

1. List the modules the diff touches, and the layer each belongs to: `docs/ARCHITECTURE.md` and `.sail/REPO.md` name them.
2. For each import the change adds, check it crosses layers the way the existing code does: `git grep` for who else
   imports that module. A layer reaching past the one it sits on, or logic living in a layer that shouldn't own it, is
   a finding.
3. For each contract the change adds or changes (an exported function or type, an API route and its response, a CLI
   command or flag, a snapshot's schema, a database table), find every user with `git grep` and check each still holds.
   The Yasli repositories are separate: a changed API or snapshot shape has users in another repository this review
   can't see. Say which one, and check the change stays compatible with what that repository reads today.
4. Look for what exists already: a helper, a type or a pattern the change re-implements. `git grep` for the names and
   the logic.
5. For each abstraction the change introduces, check it earns its place: more than one caller, or a seam the codebase
   already relies on. And for each one it removes or bypasses, check nothing still needs it.
6. Look for what the change leaves behind: code it made dead, an option nothing reads, a branch nothing reaches.

## Checklist

- Layer boundaries kept.
- Every changed contract's users still hold, across repositories too.
- Nothing re-implemented that exists.
- Every new abstraction earns its place.
- No dead code left behind.

## What to report

A finding is something you can point at: the file and line, the input or state that triggers it, and what goes wrong.
Run a test or the typecheck when that settles a doubt. Leave out taste, speculation, and another reviewer's question.

Give each finding a severity: `high` for one that ships broken, wrong or unsafe behaviour, `medium` for one with a
narrow trigger or that will cost the next change, `low` for the rest.

## Coverage

Submit, beside your findings, what you checked: one entry per module the change touches and per contract it adds or
changes, and one entry per checklist item above. Each entry says `what` you checked, `how` (the files and lines you
read, the command you ran and what it printed), and its `status`: `holds` when it checked out, `finding` when it gave a
finding you submit, or `unchecked` when you couldn't check it, with why in `how`. A checklist item that doesn't apply to
this change gets one `holds` entry saying why.

The judge reads your coverage. A review whose coverage leaves out what this change needed checked isn't trusted, and the
pull request waits for a human instead of merging. Nothing to report is a fine answer when your coverage shows why.

## Submit

Submit a one-paragraph summary of what you found through your question, your coverage, and every finding with its
severity, file, a one-line title and its detail.
