"""dbt feature models agree with the Python reference definitions (the oracle), point in time.

Needs dbt: `uv run --with "dbt-core>=1.10" --with "dbt-duckdb>=1.9" pytest tests/features/test_dbt_features.py`
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from kept.contracts.feature_registry import FEATURES
from kept.features.definitions import (
    answer_rate,
    bank_context,
    broken_promises_90d,
    cohort_rate,
    contacts_last_7d,
    days_to_next_payroll,
    kept_promise_ratio,
)
from kept.nba.train import CONTEXT_COLS

pytestmark = [pytest.mark.integration, pytest.mark.track_d]

DBT = Path(__file__).resolve().parents[2] / "dbt"
AS_OFS = [datetime(2026, 9, 14, 6), datetime(2026, 9, 21, 6), datetime(2026, 9, 28, 6)]  # naive UTC
TZ = "America/Toronto"
PRODUCTS = ["card", "personal_loan"]


def _fixture(seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = random.Random(seed)
    start = datetime(2026, 5, 1)

    def ts() -> datetime:
        return start + timedelta(minutes=rng.randrange(0, 150 * 24 * 60))

    cases, promises, contacts = [], [], []
    for i in range(600):  # open around the as_of dates, or closed earlier (cohort history)
        opened = ts().date()
        closed = opened + timedelta(days=rng.randrange(5, 90)) if rng.random() < 0.6 else None
        cases.append(
            {
                "case_id": f"CS-{i}",
                "coll_customer_ref": f"CRM-{i % 60}",
                "case_open_date": opened,
                "outcome_date": closed,
                "primary_product": rng.choice(PRODUCTS),
                "entry_dpd": rng.choice([1, 5, 20, 40]),
                "cure_flag": closed is not None and rng.random() < 0.7,
                "total_overdue": round(rng.uniform(50, 5000), 2),
            }
        )
    for i in range(900):
        due = ts()
        promises.append(
            {
                "ptp_id": f"P-{i}",
                "case_id": f"CS-{rng.randrange(600)}",
                "crm_customer_id": f"CRM-{rng.randrange(60)}",
                "ptp_due_date": due.date(),
                "ptp_created_ts": due - timedelta(days=rng.randrange(1, 20), hours=rng.randrange(24)),
                "status_ts": due + timedelta(days=rng.randrange(-5, 6)),
                "ptp_status": (status := rng.choice(["open", "kept", "partially_kept", "broken", "cancelled"])),
                "paid_date": (due + timedelta(days=rng.randrange(-3, 4))).date()
                if status in ("kept", "partially_kept")
                else None,
            }
        )
    for _ in range(3000):
        t = ts()
        channel = rng.choice(["call", "call", "sms", "email"])
        contacts.append(
            {
                "case_id": f"CS-{rng.randrange(600)}",
                "crm_customer_id": f"CRM-{rng.randrange(60)}",
                "contact_ts_utc": t,
                "channel": channel,
                "direction": rng.choice(["outbound", "outbound", "outbound", "inbound"]),
                "dial_result": rng.choice(["answered", "no_answer", "voicemail"])
                if channel == "call"
                else None,
                "contact_hour_local": pd.Timestamp(t, tz="UTC").tz_convert(TZ).hour,
                "payment_link_id": f"PL-{t:%s}" if channel == "sms" else None,
                "link_payment_flag": rng.random() < 0.3 if channel == "sms" else None,
                "rpc_flag": rng.random() < 0.4 if channel == "call" else False,
                "ptp_made_flag": rng.random() < 0.15 if channel == "call" else False,
                "payment_taken_flag": rng.random() < 0.05 if channel == "call" else False,
                "app_payment_after_contact_flag": rng.random() < 0.05 if channel in ("sms", "email") else False,
            }
        )
    notes = []
    for i in range(1500):  # C's text_signals: one row per note
        t = ts()
        notes.append(
            {
                "source_id": f"N-{i}",
                "case_id": f"CS-{rng.randrange(600)}",
                "written_at": t,
                "hardship_signal": rng.choice(["none", "none", "possible", "clear"]),
                "promise_intent": rng.random() < 0.3,
                "promised_date": (t + timedelta(days=rng.randrange(1, 20))).date(),
                "promised_amount": round(rng.uniform(20, 500), 2),
                "dispute_flag": rng.random() < 0.1,
                "cease_request_flag": rng.random() < 0.05,
                "third_party_present_flag": rng.random() < 0.2,
            }
        )
    cards, loans, deposits, customers, golden, salary = [], [], [], [], [], []
    freqs = ["weekly", "biweekly", "semi_monthly", "monthly", None]
    for i in range(60):  # one golden customer per CRM id: a card, a loan for half, payroll for most
        snap = date(2026, 9, 28) if i % 10 else date(2026, 3, 31)  # some accounts closed earlier
        cards.append(
            {
                "card_account_id": f"C-{i}",
                "src_customer_ref": f"CK-{i}",
                "snapshot_date": snap,
                "dpd": rng.choice([0, 0, 12, 35, 70]),
                "utilisation": round(rng.uniform(0, 1.2), 4),
                **{f"dpd_m{k:02d}": rng.choice([0, 0, 5, 31, 64]) for k in range(1, 13)},
                **{f"utilisation_m{k:02d}": round(rng.uniform(0, 1.2), 4) for k in range(1, 13)},
            }
        )
        if i % 2:
            loans.append(
                {
                    "loan_id": f"L-{i}",
                    "src_customer_ref": f"LK-{i}",
                    "snapshot_date": snap,
                    "dpd": rng.choice([0, 3, 45]),
                    **{f"dpd_m{k:02d}": rng.choice([0, 0, 30, 61]) for k in range(1, 13)},
                }
            )
        freq = freqs[i % 5]
        deposits.append(
            {
                "deposit_account_id": f"D-{i}",
                "src_customer_ref": f"DK-{i}",
                "snapshot_date": snap,
                "last_payroll_date": date(2026, 9, 20) if freq else None,
                "expected_next_payroll_date": date(2026, 9, rng.randrange(20, 30)) if freq else None,
                "payroll_frequency_detected": freq,
                "payroll_delay_days": rng.choice([0, 0, 4]) if freq else None,
                "payroll_avg_amount_3m": round(rng.uniform(800, 3000), 2) if freq else None,
                "payroll_amount_change_pct": round(rng.uniform(-0.3, 0.1), 4) if freq else None,
                "essential_spend_amount_mtd": round(rng.uniform(200, 900), 2),
                "other_lender_payment_amount_mtd": round(rng.uniform(0, 300), 2),
                **{f"net_cash_flow_m{k:02d}": round(rng.uniform(-900, 600), 2) for k in range(1, 13)},
            }
        )
        if (
            freq
        ):  # monthly employer pay Feb-Aug, September for half (a month still running at the as_of dates)
            per = {"weekly": 4, "biweekly": 2, "semi_monthly": 2, "monthly": 1}[freq]
            base = rng.uniform(800, 3000)
            for m in range(2, 10 if i % 2 else 9):
                count = 0 if rng.random() < 0.1 else per
                first = date(2026, m, rng.randrange(1, 8))
                salary.append(
                    {
                        "deposit_account_id": f"D-{i}",
                        "crm_customer_id": f"CRM-{i}",
                        "credit_month": f"2026-{m:02d}",
                        "employer_flag": "N" if rng.random() < 0.05 else "Y",
                        "credit_count": count,
                        "credit_amount_total": round(count * base * rng.choice([1, 1, 0.7]), 2),
                        "first_credit_date": first if count else None,
                        "last_credit_date": first + timedelta(days=(per - 1) * 7) if count else None,
                    }
                )
        customers.append(
            {"crm_customer_id": f"CRM-{i}", "monthly_housing_cost": rng.choice([None, 900.0, 1500.0])}
        )
        golden.append(
            {
                "golden_customer_id": f"G-{i}",
                "time_zone": rng.choice(["America/Toronto", "America/Vancouver", None]),
            }
        )
    return {
        "card_accounts": pd.DataFrame(cards),
        "loan_accounts": pd.DataFrame(loans),
        "deposit_accounts": pd.DataFrame(deposits),
        "salary_credit_history": pd.DataFrame(salary),
        "customers": pd.DataFrame(customers),
        "c360_customer": pd.DataFrame(golden),
        "collections_cases": pd.DataFrame(cases),
        "promises_to_pay": pd.DataFrame(promises),
        "contact_history": pd.DataFrame(contacts),
        "text_signals": pd.DataFrame(notes),
    }


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    pytest.importorskip("dbt.adapters.duckdb")
    from dbt.cli.main import dbtRunner

    tmp = tmp_path_factory.mktemp("dbt")
    db = tmp / "kept.duckdb"
    silver = _fixture()
    with duckdb.connect(str(db)) as c:
        for schema in ("silver", "text", "gold"):
            c.execute(f"create schema {schema}")
        for name, df in silver.items():
            c.register("df", df)
            # C's model lives in text; A's gold model stands in with the one column features read
            schema = {"text_signals": "text", "c360_customer": "gold"}.get(name, "silver")
            c.execute(f"create table {schema}.{name} as select * from df")
            c.unregister("df")
        # A's real crosswalk needs the match step's output; the features only join these columns
        c.execute("""create table gold.identity_crosswalk as
                     select 'G-' || i as golden_customer_id, s.system as source_system,
                            s.prefix || i as source_key, null::timestamptz as valid_to
                     from range(60) t(i), (values ('collections', 'CRM-'), ('crm', 'CRM-'), ('card', 'CK-'),
                                                  ('loan', 'LK-'), ('deposit', 'DK-')) s(system, prefix)""")

    import os

    os.environ["KEPT_WAREHOUSE_PATH"] = str(db)
    vars_ = {"features_start": str(AS_OFS[0]), "features_as_of": str(AS_OFS[-1])}
    res = dbtRunner().invoke(
        [
            "build",
            "--select",  # the feature models over the fixture silver, not A's silver models
            "path:models/features",
            "--exclude",  # needs the payment tables; checked on real silver
            "training_rows",
            "--project-dir",
            str(DBT),
            "--profiles-dir",
            str(DBT),
            "--target-path",
            str(tmp / "target"),
            "--log-path",
            str(tmp / "logs"),
            "--vars",
            json.dumps(vars_),
            "--quiet",
        ]
    )
    assert res.success, res.exception
    with duckdb.connect(str(db)) as c:  # dbt keeps its in-process connection open
        out = c.sql("select * from features.case_features").df()
        out = out.assign(golden_customer_id=out.golden_customer_id)
    return out, silver


def _aware(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.assign(**{col: pd.to_datetime(df[col]).dt.tz_localize("UTC")})


def test_columns_match_the_registry(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    out, _ = built
    meta = ["case_id", "golden_customer_id", "as_of", "feature_set_version"]
    assert list(out.columns) == meta + [f.name for f in FEATURES]


def test_spine_is_open_cases_at_each_as_of(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    out, silver = built
    cases = silver["collections_cases"]
    for as_of in AS_OFS:
        d = as_of.date()
        open_ = cases[(cases.case_open_date <= d) & (cases.outcome_date.isna() | (cases.outcome_date > d))]
        got = set(out[out.as_of == pd.Timestamp(as_of)].case_id)
        assert got == set(open_.case_id) and got


def test_sql_matches_python_reference(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    out, silver = built
    cases = silver["collections_cases"].set_index("case_id")
    promises = _aware(silver["promises_to_pay"], "status_ts")
    attempts = _aware(silver["contact_history"], "contact_ts_utc")
    attempts = attempts[attempts.direction == "outbound"]

    checked = 0
    for row in out.itertuples():
        as_of = pd.Timestamp(row.as_of).tz_localize("UTC").to_pydatetime()
        crm = cases.loc[row.case_id, "coll_customer_ref"]
        p = promises[promises.crm_customer_id == crm]
        h = attempts[attempts.crm_customer_id == crm]
        assert row.broken_promises_90d == broken_promises_90d(p, as_of=as_of)
        assert _same(row.kept_promise_ratio, kept_promise_ratio(p, as_of=as_of))
        assert _same(row.answer_rate, answer_rate(h, as_of=as_of))
        assert _same(row.answer_rate_after_18h, answer_rate(h, as_of=as_of, after_local_hour=18, tz=TZ))
        assert row.contacts_last_7d == contacts_last_7d(
            attempts[attempts.case_id == row.case_id], as_of=as_of
        )
        checked += 1
    assert checked > 50


def test_context_matches_python_reference(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    """The ten context inputs agree with `bank_context`, the oracle, for every (case, as_of)."""
    out, silver = built
    cases = silver["collections_cases"].set_index("case_id")
    contacts = _aware(silver["contact_history"], "contact_ts_utc")
    promises = _aware(silver["promises_to_pay"], "ptp_created_ts")
    promises = promises.assign(status_ts=pd.to_datetime(promises.status_ts, utc=True))
    checked = 0
    for row in out.itertuples():
        as_of = pd.Timestamp(row.as_of).tz_localize("UTC").to_pydatetime()
        crm = cases.loc[row.case_id, "coll_customer_ref"]
        mine = contacts[contacts.crm_customer_id == crm]
        want = bank_context(
            contacts[(contacts.case_id == row.case_id) & (contacts.direction == "outbound")],
            mine,
            promises[promises.crm_customer_id == crm],
            as_of=as_of,
        )
        for n in CONTEXT_COLS:
            got = getattr(row, n)
            got = None if pd.isna(got) else got
            ok = _same(got, want[n]) if want[n] is None or isinstance(want[n], float) else got == want[n]
            assert ok, (row.case_id, as_of, n, got, want[n])
        checked += 1
    assert checked > 50


def test_cohorts_match_python_reference(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    out, silver = built
    cases = silver["collections_cases"].copy()
    cases["bucket"] = cases.entry_dpd.map(lambda d: "1-30" if d <= 30 else "31-60")
    by_id = cases.set_index("case_id")
    for row in out.itertuples():
        me = by_id.loc[row.case_id]
        d: date = pd.Timestamp(row.as_of).date()
        peers = cases[
            (cases.primary_product == me.primary_product)
            & (cases.bucket == me.bucket)
            & cases.outcome_date.notna()
            & (cases.outcome_date < d)
        ]
        assert _same(row.cohort_recovery_rate, cohort_rate(int(peers.cure_flag.sum()), len(peers)))
    assert out.cohort_recovery_rate.notna().any()  # some groups reach 50


def _same(a: object, b: float | None) -> bool:
    if b is None:
        return a is None or pd.isna(a)  # type: ignore[arg-type]
    return a is not None and abs(float(a) - b) < 1e-9  # type: ignore[arg-type]


def test_text_features_match_the_rules(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    """Hardship by the 30/90 rule (>= 1 flagged note in 30 days and >= 2 in 90), latest promise in 30 days, any dispute in 90 days,
    any confirmed cease ever, latest note's third party; no notes -> missing."""
    out, silver = built
    notes = silver["text_signals"]
    rank = {"none": 0, "possible": 1, "clear": 2}
    checked = 0
    for row in out.itertuples():
        as_of = pd.Timestamp(row.as_of)
        n = notes[(notes.case_id == row.case_id) & (notes.written_at <= as_of)].sort_values(
            ["written_at", "source_id"]
        )
        if n.empty:
            assert pd.isna(row.hardship_signal) and pd.isna(row.third_party_present_flag)
            continue
        recent = n[n.written_at > as_of - timedelta(days=90)]
        flagged = recent[recent.hardship_signal != "none"]
        repeated = len(flagged) >= 2 and (flagged.written_at > as_of - timedelta(days=30)).any()
        want = (
            max((rank[x] for x in recent.hardship_signal), default=None)
            if repeated
            else (0 if len(recent) else None)
        )
        got = None if pd.isna(row.hardship_signal) else rank[row.hardship_signal]
        assert got == want, row.case_id
        assert bool(row.dispute_flag) == bool(recent.dispute_flag.any())
        assert bool(row.cease_request_flag) == bool(n.cease_request_flag.any())
        assert bool(row.third_party_present_flag) == bool(n.iloc[-1].third_party_present_flag)
        p = n[n.promise_intent & (n.written_at > as_of - timedelta(days=30))]
        if p.empty:
            assert pd.isna(row.promised_amount)
        else:
            assert float(row.promised_amount) == pytest.approx(p.iloc[-1].promised_amount)
        checked += 1
    assert checked > 30


