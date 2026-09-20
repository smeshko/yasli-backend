"""Ordering and failure semantics of the seed runner.

The order is load-bearing and non-obvious: ГРАО must precede ingest,
because `pipeline.run()` ends with the *gated* stamping passes, which can
only stamp what `grao_addresses` already holds. Getting it wrong produces
a seed that exits 0 with no districts — precisely the failure YAS-21 was
filed about. So the order is asserted here, not just written down.
"""

from __future__ import annotations

import pytest

from yasli.seed import runner


def _stub_steps(calls: list[str], failing: str | None = None) -> list[runner.Step]:
    def make(name: str) -> runner.Step:
        def _run(ctx: runner.SeedContext) -> str:
            calls.append(name)
            if name == failing:
                raise RuntimeError(f"{name} blew up")
            return f"{name}=ok"

        return runner.Step(name=name, run=_run)

    return [make(n) for n in ("first", "second", "third")]


def test_build_steps_is_the_documented_order() -> None:
    names = [step.name for step in runner.build_steps()]
    assert names == [
        "migrate",
        "grao",
        "ingest",
        "legacy-institutions",
        "institution-locations",
        "restamp-districts",
    ]


def test_grao_precedes_ingest() -> None:
    """The one ordering rule that silently breaks district routing."""
    names = [step.name for step in runner.build_steps()]
    assert names.index("grao") < names.index("ingest")


def test_restamp_is_last() -> None:
    assert runner.build_steps()[-1].name == "restamp-districts"


def test_run_seed_executes_every_step_in_order() -> None:
    calls: list[str] = []
    summary = runner.run_seed(steps=_stub_steps(calls))
    assert calls == ["first", "second", "third"]
    assert [s.name for s in summary.steps] == ["first", "second", "third"]
    assert [s.detail for s in summary.steps] == [
        "first=ok",
        "second=ok",
        "third=ok",
    ]


def test_run_seed_times_each_step() -> None:
    summary = runner.run_seed(steps=_stub_steps([]))
    assert all(s.elapsed_ms >= 0 for s in summary.steps)
    assert summary.elapsed_ms >= 0


def test_a_failing_step_aborts_and_later_steps_do_not_run() -> None:
    calls: list[str] = []
    with pytest.raises(runner.SeedStepFailed) as exc:
        runner.run_seed(steps=_stub_steps(calls, failing="second"))
    assert calls == ["first", "second"]
    assert exc.value.step == "second"
    assert "blew up" in str(exc.value)


def test_a_failing_step_names_the_step_and_carries_an_exit_code() -> None:
    calls: list[str] = []
    with pytest.raises(runner.SeedStepFailed) as exc:
        runner.run_seed(steps=_stub_steps(calls, failing="first"))
    assert exc.value.step == "first"
    assert exc.value.exit_code == 5  # unmapped exception → database/unknown


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (ValueError("bad config"), 2),
        (Exception("unknown"), 5),
    ],
)
def test_exit_code_mapping_is_applied(exception: Exception, expected: int) -> None:
    def _boom(ctx: runner.SeedContext) -> str:
        raise exception

    with pytest.raises(runner.SeedStepFailed) as exc:
        runner.run_seed(steps=[runner.Step(name="boom", run=_boom)])
    assert exc.value.exit_code == expected
