# ruff: noqa: E501  (report labels)
"""Decision A2: nightly batch plus the live-note path, against hourly re-scoring (streaming).

    uv run python scripts/decision_A2.py [--warehouse data/warehouse/eval_copy.duckdb] [--data data] [--day 2026-09-24]

Read-only on the warehouse; writes data/exports/reports/decision_A2.json and docs/reports/figures/dec_A2.png.
1. Event rates: per day, over the weekdays of the 60 days before the replay day, how many open cases get a note,
   an outbound contact, a payment, a promise falling due (cases open that day, from silver).
2. Replay of one weekday, in memory. The nightly run is 06:00 UTC. Of the case features only the two sets that
   events move within a day are recomputed (contact_features.sql and promise_features.sql, the same SQL rules,
   point in time at each hour): answer rates, payment-link use, contacts in 7 days, broken promises, kept ratio.
   The others (account, payroll, cohort, text) stay at the stored nightly values: the account tables change monthly,
   the text features are what the live-note path refreshes. The spine is the dbt rule (open at as_of). Cards come
   from the live engine (kept.nba.score.load + KeptEngine), `now` fixed at 06:00 so only the events differ.
   A card "changes" when the best action differs from the 06:00 card. Split: a note on the case in the window
   (the live-note path re-scores the case on it) vs not.
Not copied, nothing written to a warehouse.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from reportlib import AQUA, KEPT, MUTED, plt, save, style, tidy

from kept.config import CONTACT_CAP_7D, DATA_DIR
from kept.features.drift import load_alarm
from kept.nba.context import KeptContextBuilder
from kept.nba.engine import KeptEngine
from kept.nba.promise_model import load_model
from kept.nba.score import _Buffer, _NoStore, _Precomputed, call_capacity, load

CHANGING = [
    "answer_rate",
    "answer_rate_after_18h",
    "payment_link_usage",
    "contacts_last_7d",
    "broken_promises_90d",
    "kept_promise_ratio",
]
DAY_RATES = """
with days as (select cast(d as date) as day from generate_series(date '{a}', date '{b}', interval 1 day) t(d)
              where isodow(cast(d as date)) <= 5),
open_n as (select day, count(*) as open_cases from days
           join silver.collections_cases c on c.case_open_date <= day and (c.outcome_date is null or c.outcome_date > day)
           group by day),
ev as (
  select cast(note_ts_utc as date) as day, case_id, 'note' as kind from silver.agent_notes where case_id is not null
  union all select cast(contact_ts_utc as date), case_id, 'outbound_contact' from silver.contact_history
            where direction = 'outbound' and case_id is not null
  union all select cast(contact_ts_utc as date), case_id, 'inbound_contact' from silver.contact_history
            where direction = 'inbound' and case_id is not null
  union all select cast(paid_date as date), case_id, 'payment' from silver.promises_to_pay
            where paid_date is not null and amount_paid_against > 0
  union all select cast(contact_ts_utc as date), case_id, 'payment_taken_on_contact' from silver.contact_history
            where payment_taken_flag and case_id is not null
  union all select cast(ptp_due_date as date), case_id, 'promise_due' from silver.promises_to_pay
),
per_case as (select ev.day, kind, count(*) as events, count(distinct case_id) as cases
             from ev semi join days using (day)
             group by all)
select kind, avg(events / open_cases) as events_per_open_case_day, avg(cases / open_cases) as share_open_cases,
       min(cases / open_cases) as min_share, max(cases / open_cases) as max_share, avg(open_cases) as open_cases