def _points(acct: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """The snapshot row plus its twelve month-ends (m{k} = month-end k months before the snapshot's month)."""
    rows = []
    for a in acct.itertuples():
        rows.append({"date": a.snapshot_date, "month_end": False, **{c: getattr(a, c, None) for c in cols}})
        for k in range(1, 13):
            end = (pd.Timestamp(a.snapshot_date) - pd.DateOffset(months=k) + pd.offsets.MonthEnd(0)).date()
            rows.append({"date": end, "month_end": True, **{c: getattr(a, f"{c}_m{k:02d}") for c in cols}})
    return pd.DataFrame(rows)


def _slope(monthly: pd.Series) -> float | None:
    if monthly.notna().sum() < 3:
        return None
    x = np.array([d.year * 12 + d.month for d in monthly.index], dtype=float)
    return float(np.polyfit(x, monthly.to_numpy(dtype=float), 1)[0])


def _payroll_reference(salary: pd.DataFrame, account: str, d: date) -> tuple[float | None, float | None]:
    """Payroll delay and pay change from employer pay months known at h = min(d, the feed's end + 1 day)."""
    s = salary.assign(start=pd.to_datetime(salary.credit_month + "-01"))
    s = s.assign(end=s.start + pd.offsets.MonthEnd(0))
    h = min(pd.Timestamp(d), pd.Timestamp(s.end.max()) + pd.Timedelta(days=1))
    w = s[(s.deposit_account_id == account) & (s.employer_flag == "Y") & (s.start < h)]
    w = w[w.start >= h - pd.DateOffset(months=7)]
    if w.credit_count.sum() == 0:
        return None, None
    done = w[(w.end < h) & (w.credit_count > 0)].sort_values("start", ascending=False)
    if done.empty:
        return None, None
    before = done.iloc[1:4]
    change = (
        (done.credit_amount_total.iloc[0] / done.credit_count.iloc[0])
        / (before.credit_amount_total.sum() / before.credit_count.sum())
        - 1
        if len(before)
        else None
    )
    dates = [x for x in pd.concat([w.first_credit_date, w.last_credit_date]).dropna() if pd.Timestamp(x) < h]
    gap = int(np.floor(30.4 / done.credit_count.iloc[:3].mean() + 0.5))
    delay = max(0, (h - pd.Timestamp(max(dates))).days - gap - 2)
    return float(delay), None if change is None else round(float(change), 4)


def test_account_features_match_the_rules(built: tuple[pd.DataFrame, dict[str, pd.DataFrame]]) -> None:
    """Latest dpd per account (aged within a month), 30+ dpd month-ends in 12 months, days in
    bucket, trend slopes over 12 months, next payday projected on the schedule, spare cash."""
    out, src = built
    period = {"weekly": 7, "biweekly": 14, "semi_monthly": 15}
    checked = paid = 0
    for r in out.itertuples():
        i = int(r.golden_customer_id[2:])
        d = pd.Timestamp(r.as_of).date()
        year_ago = (pd.Timestamp(d) - pd.DateOffset(months=12)).date()
        card = _points(
            src["card_accounts"][src["card_accounts"].src_customer_ref == f"CK-{i}"], ["dpd", "utilisation"]
        )
        loan = _points(src["loan_accounts"][src["loan_accounts"].src_customer_ref == f"LK-{i}"], ["dpd"])
        dep = _points(
            src["deposit_accounts"][src["deposit_accounts"].src_customer_ref == f"DK-{i}"], ["net_cash_flow"]
        )
        latest = []
        for acct in (card, loan):
            k = acct[acct.date <= d] if len(acct) else acct
            if len(k):
                top = k.sort_values("date").iloc[-1]
                age = (d - top.date).days
                latest.append(top.dpd + (age if top.dpd > 0 and age <= 31 else 0))
        want = max(latest) if latest else None
        assert pd.isna(r.max_dpd) if want is None else r.max_dpd == want, (r.case_id, r.as_of)
        if want is not None:
            ends = pd.concat([card, loan])
            ends = ends[ends.month_end & (ends.dpd >= 30) & (ends.date > year_ago) & (ends.date <= d)]
            assert r.times_30plus_dpd_12m == ends.date.nunique()
            floor = next(
                f
                for top, f in ((0, None), (30, 1), (60, 31), (90, 61), (120, 91), (10**9, 121))
                if want <= top
            )
            assert pd.isna(r.days_in_bucket) if floor is None else r.days_in_bucket == want - floor
        dep_12m = dep[dep.month_end & (dep.date > year_ago) & (dep.date <= d)]
        card_12m = card[card.month_end & (card.date > year_ago) & (card.date <= d)]
        assert _same(r.cash_flow_trend, _slope(dep_12m.groupby("date").net_cash_flow.sum()))
        assert _same(r.card_utilisation_trend, _slope(card_12m.groupby("date").utilisation.mean()))
        dp = src["deposit_accounts"].iloc[i]
        tz = src["c360_customer"].time_zone.iloc[i] or "America/Toronto"
        if dp.payroll_frequency_detected is None:
            assert pd.isna(r.days_to_next_payroll) and pd.isna(r.estimated_monthly_spare_cash)
            continue
        e = dp.expected_next_payroll_date
        ref = days_to_next_payroll(e, as_of=pd.Timestamp(r.as_of).tz_localize("UTC").to_pydatetime(), tz=tz)
        p = period.get(dp.payroll_frequency_detected)
        if ref < 0 or (p and ref < p):  # overdue, or the expected date is the next payday
            assert r.days_to_next_payroll == ref
        elif p:  # projected back along the schedule: a payday on the same cycle
            assert 0 <= r.days_to_next_payroll < p and (ref - r.days_to_next_payroll) % p == 0
        delay, change = _payroll_reference(src["salary_credit_history"], f"D-{i}", d)
        got = None if pd.isna(r.pay_change_vs_3m_avg) else float(r.pay_change_vs_3m_avg)
        assert _same(r.payroll_delay_days, delay), (r.case_id, r.as_of)
        paid += delay is not None and change is not None
        assert (got is None) == (change is None) and (got is None or abs(got - change) < 1.1e-4), (
            r.case_id,
            r.as_of,
        )
        if dp.snapshot_date <= d:
            per_month = {"weekly": 52 / 12, "biweekly": 26 / 12, "semi_monthly": 2, "monthly": 1}[
                dp.payroll_frequency_detected
            ]
            housing = src["customers"].monthly_housing_cost.iloc[i]
            spare = (
                dp.payroll_avg_amount_3m * per_month
                - dp.essential_spend_amount_mtd
                - dp.other_lender_payment_amount_mtd
                - (0 if pd.isna(housing) else housing)
            )
            assert float(r.estimated_monthly_spare_cash) == pytest.approx(spare, abs=0.01)
        checked += 1
    assert checked > 30 and paid > 30
