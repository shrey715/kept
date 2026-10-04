"""kept.app.charts: the rules list honest options; the LLM only picks among them (#100)."""

from __future__ import annotations

from typing import Any

import pytest

from kept.app.charts import ChartRequest, chart_options, choose_chart
from kept.common.llm import Purpose
from tests.fakes import PassThroughRedactor, ScriptedLLM

BY_PRODUCT = (
    ["product", "kept_rate", "n"],
    [["card", "0.52", 900], ["loan", "0.47", 400], ["loc", "0.61", 120]],
)
BY_MONTH = (["month", "roll_rate"], [[f"2026-0{m}", f"0.{40 + m}"] for m in range(1, 7)])


def _req(columns: list[str], rows: list[list[Any]], q: str = "kept rate by product") -> ChartRequest:
    return ChartRequest(
        question=q, sql="select ...", columns=columns, rows=rows, user_id="an-1", role="analyst"
    )


def _kinds(columns: list[str], rows: list[list[Any]]) -> list[tuple[str, str | None, list[str], str | None]]:
    return [(o.kind, o.x, o.y, o.series) for o in chart_options(columns, rows)[0]]


def test_one_number_is_a_tile() -> None:
    assert _kinds(["average_dpd"], [["41.7"]])[0] == ("tile", None, ["average_dpd"], None)


def test_categories_give_bars_rate_before_count() -> None:
    opts = _kinds(*BY_PRODUCT)
    assert opts[0] == ("bar", "product", ["kept_rate"], None)  # string decimals parse; the rate leads
    assert ("bar", "product", ["n"], None) in opts
    assert opts[-1][0] == "table"


def test_time_gives_a_line() -> None:
    opts, prof = chart_options(*BY_MONTH)
    assert (opts[0].kind, opts[0].x, opts[0].y, opts[0].unit) == ("line", "month", ["roll_rate"], "fraction")
    assert prof[0].kind == "time"


def test_time_and_category_split_into_lines_not_one_jagged_line() -> None:
    rows = [[f"2026-0{m}", p, f"0.{30 + m}"] for m in range(1, 5) for p in ("card", "loan")]
    opts = _kinds(["month", "product", "roll_rate"], rows)
    assert ("line", "month", ["roll_rate"], "product") in opts
    assert ("line", "month", ["roll_rate"], None) not in opts  # two rows per month


def test_too_many_categories_or_free_text_is_table_only() -> None:
    assert _kinds(["agent", "calls"], [[f"AG-{i}", i] for i in range(40)]) == [("table", None, [], None)]
    assert _kinds(["note"], [["x" * 80]]) == [("table", None, [], None)]


def test_no_two_scales_on_one_chart() -> None:
    rows = [["card", "0.5", "1200.50"], ["loan", "0.4", "900.10"]]
    for kind, _, y, _ in _kinds(["product", "kept_rate", "collected_amount"], rows):
        assert len(y) <= 1 or kind == "tile"


def test_llm_picks_among_options_and_sees_the_data() -> None:
    llm = ScriptedLLM([{"option": "2", "why": "The question asks how many promises."}])
    got = choose_chart(
        _req(*BY_PRODUCT, q="how many promises by product"), llm=llm, redactor=PassThroughRedactor()
    )
    assert (got.source, got.option.y) == ("llm", ["n"])
    sent = llm.calls[0]
    assert sent["purpose"] == Purpose.ASK_CHART
    assert (
        "SQL:" in sent["user"].text
        and "kept_rate: number, fraction" in sent["user"].text
        and "card | 0.52" in sent["user"].text
    )


@pytest.mark.parametrize(
    "reply",
    [{"option": "99"}, {"why": "no option"}, RuntimeError("rate limited")],
    ids=["unknown", "missing", "error"],
)
def test_bad_llm_reply_falls_back_to_the_rules(reply: Any) -> None:
    got = choose_chart(_req(*BY_PRODUCT), llm=ScriptedLLM([reply]), redactor=PassThroughRedactor())
    assert (got.source, got.option.kind, got.option.y) == ("rules", "bar", ["kept_rate"])


def test_a_why_with_numbers_is_dropped() -> None:
    llm = ScriptedLLM([{"option": "1", "why": "Loc is highest at 61%."}])
    got = choose_chart(_req(*BY_PRODUCT), llm=llm, redactor=PassThroughRedactor())
    assert got.source == "llm" and got.why is None


def test_chart_route_without_llm_uses_rules() -> None:
    from fastapi.testclient import TestClient

    from kept.app.api import Services, create_app

    client = TestClient(create_app(Services(None, None, None, None, None)))  # type: ignore[arg-type]
    cols, rows = BY_MONTH
    r = client.post(
        "/chart",
        json={
            "question": "roll rate by month",
            "columns": cols,
            "rows": rows,
            "user_id": "an-1",
            "role": "analyst",
        },
    )
    assert r.status_code == 200 and r.json()["option"]["kind"] == "line" and r.json()["source"] == "rules"
