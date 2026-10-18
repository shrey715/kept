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
        "_p": p,
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

    def ci(g: list) -> str:  # type: ignore[type-arg]
        return f"{g[0]:+.1f} [{g[1]:+.1f}, {g[2]:+.1f}]"

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
("Booked 18:00: this customer is likelier to answer then (62% chance of reaching them, against 41% at 07:00)"; the line goes in the card's why-not text).

**Predictor shipped: a per-case LightGBM** (`data/exports/models/best_hour.pkl`, `kept train-best-hour`): P(right-party contact | local hour, weekday, the 17 model inputs of the uplift model).
Its inputs are registry inputs only (no language, postal code, accent, age or other protected attribute or proxy; `tests/nba/test_best_hour.py` runs `assert_no_denied`). Fitted on
calls before {res["cutoff"]}, it scores AUC {res["auc"]:.3f} on the later calls (the study's version with three extra context inputs that are not in the serving vector scored 0.729, `uplift_improvement.md`).
A per-case model was servable cleanly, so the fall-back observed-rate table was not needed.

## Result (a prediction, not a measured payment gain)

**Headline, against what the bank actually did, at today's team volume: predicted right-party contact {100 * h['predicted_rpc']:.1f}% to {100 * tv['on']['predicted_rpc']:.1f}%, {ci(tv['on_minus_bank_pts'])} points** (95% case-bootstrap interval).
"What the bank did" is the hour every one of these calls was actually made at, valued by the same model. Team volume is what the team handled per weekday and hour (average over the window's dates, rounded up): the booking may not use more evening hours than the team works today.

Other baselines, each named:

- **Against Kept's current earliest-slot booking** ({100 * tv['off']['predicted_rpc']:.1f}%): {ci(tv['on_minus_off_pts'])} points at team volume. That baseline is itself worse than the bank's own timing ({100 * tv['off']['predicted_rpc']:.1f}% against {100 * h['predicted_rpc']:.1f}%): the earliest free hour is the first hour of the day, the least answered, so today's booking loses contact the bank's calls had.
- **With the full recorded capacity** (`silver.channel_capacity`, as `kept score` reads it; far above the calls made, so it is only real if the team staffs the evening capacity it has on paper): {100 * rc['on']['predicted_rpc']:.1f}%, {ci(rc['on_minus_bank_pts'])} points against the bank's hours and {ci(rc['on_minus_off_pts'])} against the earliest-slot booking ({100 * rc['off']['predicted_rpc']:.1f}%).
- The study (`uplift_improvement.md`) estimated +7.4 points against the hours as booked with a simpler capacity model (each evening hour capped by the total handled over the window, extra context inputs, no booking class). This replay is the more careful one and gets less ({ci(tv['on_minus_bank_pts'])} at team volume); likely reasons, not separated: the cap here is per date, calls are booked one at a time through the real booking class, capacity is in bank time while calls are in customer time, and the model here has only inputs available at serving (AUC {res['auc']:.3f}, the study's 0.729).

| Booking | Predicted right-party contact | Observed hourly rate, same bookings | Calls moved off their earliest slot |
|---|---:|---:|---:|
{row('The bank: hours actually called at', h)}
{row('Team volume, switch off (earliest slot)', tv['off'])}
{row('**Team volume, switch on**', tv['on'], f"{100 * tv['share_moved_from_earliest']:.0f}%")}
{row('Recorded capacity, switch off', rc['off'])}
{row('Recorded capacity, switch on', rc['on'], f"{100 * rc['share_moved_from_earliest']:.0f}%")}

The last column re-values the same bookings with the observed right-party rate by hour before the cutoff, with no per-case model: {100 * (tv['on']['observed_hour_rate_estimate'] - h['observed_hour_rate_estimate']):+.1f} points against the bank's hours ({100 * h['observed_hour_rate_estimate']:.1f}%; their actual outcome was {100 * h['observed_rpc']:.1f}%) at team volume.

**This is a large operational change.** With the switch on, **{100 * tv['share_moved_from_earliest']:.0f}% of calls** are booked into a different hour than the earliest free one ({100 * rc['share_moved_from_earliest']:.0f}% at recorded capacity), and the day's hour mix shifts toward the late afternoon and evening, as below. Agents' shifts, not the model, decide whether those hours exist.

Share of calls by local hour:

| Hour (customer-local) | The bank's hours | Team volume, off | Team volume, on | Recorded, off | Recorded, on |
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
- Every customer record allows calls from 07:00, but almost no call was ever made before 08:00 local, so the model has little data there (it treats 07:00 like 08:00); the earliest-slot booking uses 07:00.
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
            "observed_hour_rate_estimate": float(np.mean([rate[min(rate, key=lambda k: abs(k - int(x)))] for x in actual.hour])),
            "hour_mix": {int(h): int(n) for h, n in actual.hour.value_counts().sort_index().items()},
        },
    }  # fmt: skip
    p_bank = model.p_rows(test, actual.hour, actual.weekday)

    def gap(a: np.ndarray, b: np.ndarray) -> list[float]:  # a minus b in points: mean and a 95% case-bootstrap interval
        codes, rng = pd.factorize(test.case_id)[0], np.random.default_rng(0)
        n, d = codes.max() + 1, a - b
        bs = []
        for _ in range(200):  # resample whole cases
            w = np.bincount(rng.integers(0, n, n), minlength=n)[codes]
            bs.append(float((w * d).sum() / w.sum()))
        return [100 * float((a - b).mean()), *(100 * np.quantile(bs, [0.025, 0.975])).tolist()]

    for name, units in (("team_volume", team_volume(test)), ("recorded_capacity", recorded)):
        off, on = run(test, units, None), run(test, units, model)
        so, sn = summary(test, off, model, rate), summary(test, on, model, rate)
        res[name] = {
            "off": {k: v for k, v in so.items() if k != "_p"}, "on": {k: v for k, v in sn.items() if k != "_p"},
            "on_minus_bank_pts": gap(sn["_p"], p_bank), "on_minus_off_pts": gap(sn["_p"], so["_p"]),  # type: ignore[arg-type]
            "share_moved_from_earliest": on["moved"] / len(test),  # type: ignore[operator]
            "share_hour_differs_from_off": float((on["booked"].hour.to_numpy() != off["booked"].hour.to_numpy()).mean()),  # type: ignore[attr-defined]
        }  # fmt: skip
        print(name, json.dumps(res[name], indent=1, default=float), flush=True)
        OUT.write_text(json.dumps(res, indent=1, default=float))
    MD.write_text(to_markdown(res))
    print(f"wrote {OUT} and {MD}")


if __name__ == "__main__":
    main()
