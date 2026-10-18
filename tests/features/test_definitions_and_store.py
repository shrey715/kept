"""Reference feature semantics (point in time, missing stays missing) and the deny-list."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from kept.contracts.feature_registry import OUTCOME_DENY_LIST, STATED_REASON_FIELDS
from kept.features.definitions import (
    answer_rate,
    bank_context,
    broken_promises_90d,
    cohort_rate,
    contacts_last_7d,
    days_to_next_payroll,
    kept_promise_ratio,
)
from kept.features.store import assert_no_denied, drop_denied

AS_OF = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)  # 06:00 Toronto


def _promises(rows: list[tuple[int, str, int]]) -> pd.DataFrame:
    """(due_days_from_as_of, ptp_status, status_days_from_as_of) -> promises_to_pay columns"""
    return pd.DataFrame(
        [
            {
                "ptp_due_date": (AS_OF + timedelta(days=d)).date(),
                "ptp_status": s,
                "status_ts": AS_OF + timedelta(days=r),
            }
            for d, s, r in rows
        ]
    )


# ----------------------------------------------------------------- promises
def test_broken_promises_90d_window_and_point_in_time() -> None:
    df = _promises(
        [
            (-10, "broken", -9),  # counts
            (-89, "broken", -88),  # counts (inside 90d)
            (-90, "broken", -89),  # boundary: (as_of - 90d, as_of] excludes exactly 90 days ago
            (-120, "broken", -119),  # too old
            (-5, "kept", -4),  # not broken
            (-3, "broken", +1),  # recorded AFTER as_of: future leak, must not count
        ]
    )
    assert broken_promises_90d(df, as_of=AS_OF) == 2


def test_kept_ratio_ignores_open_and_future() -> None:
    df = _promises(
        [
            (-10, "kept", -9),
            (-20, "broken", -19),
            (-30, "kept", -29),
            (5, "open", -1),
            (-2, "cancelled", -1),
            (-1, "broken", 2),
        ]
    )
    assert kept_promise_ratio(df, as_of=AS_OF) == pytest.approx(2 / 3)


def test_partially_kept_is_not_kept() -> None:
    df = _promises([(-10, "kept", -9), (-20, "partially_kept", -19)])
    assert kept_promise_ratio(df, as_of=AS_OF) == pytest.approx(0.5)
    assert broken_promises_90d(df, as_of=AS_OF) == 0  # only ptp_status == broken counts as broken


def test_kept_ratio_none_without_resolved_promises() -> None:
    assert kept_promise_ratio(_promises([(5, "open", -1)]), as_of=AS_OF) is None
    assert (
        kept_promise_ratio(
            _promises([]).reindex(columns=["ptp_due_date", "ptp_status", "status_ts"]), as_of=AS_OF
        )
        is None
    )


# ----------------------------------------------------------------- payroll
@pytest.mark.parametrize(
    "payday,expected", [(date(2026, 10, 2), 4), (date(2026, 9, 28), 0), (date(2026, 9, 27), -1), (None, None)]
)
def test_days_to_next_payroll(payday: date | None, expected: int | None) -> None:
    assert days_to_next_payroll(payday, as_of=AS_OF, tz="America/Toronto") == expected


def test_days_to_payroll_uses_local_date() -> None:
    late = datetime(
        2026, 9, 29, 5, 0, tzinfo=UTC
    )  # 22:00 PDT 28 Sep in Vancouver; 01:00 EDT 29 Sep in Toronto
    assert days_to_next_payroll(date(2026, 10, 2), as_of=late, tz="America/Vancouver") == 4
    assert days_to_next_payroll(date(2026, 10, 2), as_of=late, tz="America/Toronto") == 3


# ----------------------------------------------------------------- contacts
def _contacts(rows: list[tuple[float, str, bool]]) -> pd.DataFrame:
    """(days_from_as_of, channel, answered) -> contact_history columns"""
    return pd.DataFrame(
        [
            {
                "contact_ts_utc": AS_OF + timedelta(days=d),
                "channel": c,
                "dial_result": "answered" if a else "no_answer",
            }
            for d, c, a in rows
        ]
    )


def test_contacts_last_7d_window() -> None:
    df = _contacts(
        [
            (-1, "call", True),
            (-6.9, "sms", False),
            (-7, "call", False),
            (-8, "call", True),
            (0.1, "call", True),
        ]
    )
    assert contacts_last_7d(df, as_of=AS_OF) == 2


def test_answer_rate_calls_only_and_point_in_time() -> None:
    df = _contacts([(-1, "call", True), (-2, "call", False), (-3, "sms", True), (1, "call", True)])
    assert answer_rate(df, as_of=AS_OF) == pytest.approx(0.5)
    assert answer_rate(_contacts([(-1, "sms", True)]), as_of=AS_OF) is None


def test_answer_rate_after_18h_local() -> None:
    # 22:30 UTC = 18:30 Toronto (answered); 20:00 UTC = 16:00 Toronto (not answered)
    df = pd.DataFrame(
        [
            {
                "contact_ts_utc": datetime(2026, 9, 25, 22, 30, tzinfo=UTC),
                "channel": "call",
                "dial_result": "answered",
            },
            {
                "contact_ts_utc": datetime(2026, 9, 25, 20, 0, tzinfo=UTC),
                "channel": "call",
                "dial_result": "busy",
            },
        ]
    )
    assert answer_rate(df, as_of=AS_OF, after_local_hour=18, tz="America/Toronto") == 1.0


# ----------------------------------------------------------------- cohorts
def test_cohort_rate_groups_of_fifty_plus() -> None:
    assert cohort_rate(32, 50) == pytest.approx(0.64)
    assert cohort_rate(30, 49) is None
    with pytest.raises(ValueError):
        cohort_rate(51, 50)


# ----------------------------------------------------------------- deny-list
def test_drop_denied_removes_outcomes_without_mutating() -> None:
    df = pd.DataFrame(
        {
            "case_id": ["C-1"],
            "max_dpd": [3],
            "paid_14d": [1],
            "test_cell": ["challenger_B"],
            "dpd_at_day_30": [45],
            "hardship_reason": ["reduced_income"],
        }
    )
    before = df.copy()
    out = drop_denied(df)
    assert list(out.columns) == ["case_id", "max_dpd"]
    pd.testing.assert_frame_equal(df, before)


@pytest.mark.parametrize("col", sorted(OUTCOME_DENY_LIST | STATED_REASON_FIELDS))
def test_assert_no_denied_names_the_column(col: str) -> None:
    with pytest.raises(ValueError, match=col):
        assert_no_denied(pd.DataFrame({"max_dpd": [1], col: [0]}))


def test_assert_no_denied_passes_clean_frame() -> None:
    assert_no_denied(pd.DataFrame({"case_id": ["C-1"], "max_dpd": [1]}))


# ----------------------------------------------------------------- the bank's context at as_of
def _out(rows: list[tuple[float, bool, bool]]) -> pd.DataFrame:
    """(days before as_of, rpc, ptp made) -> the case's outbound contacts"""
    return pd.DataFrame(
        [{"contact_ts_utc": AS_OF - timedelta(days=d), "rpc_flag": r, "ptp_made_flag": m} for d, r, m in rows],
        columns=["contact_ts_utc", "rpc_flag", "ptp_made_flag"],
    )


