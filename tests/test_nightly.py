"""kept nightly runs every track's step in order and stops at the first failure."""

from __future__ import annotations

import argparse

import pytest

from kept.cli import NIGHTLY, nightly

pytestmark = pytest.mark.track_d


def _run(fail: str | None = None):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def run(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if fail and argv == dict(NIGHTLY)[fail] else 0

    return calls, run


def test_runs_every_step_in_order() -> None:
    calls, run = _run()
    assert nightly(argparse.Namespace(start=None, skip=[]), run=run) == 0
    assert calls == [argv for _, argv in NIGHTLY]
    names = [n for n, _ in NIGHTLY]  # A's order, then text, features, parity, score
    assert names.index("gate") < names.index("features") < names.index("parity") < names.index("score")
    assert names.index("extract") < names.index("features")  # tonight's notes reach the features
    assert dict(NIGHTLY)["match"] == [
        "match",
        "--train-sample-mod",
        "5",
    ]  # full-data training runs out of RAM


def test_a_failing_gate_publishes_nothing() -> None:
    calls, run = _run(fail="gate")
    assert nightly(argparse.Namespace(start=None, skip=[]), run=run) == 1
    assert calls[-1] == ["gate"] and ["score"] not in calls


def test_resume_and_skip() -> None:
    calls, run = _run()
    assert nightly(argparse.Namespace(start="extract", skip=["extract"]), run=run) == 0
    assert calls == [["features"], ["parity"], ["score"]]
    assert nightly(argparse.Namespace(start="nope", skip=[]), run=run) == 2
