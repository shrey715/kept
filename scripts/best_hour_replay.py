# ruff: noqa: E501  (report prose)
"""Replay the test window's calls through the nightly call booking with best-hour off and on: docs/reports/best_hour.md.

    uv run python scripts/best_hour_replay.py [--warehouse data/warehouse/kept.duckdb] [--model data/exports/models/best_hour.pkl]

Every outbound call on a randomly assigned case from 15 Aug (the model was fitted on calls before it) is booked day by day through
`kept.nba.ranking.CallCapacity`, the class the nightly batch uses: switch off = `book` (earliest half-hour slot with capacity inside the
customer's hours), switch on = `book_best`. Two capacity books: "recorded" is silver.channel_capacity as `kept score` reads it; "team volume" is
what the team actually handled per weekday and hour (average over the window's dates, rounded up), the staffing limit the study used.
The predicted right-party contact (RPC) rate is the model's own estimate at the booked hour, so it is a prediction, not a measured gain;
a second estimate uses the observed RPC rate by hour before the cutoff and no per-case model. Writes data/exports/reports/best_hour.json.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

from kept.config import OPERATING_TZ, WAREHOUSE_PATH
from kept.nba import best_hour as bh
from kept.nba.engine import WINDOW
from kept.nba.ranking import CallCapacity
from kept.nba.score import SQL_CALL_CAPACITY

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "exports" / "reports" / "best_hour.json"
HOURS = range(5, 23)


class Ctx:  # the fields CallCapacity reads
    def __init__(self, tz: str, start: time, end: time, sunday: bool) -> None:
        self.time_zone, self.permitted_call_start_local, self.permitted_call_end_local = tz, start, end
        self.sunday_contact_permitted = sunday


def hm(s: str) -> time:
    h, m = str(s).split(":")[:2]
    return time(int(h), int(m))


def calls(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    d = bh.load(conn)
    c = conn.sql("""select crm_customer_id, any_value(time_zone) tz, any_value(permitted_call_start_local) ps,
        any_value(permitted_call_end_local) pe, any_value(sunday_contact_permitted) sun from silver.customers group by 1""").df()
    d = d.merge(
        conn.sql(
            "select contact_id as decision_id, crm_customer_id, contact_ts_local from silver.contact_history"
        ).df(),
        on="decision_id",
    ).merge(c, on="crm_customer_id", how="left")
    d["tz"] = d.tz.fillna("America/Toronto")
    d["ps"], d["pe"] = d.ps.fillna("08:00"), d.pe.fillna("21:00")
    d["sun"] = d.sun.fillna(False).astype(bool)
    d["day"] = pd.to_datetime(d.contact_ts_local).dt.date
    return d


def team_volume(test: pd.DataFrame) -> dict[tuple[int, int], float]:
    """Calls the team handled per (weekday, hour), averaged over the window's dates with that weekday, rounded up."""
    per = test.groupby(["day", "weekday", "hour"]).size().reset_index(name="n")
    days = test.groupby("weekday").day.nunique()
    return {
        (int(w), int(h)): float(math.ceil(n / days[w]))
        for (w, h), n in per.groupby(["weekday", "hour"]).n.sum().items()
    }


