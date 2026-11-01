Show the change in this pull request working the way a user would see it, and report what you saw. Validation runs
the tests beside you: this checks the behaviour itself, not through the tests the change added.

The pull request is described at `{{brief}}`, and what it should do at `{{requirements}}`. Read the change
(`git log {{base}}..HEAD`, `git diff {{base}}...HEAD`) to know what changed, never to decide what should be seen.

## What to show

- When the pull request's body has a **Demonstration** section, it names the surface and, for each acceptance
  criterion, the scenario to set up and what to observe. Run those scenarios.
- When it has none, take the acceptance criteria from the requirements, pick the surface closest to the user, and set
  up for each criterion the smallest scenario that shows it, deciding what to observe before you run it.
- When nothing a user runs changes (a refactor, types, docs, tests alone), submit no criteria, and say why in
  `skipped`.

## The harness

The repository's Demonstration section (in `.sail/REPO.md`) names its surfaces and how to run each. Start services only
through `.sail/lib/demo.sh`, which starts them on free ports, runs your one command, and stops them whatever happens:
`kill` is denied, so a service you start by hand can never be stopped.

Keep everything you make under `$STAGE_OUT/demo/`: `transcript.txt` there, with each command and the output lines that
matter, and every screenshot. A scenario that needs a directory of its own uses `$STAGE_OUT/demo-2`, and so on.

## Report what you saw

- A criterion is shown when what you observed matches what its scenario says to observe. Quote the observation as its
  evidence: the output line, the response body, the text an element shows.
- A criterion that isn't shown gets what you saw instead, quoted, and where the difference starts. Never call it shown
  because the code looks right, because a test covers it, or because the difference looks small.
- Change nothing outside `$STAGE_OUT`, and fix nothing: the judge gets your report.
- A scenario written as a test command is not a demonstration. Report that criterion shown only if a run of the real
  surface shows it; otherwise report it not shown, saying a test is the only way it was written to be observed.
- End the step **blocked** only when the harness itself can't run: `.sail/lib/demo.sh` fails to start, or a tool it
  needs is missing. A change that runs and behaves wrong is a report.

Each `transcript.txt` and every screenshot under `$STAGE_OUT/demo*/` is attached to the pull request's ticket, for a
reader who wasn't here. Name each screenshot after what it shows (`search-escape-keeps-query`, not `shot-1`), and capture
one for each criterion a view shows.

## Submit

Submit each acceptance criterion you ran a scenario for, in the requirements' or the Demonstration section's words,
with whether it was shown and its evidence, and `skipped` null. Leave out a criterion only a test can observe:
validation runs the tests. Submit too the transcript: the commands that show the criteria, with the output lines that
matter, under 4000 characters.
