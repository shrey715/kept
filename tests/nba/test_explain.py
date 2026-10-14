"""The case page's full "why": every model input's push, either sign, largest first."""

from kept.nba.explain import drivers


def test_drivers_keep_both_signs_largest_first() -> None:
    out = drivers(
        {"max_dpd": -0.05, "answer_rate": 0.09, "kept_promise_ratio": 0.01},
        {"max_dpd": 71, "answer_rate": 0.4},
    )
    assert [(d.feature, d.pts) for d in out] == [
        ("answer_rate", 9.0),
        ("max_dpd", -5.0),
        ("kept_promise_ratio", 1.0),
    ]
    assert out[0].label == "Answer rate" and out[0].value == "40%" and out[2].value is None