def run(
    test: pd.DataFrame, units: dict[tuple[int, int], float], model: bh.BestHourModel | None
) -> dict[str, object]:
    """Book every call of `test` day by day; booked hour and weekday per call, and the checks."""
    cap = CallCapacity(units, tz=OPERATING_TZ, length=WINDOW, best_hour=model)
    op, inputs = ZoneInfo(OPERATING_TZ), list(bh.model_inputs())
    booked: dict[int, tuple[int, int]] = {}
    moved = later_day = outside = unbooked = (
        0  # unbooked: no free slot within a week, the call keeps its first slot
    )
    use: Counter[tuple[date, int]] = Counter()
    for day, g in test.groupby("day", sort=True):
        for i, r in g.iterrows():  # ponytail: decision order within a day; the nightly orders by balance
            ctx = Ctx(r.tz, hm(r.ps), hm(r.pe), bool(r.sun))
            tz = ZoneInfo(r.tz)
            first_s = datetime.combine(day, hm(r.ps), tz)
            first = (first_s.astimezone(UTC), (first_s + WINDOW).astimezone(UTC))
            fo = first_s.astimezone(op)
            fkey = (fo.date(), fo.hour)
            left0 = cap._left.get(fkey, units.get((fo.weekday(), fo.hour), 0.0))
            if model is None:
                slot, mv = cap.book(ctx, first), None  # type: ignore[arg-type]
            else:
                slot, mv = cap.book_best(ctx, first, test.loc[[i], inputs])  # type: ignore[arg-type]
            s, e = slot[0].astimezone(tz), slot[1].astimezone(tz)
            if slot == first and cap._left.get(fkey, left0) != left0 - 1:
                unbooked += 1
                booked[i] = (s.hour, s.weekday())
                continue  # not a booking: no capacity used, and not counted in the checks
            if mv is not None:
                moved += 1
                later_day += mv.booked.date() != mv.earliest.date()
            lo, hi = datetime.combine(s.date(), hm(r.ps), tz), datetime.combine(s.date(), hm(r.pe), tz)
            outside += not (lo <= s and e <= hi)
            o = s.astimezone(op)
            use[(o.date(), o.hour)] += 1
            booked[i] = (s.hour, s.weekday())
    over = sum(max(0.0, n - units.get((d.weekday(), h), 0.0)) for (d, h), n in use.items())
    b = pd.DataFrame.from_dict(booked, orient="index", columns=["hour", "weekday"]).loc[test.index]
    return {
        "booked": b,
        "moved": moved,
        "later_day": later_day,
        "outside_hours": outside,
        "capacity_overrun_calls": int(over),
        "unbooked": unbooked,
    }


def summary(
    test: pd.DataFrame, r: dict[str, object], model: bh.BestHourModel, rate: dict[int, float]
) -> dict[str, object]:
    b: pd.DataFrame = r["booked"]  # type: ignore[assignment]
    p = model.p_rows(test, b.hour, b.weekday)
    return {
        "predicted_rpc": float(p.mean()),
        "observed_hour_rate_estimate": float(np.mean([rate[min(rate, key=lambda k: abs(k - int(h)))] for h in b.hour])),  # nearest hour with calls
        "hour_mix": {int(h): int(n) for h, n in b.hour.value_counts().sort_index().items()},
        "moved_from_earliest": r["moved"], "later_day": r["later_day"], "outside_hours": r["outside_hours"],
        "capacity_overrun_calls": r["capacity_overrun_calls"], "unbooked": r["unbooked"],
    }  # fmt: skip


MD = REPO / "docs" / "reports" / "best_hour.md"


