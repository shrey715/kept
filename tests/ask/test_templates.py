from datetime import date

import pytest

from kept.ask.templates import EXAMPLES, TEMPLATES, date_hints, examples, resolve_dates

D = date(2026, 9, 28)


@pytest.mark.parametrize(
    ("question", "want"),
    [
        ("calls in September 2026", [("2026-09-01", "2026-09-30")]),
        ("promises due in July-September 2026", [("2026-07-01", "2026-09-30")]),
        (
            "disputes between 15 and 22 September 2026, compared with the 8 days before",
            [("2026-09-15", "2026-09-22"), ("2026-09-07", "2026-09-14")],
        ),
        ("charged off in the 12 months to 28 September 2026", [("2025-09-29", "2026-09-28")]),
        ("1-30 DPD at the end of March 2026", [("2026-03-31", "2026-03-31")]),
        ("volume on 23-24 September 2026", [("2026-09-23", "2026-09-24")]),
        ("customers who broke a promise last month", [("2026-08-01", "2026-08-31")]),
        ("open cases today, by bucket", []),  # "today" is the as-of date the router has, not a range
    ],
)
def test_resolve_dates(question: str, want: list[tuple[str, str]]) -> None:
    assert [(s.isoformat(), e.isoformat()) for _, s, e in resolve_dates(question, D)] == want


def test_date_hints_text() -> None:
    assert "2025-09-29 to 2026-09-28" in date_hints("the 12 months to 28 September 2026", D)
    assert "2026-03-31 (one day)" in date_hints("at the end of March 2026", D)
    assert date_hints("how many open cases", D) == ""


@pytest.mark.parametrize("metric_id", sorted(TEMPLATES))
def test_templates_compile_and_pass_the_guard(metric_id: str) -> None:
    pytest.importorskip("sqlglot")
    from kept.ask.metrics import compile_metric
    from kept.contracts.ask import Intent, IntentKind

    d, q = TEMPLATES[metric_id]
    intent = Intent(
        kind=IntentKind.METRIC,
        metric_id=metric_id,
        confidence=0.9,
        group_by=sorted(q.allowed_group_by)[:1],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 6, 30),
    )
    sql, params = compile_metric(intent, {metric_id: d}, {metric_id: q})
    import sqlglot

    assert sqlglot.parse_one(sql, dialect="duckdb") is not None
    assert params == [date(2026, 1, 1), date(2026, 6, 30)]


def test_examples_pick_the_closest() -> None:
    text = examples("How much was paid against promises due in September 2026?", k=1)
    assert "amount_paid_against" in text and text.count("Q: ") == 1
    assert len(EXAMPLES) >= 5
