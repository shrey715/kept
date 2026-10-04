"""#86: the night-over-night drift alarm, and the engine sending Green cards to a person while it stands."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from kept.features.drift import ALARM_FILE, load_alarm, night_over_night

pytestmark = pytest.mark.track_d


def _night(seed: int, shift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "as_of": pd.Timestamp("2026-10-03"),
            "max_dpd": rng.integers(0, 90, 5_000) + shift,
            "answer_rate": rng.uniform(0, 1, 5_000),
        }
    )


def test_alarm_only_on_a_real_shift(tmp_path) -> None:  # type: ignore[no-untyped-def]
    quiet = night_over_night(_night(1), _night(2), ["max_dpd", "answer_rate"])
    assert quiet["drifted"] == []
    broken = night_over_night(_night(1), _night(2, shift=60), ["max_dpd", "answer_rate"])
    assert broken["drifted"] == ["max_dpd"]
    assert load_alarm(tmp_path) == []  # no file: no alarm
    (tmp_path / ALARM_FILE).write_text(json.dumps(broken))
    assert load_alarm(tmp_path) == ["max_dpd"]


def test_calendar_features_never_alarm() -> None:
    a, b = _night(1), _night(2)
    a["days_to_next_payroll"], b["days_to_next_payroll"] = 5, 4  # one night later, by design
    assert night_over_night(a, b, ["max_dpd", "days_to_next_payroll"])["drifted"] == []
