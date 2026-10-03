"""dbt feature models agree with the Python reference definitions (the oracle), point in time.

Needs dbt: `uv run --with "dbt-core>=1.10" --with "dbt-duckdb>=1.9" pytest tests/features/test_dbt_features.py`
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from kept.contracts.feature_registry import FEATURES
from kept.features.definitions import (
    answer_rate,
    broken_promises_90d,
    cohort_rate,
    contacts_last_7d,
    kept_promise_ratio,
)

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
                "status_ts": due + timedelta(days=rng.randrange(-5, 6)),
                "ptp_status": rng.choice(["open", "kept", "partially_kept", "broken", "cancelled"]),
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
    return {
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
        c.execute("create schema silver")
        c.execute("create schema text")
        for name, df in silver.items():
            c.register("df", df)
            schema = "text" if name == "text_signals" else "silver"  # C's model lives in text
            c.execute(f"create table {schema}.{name} as select * from df")
            c.unregister("df")
        # A's real crosswalk needs the match step's output; the features only join these columns
        c.execute("create schema gold")
        c.execute("""create table gold.identity_crosswalk (golden_customer_id varchar, source_system varchar,
                     source_key varchar, valid_to timestamptz)""")

    import os

    os.environ["KEPT_WAREHOUSE_PATH"] = str(db)
    vars_ = {"features_start": str(AS_OFS[0]), "features_as_of": str(AS_OFS[-1])}
    res = dbtRunner().invoke(
        [
            "build",
            "--select",  # the feature models over the fixture silver, not A's silver models
            "path:models/features",
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
    """Strongest hardship in 90 days, latest promise in 30 days, any dispute in 90 days,
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
        want = max((rank[x] for x in recent.hardship_signal), default=None)
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