from per_case join open_n using (day) group by kind order by kind"""


def event_rates(conn: duckdb.DuckDBPyConnection, day: date) -> dict[str, Any]:
    a, b = day - timedelta(days=60), day - timedelta(days=1)
    df = conn.sql(DAY_RATES.format(a=a, b=b)).df()
    return {
        "window": f"weekdays {a}..{b}",
        **{
            r.kind: {
                "events_per_open_case_per_day": round(r.events_per_open_case_day, 4),
                "share_of_open_cases_with_one": round(r.share_open_cases, 4),
                "min_day": round(r.min_share, 4),
                "max_day": round(r.max_share, 4),
            }
            for r in df.itertuples()
        },
        "open_cases_mean": int(df.open_cases.mean()),
    }


def changing_features(
    conn: duckdb.DuckDBPyConnection, spine: pd.DataFrame, as_of: datetime, hour: str = "contact_hour_local"
) -> pd.DataFrame:
    """contact_features.sql and promise_features.sql for the spine at one as_of (naive UTC), same rules."""
    ts = as_of.replace(tzinfo=None)
    conn.register("spine", spine[["case_id", "crm_customer_id"]])
    return conn.sql(f"""
    with s as (select case_id, crm_customer_id, timestamp '{ts}' as as_of from spine),
    attempts as (select case_id, crm_customer_id, channel, dial_result, {hour} as contact_hour_local, link_payment_flag,
                        payment_link_id, contact_ts_utc
                 from silver.contact_history where direction = 'outbound' and contact_ts_utc <= timestamp '{ts}'),
    per_customer as (
      select s.case_id,
        avg(case when h.dial_result = 'answered' then 1.0 else 0.0 end) filter (where h.channel = 'call') as answer_rate,
        avg(case when h.dial_result = 'answered' then 1.0 else 0.0 end)
            filter (where h.channel = 'call' and h.contact_hour_local >= 18) as answer_rate_after_18h,
        avg(case when h.link_payment_flag then 1.0 else 0.0 end) filter (where h.payment_link_id is not null) as payment_link_usage
      from s left join attempts h on h.crm_customer_id = s.crm_customer_id group by s.case_id),
    per_case as (
      select s.case_id, count(h.case_id) as contacts_last_7d
      from s left join attempts h on h.case_id = s.case_id and h.contact_ts_utc > s.as_of - interval 7 day group by s.case_id),
    prom as (
      select s.case_id,
        count(*) filter (where p.ptp_status = 'broken' and p.ptp_due_date > cast(s.as_of as date) - 90
                         and p.ptp_due_date <= cast(s.as_of as date)) as broken_promises_90d,
        cast(count(*) filter (where p.ptp_status = 'kept') as double)
          / nullif(count(*) filter (where p.ptp_status in ('kept', 'partially_kept', 'broken')), 0) as kept_promise_ratio
      from s left join silver.promises_to_pay p on p.crm_customer_id = s.crm_customer_id
        and p.status_ts <= s.as_of group by s.case_id)
    select * from per_customer join per_case using (case_id) join prom using (case_id) order by case_id""").df()


def _nan_none(v: Any) -> Any:
    return None if v is None or (isinstance(v, float) and v != v) else v


def make_engine(bulk: Any, calls: Any, buffer: Any, export_dir: Path) -> KeptEngine:
    """The engine `kept score` builds, over in-memory readers (kept.nba.score.score does the same inline)."""
    model = pickle.loads((export_dir / "models" / "uplift.pkl").read_bytes())  # kept train's champion file
    return KeptEngine(
        context=KeptContextBuilder(
            c360=bulk, features=bulk, cases=bulk.case_row, holdout_salt="a2", extractions=bulk
        ),
        features=bulk,
        scorer=_Precomputed(model, list(bulk.vectors.values())),
        audit_log=buffer,
        proposals=_NoStore(),
        drift_alarm=load_alarm(export_dir / "features"),
        promise_model=load_model(export_dir / "models" / "promise.pkl"),
        call_capacity=calls,
    )


def replay(conn: duckdb.DuckDBPyConnection, day: date, data: Path) -> dict[str, Any]:
    t0 = datetime(day.year, day.month, day.day, 6, tzinfo=UTC)  # the nightly run
    bulk = load(conn)
    # the stored vectors are stamped with the real nightly (15 Oct); the engine refuses features newer than `now`
    bulk.vectors = {k: v.model_copy(update={"as_of": t0}) for k, v in bulk.vectors.items()}
    now = t0 + timedelta(minutes=30)  # a card is scored shortly after the features
    calls = call_capacity(conn)
    spine = conn.sql(
        f"select case_id, coll_customer_ref as crm_customer_id from silver.collections_cases "
        f"where case_open_date <= date '{day}' and (outcome_date is null or outcome_date > date '{day}')"
    ).df()
    spine = spine[spine.case_id.isin(bulk.vectors)].reset_index(drop=True)
    notes = conn.sql(
        f"select distinct case_id from silver.agent_notes where note_ts_utc > timestamp '{t0:%Y-%m-%d %H:%M:%S}' "
        f"and note_ts_utc <= timestamp '{t0 + timedelta(hours=24):%Y-%m-%d %H:%M:%S}'"
    ).df()
    noted = set(notes.case_id)
    hours = [t0 + timedelta(hours=h) for h in range(25)]
    t_feat = time.perf_counter()
    feats = [changing_features(conn, spine, h).set_index("case_id")[CHANGING] for h in hours]
    feature_seconds = time.perf_counter() - t_feat

    base = feats[0]
    changed_inputs: dict[
        int, pd.Series
    ] = {}  # hour -> bool per case: any of the six inputs differs from 06:00
    for i, f in enumerate(feats[1:], 1):
        diff = ~((f == base) | (f.isna() & base.isna()))
        changed_inputs[i] = diff.any(axis=1)
    ever = pd.concat(changed_inputs, axis=1).any(axis=1)
    by_input = {
        c: int(
            pd.concat([~((f[c] == base[c]) | (f[c].isna() & base[c].isna())) for f in feats[1:]], axis=1)
            .any(axis=1)
            .sum()
        )
        for c in CHANGING
    }

    buffer = _Buffer()
    engine = make_engine(bulk, calls, buffer, data / "exports")

    stored = dict(bulk.vectors)
    cache: dict[tuple[str, tuple[Any, ...]], tuple[str, str, bool]] = {}

    def card(case_id: str, h: int) -> tuple[str, str, bool]:
        key = (case_id, tuple(_nan_none(float(x)) if x == x else None for x in feats[h].loc[case_id]))
        if key not in cache:
            new = {c: _nan_none(feats[h].at[case_id, c]) for c in CHANGING}
            new["contacts_last_7d"] = int(new["contacts_last_7d"])
            new["broken_promises_90d"] = int(new["broken_promises_90d"])
            bulk.vectors[case_id] = stored[case_id].model_copy(update=new)
            c = engine.recommend(case_id, now)
            buffer.events.clear()
            p = c.proposal
            cache[key] = (
                p.action.value if p else "none",
                p.tier.value if p else "none",
                c.hardship_banner is not None,
            )
        return cache[key]

    def cap_of(cid: str) -> int:
        cap = bulk.cases[cid].contact_cap_7d
        return CONTACT_CAP_7D if cap is None else cap

    t_score = time.perf_counter()
    rows = []
    for case_id in ever.index[ever]:
        first = card(case_id, 0)
        series = [card(case_id, h) for h in range(1, 25)]
        act = [s[0] for s in series]
        rows.append(
            {
                "case_id": case_id,
                "action_0": first[0],
                "tier_0": first[1],
                "hardship_0": first[2],
                "changed_any_hour": any(a != first[0] for a in act),
                "changed_by_end": act[-1] != first[0],
                "tier_changed_by_end": series[-1][1] != first[1],
                "first_change_hour": next((h for h, a in enumerate(act, 1) if a != first[0]), None),
                "noted": case_id in noted,
                # the CONTACT_CAP check (rules.py) removes every contact action, a hardship review included
                "cap_crossed": (int(feats[0].at[case_id, "contacts_last_7d"]) < cap_of(case_id))
                != (int(feats[24].at[case_id, "contacts_last_7d"]) < cap_of(case_id)),
                "changed_hours": [h for h in range(1, 25) if changed_inputs[h][case_id]],
            }
        )
    score_seconds = time.perf_counter() - t_score
    # control: the clock alone. Same features (06:00), `now` moved to each hour: the call windows and capacity depend on it
    sample = spine.case_id.sample(3000, random_state=0).tolist()
    for cid in sample:
        bulk.vectors[cid] = stored[cid].model_copy(
            update={c: _nan_none(feats[0].at[cid, c]) for c in CHANGING}
            | {
                "contacts_last_7d": int(feats[0].at[cid, "contacts_last_7d"]),
                "broken_promises_90d": int(feats[0].at[cid, "broken_promises_90d"]),
            }
        )

    def act(cid: str, at: datetime) -> str:
        c = engine.recommend(cid, at)
        buffer.events.clear()
        return c.proposal.action.value if c.proposal else "none"

    zero = {cid: act(cid, now) for cid in sample}
    clock = {
        h: sum(act(cid, now + timedelta(hours=h)) != zero[cid] for cid in sample) / len(sample)
        for h in (3, 6, 12, 18, 24)
    }
    df = pd.DataFrame(rows)
    n = len(spine)
    flips = df[df.changed_by_end] if len(df) else df
    covered, hard = (int(flips.noted.sum()), int(flips.hardship_0.sum())) if len(df) else (0, 0)
    hourly = [
        {
            "hour_after_nightly": h,
            "cases_with_input_change": int(changed_inputs[h].sum()),
            "cards_best_action_differs_from_nightly": int(
                sum(card(c, h)[0] != card(c, 0)[0] for c in changed_inputs[h].index[changed_inputs[h]])
            ),
        }
        for h in (1, 2, 3, 6, 9, 12, 18, 24)
    ]
    return {
        "day": f"{day} 06:00 UTC to {day + timedelta(days=1)} 06:00 UTC",
        "cases_open_at_nightly": n,
        "cases_with_any_changing_input": int(ever.sum()),
        "cases_with_changing_input_by_feature": by_input,
        "cards_rescored_distinct_states": len(cache),
        "cards_changed_any_hour": int(df.changed_any_hour.sum()) if len(df) else 0,
        "cards_changed_by_end_of_day": len(flips),
        "share_changed_by_end_of_day": round(len(flips) / n, 5),
        "share_changed_any_hour": round(float(df.changed_any_hour.sum()) / n, 5) if len(df) else 0.0,
        "share_tier_changed_by_end": round(float(df.tier_changed_by_end.sum()) / n, 5) if len(df) else 0.0,
        "changed_with_note_in_window_live_path_covers": covered,
        "changed_without_note_not_covered": len(flips) - covered,
        "changed_cards_hardship_at_nightly": hard,
        "changed_cards_where_contact_cap_crossed": int(flips.cap_crossed.sum()) if len(df) else 0,
        "changed_hardship_cards_where_contact_cap_crossed": int((flips.cap_crossed & flips.hardship_0).sum())
        if len(df)
        else 0,
        "changes_by_hour_after_nightly": hourly,
        "first_change_hour_histogram": {
            int(k): int(v) for k, v in df.first_change_hour.dropna().value_counts().sort_index().items()
        }
        if len(df)
        else {},
        "from_to_actions_end_of_day": {
            f"{a} -> {b}": int(v)
            for (a, b), v in pd.Series(
                list(zip(flips.action_0, [card(c, 24)[0] for c in flips.case_id], strict=True))
            )
            .value_counts()
            .head(8)
            .items()
        }
        if len(flips)
        else {},
        "control_clock_only_share_action_differs_by_hours_later_sample_3000": {
            str(h): round(v, 4) for h, v in clock.items()
        },
        "seconds_feature_sql_25_hours": round(feature_seconds, 1),
        "seconds_rescoring": round(score_seconds, 1),
    }


def nightly_wall(data: Path) -> dict[str, Any]:
    """data/exports/reports/nightly_run.json when present; else the step seconds the nightly logs print."""
    f = data / "exports" / "reports" / "nightly_run.json"
    if f.exists():
        return {"source": str(f.name), **json.loads(f.read_text())}
    import re

    out = {}
    for log in ("nightly_run.log", "nightly_full.log"):
        text = (data / "warehouse" / log).read_text()
        steps = {m[0]: int(m[1]) for m in re.findall(r"== (\w+): exit 0 in (\d+)s", text)}
        out[log] = {"steps_seconds": steps, "total_seconds": sum(steps.values())}
    return {"source": "data/warehouse/nightly_*.log (nightly_run.json is not on this machine)", **out}


def figure(out: dict[str, Any]) -> str:
    style()
    h = out["replay"]["changes_by_hour_after_nightly"]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = [r["hour_after_nightly"] for r in h]
    n = out["replay"]["cases_open_at_nightly"]
    ax.plot(
        x, [100 * r["cases_with_input_change"] / n for r in h], color=AQUA, marker="o", label="inputs changed"
    )
    ax.plot(
        x,
        [100 * r["cards_best_action_differs_from_nightly"] / n for r in h],
        color=KEPT,
        marker="o",
        label="best action differs from the nightly card",
    )
    ax.set_xlabel("Hours after the 06:00 nightly run")
    ax.set_ylabel("% of open cases")
    ax.set_title(f"Hourly re-scoring would change few cards ({out['replay']['day'][:10]})", loc="left")
    ax.legend(frameon=False, fontsize=8)
    ax.axhline(0, color=MUTED, lw=0.5)
    tidy(ax)
    return save(fig, "dec_A2")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(DATA_DIR / "warehouse" / "eval_copy.duckdb"))
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--day", default="2026-09-24")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    conn = duckdb.connect(a.warehouse, read_only=True)
    conn.execute("SET memory_limit='3GB'; SET threads=4")
    out: dict[str, Any] = {
        "generated": datetime.now(UTC).isoformat(timespec="minutes"),
        "warehouse": Path(a.warehouse).name,
    }
    out["event_rates"] = event_rates(conn, day)
    out["nightly_wall_time"] = nightly_wall(a.data)
    out["replay"] = replay(conn, day, a.data)
    out["figure"] = figure(out)
    (a.data / "exports" / "reports" / "decision_A2.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