_NO_CONTACTS = pd.DataFrame(
    columns=["contact_ts_utc", "payment_taken_flag", "link_payment_flag", "app_payment_after_contact_flag"]
)
_NO_PROMISES = pd.DataFrame(
    columns=["ptp_created_ts", "ptp_due_date", "ptp_status", "status_ts", "paid_date"]
)


def test_context_with_nothing_known() -> None:
    c = bank_context(_out([]), _NO_CONTACTS, _NO_PROMISES, as_of=AS_OF)
    assert c["pending_ptp"] is False and c["paid_prev7"] is False
    assert (c["n_out_7d"], c["n_out_30d"], c["n_rpc_30d"]) == (0, 0, 0)
    assert c["days_since_contact"] is None and c["last_rpc"] is None and c["ptp_due_in_days"] is None
    assert c["weekday"] == 1  # Monday 28 Sep 2026; duckdb counts Sunday as 0


def test_context_contacts_window_and_last_outcome() -> None:
    out = _out([(1, True, True), (3, False, False), (10, True, False), (29.5, True, False), (31, True, True)])
    c = bank_context(out, _NO_CONTACTS, _NO_PROMISES, as_of=AS_OF)
    assert (c["n_out_7d"], c["n_out_30d"], c["n_rpc_30d"]) == (2, 4, 3)  # the 31-day-old contact is outside
    assert c["days_since_contact"] == pytest.approx(1.0)
    assert (c["last_rpc"], c["last_ptp_made"]) == (True, True)
    later = pd.concat([out, _out([(-1, True, True)])])  # a contact a day after as_of never counts
    assert bank_context(later, _NO_CONTACTS, _NO_PROMISES, as_of=AS_OF)["n_out_30d"] == 4


def test_context_open_promise_and_recent_payment() -> None:
    created = AS_OF - timedelta(days=5)
    promises = pd.DataFrame(
        [
            {"ptp_created_ts": created, "ptp_due_date": (AS_OF + timedelta(days=4)).date(), "ptp_status": "open",
             "status_ts": pd.NaT, "paid_date": None},
            {"ptp_created_ts": created, "ptp_due_date": (AS_OF + timedelta(days=9)).date(), "ptp_status": "broken",
             "status_ts": AS_OF + timedelta(days=1), "paid_date": None},  # resolved after as_of: still open at as_of
            {"ptp_created_ts": created, "ptp_due_date": (AS_OF - timedelta(days=1)).date(), "ptp_status": "kept",
             "status_ts": AS_OF - timedelta(days=2), "paid_date": (AS_OF - timedelta(days=2)).date()},
        ]
    )  # fmt: skip
    c = bank_context(_out([]), _NO_CONTACTS, promises, as_of=AS_OF)
    assert c["pending_ptp"] is True and c["ptp_due_in_days"] == 4
    assert c["paid_prev7"] is True  # the kept promise was paid two days ago
    paid = pd.DataFrame([{"contact_ts_utc": AS_OF - timedelta(days=3), "payment_taken_flag": None,
                          "link_payment_flag": True, "app_payment_after_contact_flag": None}])  # fmt: skip
    assert bank_context(_out([]), paid, _NO_PROMISES, as_of=AS_OF)["paid_prev7"] is True
    old = paid.assign(contact_ts_utc=AS_OF - timedelta(days=8))
    assert bank_context(_out([]), old, _NO_PROMISES, as_of=AS_OF)["paid_prev7"] is False


def test_context_day_is_the_decisions_own_when_as_of_is_a_second_before_midnight() -> None:
    as_of = datetime(2026, 9, 28, 23, 59, 59, tzinfo=UTC)  # a decision at midnight: Tuesday 29 Sep
    promises = pd.DataFrame(
        [{"ptp_created_ts": as_of - timedelta(days=2), "ptp_due_date": date(2026, 10, 1), "ptp_status": "open",
          "status_ts": pd.NaT, "paid_date": None}]
    )  # fmt: skip
    c = bank_context(_out([]), _NO_CONTACTS, promises, as_of=as_of)
    assert c["weekday"] == 2 and c["ptp_due_in_days"] == 2
