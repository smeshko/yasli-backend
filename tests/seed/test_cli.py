"""`python -m yasli.seed` — reporting and exit codes.

Exit codes follow the `yasli.ingest` convention the rest of the project
already uses: 2 config, 3 data, 4 fetch/precondition, 5 database. A failed
step must name itself on stderr; a seed that stops halfway without saying
where is the failure mode YAS-21 complains about.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from yasli.seed import runner
from yasli.seed.__main__ import main


def _steps(failing: str | None = None, exc: Exception | None = None) -> list[runner.Step]:
    def make(name: str) -> runner.Step:
        def _run(ctx: runner.SeedContext) -> str:
            if name == failing:
                raise exc or RuntimeError("boom")
            return "rows=1"

        return runner.Step(name=name, run=_run)

    return [make(n) for n in ("alpha", "beta")]


def _run(argv: list[str], steps: list[runner.Step], monkeypatch) -> tuple[int, str, str]:
    monkeypatch.setattr(runner, "build_steps", lambda **kwargs: steps)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_successful_seed_prints_one_line_per_step(monkeypatch) -> None:
    rc, out, _ = _run([], _steps(), monkeypatch)
    assert rc == 0
    assert "alpha" in out
    assert "beta" in out
    assert "rows=1" in out


def test_successful_seed_prints_elapsed_time_per_step(monkeypatch) -> None:
    _, out, _ = _run([], _steps(), monkeypatch)
    assert out.count("ms") >= 2


def test_a_failing_step_is_named_on_stderr(monkeypatch) -> None:
    rc, _, err = _run([], _steps(failing="alpha"), monkeypatch)
    assert rc != 0
    assert "alpha" in err


def test_later_steps_are_not_reported_after_a_failure(monkeypatch) -> None:
    _, out, _ = _run([], _steps(failing="alpha"), monkeypatch)
    assert "beta" not in out


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (ValueError("DATABASE_URL is not set"), 2),
        (RuntimeError("unknown"), 5),
    ],
)
def test_exit_codes_follow_the_ingest_convention(
    exception: Exception, expected: int, monkeypatch
) -> None:
    rc, _, _ = _run([], _steps(failing="alpha", exc=exception), monkeypatch)
    assert rc == expected
