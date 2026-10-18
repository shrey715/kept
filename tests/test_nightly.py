"""kept nightly runs every track's step in order, stops at the first failure and leaves a heartbeat file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from kept.cli import NIGHTLY, nightly

pytestmark = pytest.mark.track_d


def _run(fail: str | None = None):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def run(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if fail and argv == dict(NIGHTLY)[fail] else 0

    return calls, run


def test_runs_every_step_in_order(tmp_path: Path) -> None:
    calls, run = _run()
    assert nightly(argparse.Namespace(start=None, skip=[]), run=run, exports=tmp_path) == 0
    assert calls == [argv for _, argv in NIGHTLY]
    names = [n for n, _ in NIGHTLY]  # A's order, then text, features, parity, score
    assert names.index("gate") < names.index("features") < names.index("parity") < names.index("score")
    assert names.index("extract") < names.index("features")  # tonight's notes reach the features
    assert names[-1] == "invariance"  # tonight's cards, checked against scrambled protected attributes
    assert dict(NIGHTLY)["match"] == [
        "match",
        "--train-sample-mod",
        "5",
    ]  # full-data training runs out of RAM


def test_a_failing_gate_publishes_nothing(tmp_path: Path) -> None:
    calls, run = _run(fail="gate")
    assert nightly(argparse.Namespace(start=None, skip=[]), run=run, exports=tmp_path) == 1
    assert calls[-1] == ["gate"] and ["score"] not in calls
    beat = json.loads((tmp_path / "reports" / "nightly_run.json").read_text())
    assert beat["exit"] == 1 and beat["gate"] == "block" and beat["steps"][-1]["name"] == "gate"
    assert beat["parity"] is None and "score" in beat["planned"]  # the strip shows what never ran


def test_resume_and_skip(tmp_path: Path) -> None:
    calls, run = _run()
    assert nightly(argparse.Namespace(start="extract", skip=["extract"]), run=run, exports=tmp_path) == 0
    assert calls == [["features"], ["parity"], dict(NIGHTLY)["train-best-hour"], ["score"], ["invariance"]]
    assert nightly(argparse.Namespace(start="nope", skip=[]), run=run, exports=tmp_path) == 2


def test_heartbeat_records_each_step_and_the_badges(tmp_path: Path) -> None:
    def run(argv: list[str]) -> int:  # the steps write what they always write
        if argv == ["features"]:
            (tmp_path / "features").mkdir()
            (tmp_path / "features" / "drift_alarm.json").write_text('{"drifted": ["max_dpd"]}')
        if argv == ["parity"]:
            (tmp_path / "quality").mkdir()
            (tmp_path / "quality" / "parity_report.md").write_text(
                "Result: **PASS**: 3 of 56,000 cells differ (0.0054%; the limit is 0.1%)."
            )
        return 0

    assert nightly(argparse.Namespace(start=None, skip=["extract"]), run=run, exports=tmp_path) == 0
    beat = json.loads((tmp_path / "reports" / "nightly_run.json").read_text())
    names = [n for n, _ in NIGHTLY if n != "extract"]
    assert [s["name"] for s in beat["steps"]] == beat["planned"] == names
    assert all(s["exit"] == 0 and s["seconds"] >= 0 and s["start"] for s in beat["steps"])
    assert beat["exit"] == 0 and beat["finished"] >= beat["started"]
    assert beat["gate"] == "pass" and beat["drift_alarm"] == ["max_dpd"]
    assert beat["parity"] == {"passed": True, "mismatch_rate": pytest.approx(0.000054)}
    assert not list((tmp_path / "reports").glob("*.tmp"))