def to_markdown(res: dict) -> str:  # type: ignore[type-arg]
    h, tv, rc = res["as_historically_booked"], res["team_volume"], res["recorded_capacity"]
    n = res["calls"]

    def row(label: str, r: dict, moved: object = "") -> str:  # type: ignore[type-arg]
        return f"| {label} | {100 * r['predicted_rpc']:.1f}% | {100 * r['observed_hour_rate_estimate']:.1f}% | {moved} |"

    def share(mix: dict, hr: int) -> str:  # type: ignore[type-arg]
        return f"{100 * mix.get(str(hr), mix.get(hr, 0)) / n:.0f}%"

    hours = sorted(
        {
            int(k)
            for m in (
                h["hour_mix"],
                tv["off"]["hour_mix"],
                tv["on"]["hour_mix"],
                rc["off"]["hour_mix"],
                rc["on"]["hour_mix"],
            )
            for k in m
        }
    )
    return (
        f"""# Best-hour call booking

Written by `scripts/best_hour_replay.py` on the {n:,} outbound calls on randomly assigned cases from {res["cutoff"]} to the end of the data ({res["days"]} days), booked day by day through
`kept.nba.ranking.CallCapacity`, the class the nightly batch uses. Nothing here changes the default nightly run: the booking is behind `kept score --best-hour` (or `KEPT_BEST_HOUR=1`) and is off unless asked for.

## What it does

With the switch off, a call goes into the **earliest** half-hour slot with capacity inside the customer's calling hours. With it on, the call goes into the slot with the
highest predicted chance of reaching the right party, among the free slots **on the same local day as the earliest one** (never a later day), inside the customer's hours
and the operating hour's capacity, Sunday rules unchanged; ties go to the earlier slot. When it moves a call, the card says so in one line, with the model's numbers
("Booked 18:00: this customer is likelier to answer then (62% chance of reaching them, against 41% at 07:00)").

**Predictor shipped: a per-case LightGBM** (`data/exports/models/best_hour.pkl`, `kept train-best-hour`): P(right-party contact | local hour, weekday, the 17 model inputs of the uplift model).
Its inputs are registry inputs only (no language, postal code, accent, age or other protected attribute or proxy; `tests/nba/test_best_hour.py` runs `assert_no_denied`). Fitted on
calls before {res["cutoff"]}, it scores AUC {res["auc"]:.3f} on the later calls (the study's version with three extra context inputs that are not in the serving vector scored 0.729, `uplift_improvement.md`).
A per-case model was servable cleanly, so the fall-back observed-rate table was not needed.

## Result (a prediction, not a measured payment gain)

Two capacity books: **team volume** is what the team actually handled per weekday and hour (average over the window's dates, rounded up), the limit the study used;
**recorded capacity** is `silver.channel_capacity` as `kept score` reads it (far above the calls made). Predicted RPC is the model's own estimate at the booked hour;
the last column re-values the same bookings with the observed RPC rate by hour before the cutoff, with no per-case model.

| Booking | Predicted right-party contact | Observed hourly rate, same bookings | Calls moved off their earliest slot |
|---|---:|---:|---:|
{row("As historically booked", h)}
{row("Team volume, switch off", tv["off"])}
{row("Team volume, switch on", tv["on"], f"{100 * tv['share_moved_from_earliest']:.0f}%")}
{row("Recorded capacity, switch off", rc["off"])}
{row("Recorded capacity, switch on", rc["on"], f"{100 * rc['share_moved_from_earliest']:.0f}%")}

Switch on against off: **{100 * (tv["on"]["predicted_rpc"] - tv["off"]["predicted_rpc"]):+.1f} points** at team volume ({100 * (tv["on"]["observed_hour_rate_estimate"] - tv["off"]["observed_hour_rate_estimate"]):+.1f} on observed hourly rates),
{100 * (rc["on"]["predicted_rpc"] - rc["off"]["predicted_rpc"]):+.1f} points at recorded capacity ({100 * (rc["on"]["observed_hour_rate_estimate"] - rc["off"]["observed_hour_rate_estimate"]):+.1f}). The study's capacity-respecting estimate against the hours as booked was +7.4 points.
Today's booking is not the historical one: with all customers allowed from 07:00 it puts nearly every call into the first hours of the day, which is why "off" is below "as historically booked".

Share of calls by local hour:

| Hour | As historically booked | Team volume, off | Team volume, on | Recorded, off | Recorded, on |
|---:|---:|---:|---:|---:|---:|
"""
        + "\n".join(
            f"| {hr}:00 | {share(h['hour_mix'], hr)} | {share(tv['off']['hour_mix'], hr)} | {share(tv['on']['hour_mix'], hr)} | {share(rc['off']['hour_mix'], hr)} | {share(rc['on']['hour_mix'], hr)} |"
            for hr in hours
        )
        + f"""

Checks, switch on (every booked call; calls with no free slot within a week keep their first slot and are not counted):

| Check | Team volume | Recorded capacity |
|---|---:|---:|
| Calls outside the customer's permitted hours | {tv["on"]["outside_hours"]} | {rc["on"]["outside_hours"]} |
| Capacity overruns (calls above an operating hour's units) | {tv["on"]["capacity_overrun_calls"]} | {rc["on"]["capacity_overrun_calls"]} |
| Calls moved to a later day than their earliest bookable slot | {tv["on"]["later_day"]} | {rc["on"]["later_day"]} |
| Calls left unbooked (no free slot in a week) | {tv["on"]["unbooked"]} | {rc["on"]["unbooked"]} |

## Limits

- It is a **predicted** right-party-contact gain. Hour was not randomised. The model picks the hour it scores highest and is then scored by itself, which flatters the gain; the observed-hourly-rate column
  is the check that does not use the per-case model, and the within-customer comparison in the study (evening calls reach the same customer 24 points more often) is the check against "who gets called when".
  A pilot cell (best-hour booking on half the calls, the rest as today) would measure it.
- Right-party contact is the outcome, not payment: the study found contact itself barely moves payment, so a payment gain is not claimed.
- Evening capacity is a staffing question. The recorded capacity book is generous; the team-volume book assumes no more evening staff than today.
- Calls are replayed in decision order within a day; the nightly orders by balance, so who gets the scarce hours differs.
- Hours before 08:00 are allowed by every customer record (07:00 to 21:00) but no call was ever made then, so the model has no data there; "off" books the 07:00 hour.
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--report-only", action="store_true", help="rewrite docs/reports/best_hour.md from best_hour.json"
    )
    ap.add_argument("--warehouse", default=str(WAREHOUSE_PATH))
    ap.add_argument("--model", type=Path, default=REPO / "data" / "exports" / "models" / "best_hour.pkl")
    ap.add_argument("--limit", type=int, default=0, help="first N calls only (a quick check)")
    args = ap.parse_args()
    if args.report_only:
        MD.write_text(to_markdown(json.loads(OUT.read_text())))
        return
    conn = duckdb.connect(args.warehouse, read_only=True)
    conn.execute("set memory_limit = '6GB'")
    model = bh.load_model(args.model)
    assert model is not None, "run `kept train-best-hour` first"
    d = calls(conn)
    test = (
        d[d.decision_at >= bh.CUTOFF]
        .sort_values(["day", "decision_id"])
        .head(args.limit or None)
        .reset_index(drop=True)
    )
    rate = (
        d[d.decision_at < bh.CUTOFF].groupby("hour").rpc.mean().to_dict()
    )  # observed RPC by hour, before the cutoff
    recorded = {(int(w), int(h)): float(u) for w, h, u in conn.execute(SQL_CALL_CAPACITY).fetchall()}
    from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]

    actual = pd.DataFrame({"hour": test.hour, "weekday": test.weekday})
    res: dict[str, object] = {
        "auc": float(roc_auc_score(test.rpc, model.p_rows(test, test.hour, test.weekday))),
        "calls": len(test), "model": model.model_version, "cutoff": f"{bh.CUTOFF:%Y-%m-%d}", "days": int(test.day.nunique()),
        "as_historically_booked": {
            "predicted_rpc": float(model.p_rows(test, actual.hour, actual.weekday).mean()), "observed_rpc": float(test.rpc.mean()),
            "hour_mix": {int(h): int(n) for h, n in actual.hour.value_counts().sort_index().items()},
        },
    }  # fmt: skip
    for name, units in (("team_volume", team_volume(test)), ("recorded_capacity", recorded)):
        off, on = run(test, units, None), run(test, units, model)
        res[name] = {
            "off": summary(test, off, model, rate), "on": summary(test, on, model, rate),
            "share_moved_from_earliest": on["moved"] / len(test),  # type: ignore[operator]
            "share_hour_differs_from_off": float((on["booked"].hour.to_numpy() != off["booked"].hour.to_numpy()).mean()),  # type: ignore[attr-defined]
        }  # fmt: skip
        print(name, json.dumps(res[name], indent=1, default=float), flush=True)
        OUT.write_text(json.dumps(res, indent=1, default=float))
    MD.write_text(to_markdown(res))
    print(f"wrote {OUT} and {MD}")


if __name__ == "__main__":
    main()
