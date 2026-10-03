"""The SQL hardship combine (gold) gives the same answer as Track C's Python `combine`."""

from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kept.contracts.enums import HardshipSignal, HardshipSource, HardshipStatus
from kept.data.hardship_sql import register
from kept.hardship.combine import HardshipObservation, combine

T0 = datetime(2026, 9, 1)

observation = st.builds(
    HardshipObservation,
    source=st.sampled_from(list(HardshipSource)),
    signal=st.sampled_from(list(HardshipSignal)),
    observed_at=st.integers(0, 6).map(lambda d: T0 + timedelta(days=d)),  # few days: ties happen
    confirmed_by=st.one_of(st.none(), st.just("AG-1")),
    cleared_by=st.one_of(st.none(), st.none(), st.just("SPEC-1")),
)


def _sql_combine(per_customer: dict[str, list[HardshipObservation]]) -> dict[str, tuple[str, str]]:
    conn = duckdb.connect()
    register(conn)
    conn.execute(
        "create table obs (golden_customer_id varchar, source varchar, signal varchar, observed_at timestamp, "
        "confirmed_by varchar, cleared_by varchar)"
    )
    rows = [
        (g, o.source.value, o.signal.value, o.observed_at, o.confirmed_by, o.cleared_by)
        for g, observations in per_customer.items()
        for o in observations
    ]
    if rows:
        conn.executemany("insert into obs values (?, ?, ?, ?, ?, ?)", rows)
    return {
        g: (s, src) for g, s, src in conn.execute("select * from kept_combine_hardship('obs')").fetchall()
    }


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.lists(observation, min_size=0, max_size=6), min_size=1, max_size=4))
def test_sql_combine_equals_python_combine(customers: list[list[HardshipObservation]]) -> None:
    per_customer = {f"G-{i}": obs for i, obs in enumerate(customers)}
    got = _sql_combine(per_customer)
    for golden, observations in per_customer.items():
        status, source = combine(observations)
        if status is HardshipStatus.NONE:
            assert golden not in got  # the SQL lists only customers with a hardship status
        else:
            assert got[golden] == (status.value, source.value if source else None), observations


def test_the_documented_rules_in_sql() -> None:
    def obs(source: HardshipSource, signal: HardshipSignal, day: int, **kw: str) -> HardshipObservation:
        return HardshipObservation(source, signal, T0 + timedelta(days=day), **kw)

    got = _sql_combine(
        {
            "llm-only": [obs(HardshipSource.LLM, HardshipSignal.CLEAR, 1)],  # stays possible
            "agent": [obs(HardshipSource.AGENT, HardshipSignal.CLEAR, 1)],  # confirmed
            "llm-confirmed": [obs(HardshipSource.LLM, HardshipSignal.POSSIBLE, 1, confirmed_by="AG-1")],
            "cleared": [
                obs(HardshipSource.AGENT, HardshipSignal.CLEAR, 1),
                obs(HardshipSource.AGENT, HardshipSignal.NONE, 2, cleared_by="SPEC-1"),
                obs(HardshipSource.MODEL, HardshipSignal.POSSIBLE, 3),  # after the clearing: counts again
            ],
        }
    )
    assert got == {
        "llm-only": ("possible", "llm"),
        "agent": ("confirmed", "agent"),
        "llm-confirmed": ("confirmed", "llm"),
        "cleared": ("possible", "model"),
    }
