# ruff: noqa: E501  (report prose and SQL)
"""The business case for Kept: docs/reports/business_case.pdf (LaTeX source alongside).

    uv run python scripts/business_case.py

Reads only the raw release files and the scored cards export (no warehouse, runs next to `kept serve`).
Measured from the data: payday timing vs promises kept and paid, the action mix of our cards vs the bank's current
strategy, contact costs per channel, the roll-to-charge-off funnel, call volume and handle time. Everything that is an
assumption (wage, minutes saved, passes a year, build and run costs) is a named constant below, shown in the report,
and stressed in the sensitivity chart.
"""

from __future__ import annotations

import glob
import os
from collections import Counter
from collections.abc import Callable
from typing import Any

import duckdb
import numpy as np
from reportlib import AQUA, BLUE, INK, KEPT, MUTED, ORANGE, REPO, plt, save, style, tidy

from kept.nba.legacy import legacy_to_action

RAW = REPO / "data" / "raw"
CASES = f"read_csv('{RAW / 'collections_cases.csv'}', header=true, all_varchar=true)"
CONTACTS = f"read_csv('{RAW / 'contact_history.csv'}', header=true, all_varchar=true)"
PROMISES = f"read_csv('{RAW / 'promises_to_pay.csv'}', header=true, all_varchar=true)"
SALARY = f"read_parquet('{RAW / 'salary_credit_history'}/*/*.parquet', hive_partitioning=true)"
YEAR = ("2025-09-28", "2026-09-28")  # the 12 months to the release snapshot

# --- assumptions (CAD). Base, low, high. Each is shown in the report and stressed in the sensitivity chart.
AGENT_COST_PER_HOUR = (
    36.0,
    30.0,
    42.0,
)  # loaded agent cost: ~$50k salary + 30% on-cost over ~1,800 paid hours
WRAPUP_SECONDS_SAVED = (60, 30, 90)  # after-call work saved per agent call by the auto summary
BOOK_PASSES_PER_YEAR = (
    52,
    26,
    104,
)  # how often the whole open book is actually worked through (contact cap, capacity)
# measured, not assumed: promised money paid if every promise fell due 0-2 days after payday, minus what promises
# achieved, on the bank's randomised cases within days-past-due bands (docs/reports/evidence.md §2: +2.7 [+0.1, +6.1])
POLICY_VALUE_PTS = (2.7, 0.1, 6.1)
# share of promises Kept can date to payday: bank's deposit data only 24%; plus the payday customers state to agents
# 55%; plus the pay page asking the rest (assumed 75%)
PAYDAY_COVERAGE = (0.55, 0.24, 0.75)
ROLL_POINTS = (
    0.0,
    0.0,
    1.0,
)  # roll-rate reduction counted (base 0: overlaps the payday gain; high adds the design's 1 pt)
QA_MANUAL_SHARE, QA_MINUTES = 0.02, 12  # today's manual QA sample and minutes per reviewed call
QA_TIME_SAVED = (0.5, 0.25, 0.75)  # share of QA reviewer time saved by pre-scoring every call
BUILD_COST = 300_000  # one-off: productionising (4 engineers x 3 months)
RUN_COST = 150_000  # a year: 1 ops FTE (~$120k) + GPU server and warehouse compute (~$30k); the LLM is local
DRAWS = 20_000  # simulation draws: each assumption triangular over (low, base, high); the payday effect normal on its CI


def q(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:  # type: ignore[type-arg]
    return con.execute(sql).fetchall()


def collect() -> dict[str, object]:
    con = duckdb.connect()
    con.execute("set memory_limit = '16GB'")
    payday = q(
        con,
        f"""
        with pay as (select distinct crm_customer_id, unnest([first_credit_date, last_credit_date]) as d from {SALARY} where crm_customer_id is not null),
        pr as (select ptp_id, crm_customer_id, try_cast(ptp_due_date as date) as due, ptp_status,
                      try_cast(ptp_amount as double) as amt, try_cast(amount_paid_against as double) as paid
               from {PROMISES} where ptp_status in ('kept', 'partially_kept', 'broken')),
        lp as (select pr.ptp_id, max(pay.d) as lp from pr join pay on pay.crm_customer_id = pr.crm_customer_id
               and pay.d between pr.due - 40 and pr.due group by 1)
        select case when lp is null then 'unknown' when due - lp <= 2 then '0-2' when due - lp <= 7 then '3-7' else '8+' end,
               count(*), avg((ptp_status = 'kept')::int), sum(paid) / sum(amt), sum(amt),
               sum(amt) filter (where due > date '{YEAR[0]}' and due <= date '{YEAR[1]}')
        from pr left join lp using (ptp_id) group by 1""",
    )
    cost = dict(
        q(
            con,
            f"""select coalesce(nullif(channel_v2, ''), channel), avg(try_cast(contact_cost_cad as double))
        from {CONTACTS} where try_cast(contact_ts_local as timestamp) >= '2026-09-01' and coalesce(nullif(channel_v2, ''), channel) <> 'system' group by 1""",
        )
    )
    cards = glob.glob(str(REPO / "data" / "exports" / "nba_cards" / "*.parquet"))
    card_file = max(cards, key=os.path.getmtime)
    ours = dict(
        q(con, f"select coalesce(action, 'no action'), count(*) from read_parquet('{card_file}') group by 1")
    )
    ev, positive = q(
        con,
        f"select sum(expected_value), count(*) filter (where expected_value > 0) from read_parquet('{card_file}')",
    )[0]
    tiers = dict(
        q(con, f"select coalesce(tier, 'none'), count(*) from read_parquet('{card_file}') group by 1")
    )
    legacy: Counter[str] = Counter()
    for rec, n in q(
        con, f"select nba_recommendation_last, count(*) from {CASES} where outcome is null group by 1"
    ):
        a = legacy_to_action(rec) if rec else None
        legacy[a.value if a else ("letter" if rec == "send_letter" else "no action")] += n
    roll = q(
        con,
        f"""select count(*), avg((try_cast(dpd_at_day_30 as int) > 30)::int) from {CASES}
        where try_cast(entry_dpd as int) between 1 and 30 and coalesce(dpd_at_day_30, '') <> ''""",
    )[0]
    inflow = q(
        con,
        f"""select count(*), sum(try_cast(entry_overdue as double)) from {CASES}
        where try_cast(entry_dpd as int) between 1 and 30 and try_cast(case_open_date as date) > date '{YEAR[0]}'""",
    )[0]
    co_rolled = q(
        con,
        f"""select avg((lower(chargeoff_flag) = 'true')::int), avg(try_cast(chargeoff_amount as double)) filter (where lower(chargeoff_flag) = 'true')
        from {CASES} where try_cast(entry_dpd as int) between 1 and 30 and try_cast(dpd_at_day_30 as int) > 30""",
    )[0]
    co_cured = q(
        con,
        f"""select avg((lower(chargeoff_flag) = 'true')::int) from {CASES}
        where try_cast(entry_dpd as int) between 1 and 30 and try_cast(dpd_at_day_30 as int) <= 30""",
    )[0][0]
    calls = q(
        con,
        f"""select count(*) from {CONTACTS} where coalesce(nullif(channel_v2, ''), channel) = 'call'
        and coalesce(agent_id, '') <> '' and try_cast(contact_ts_local as timestamp) > timestamp '{YEAR[0]}'""",
    )[0][0]
    aht = q(
        con,
        f"select avg(try_cast(avg_handle_time_sec as double)) from read_csv('{RAW / 'agents.csv'}', header=true, all_varchar=true) where status = 'active'",
    )[0][0]
    return {
        "payday": payday,
        "cost": cost,
        "ours": ours,
        "legacy": dict(legacy),
        "ev": float(ev),
        "positive": positive,
        "tiers": tiers,
        "roll": roll,
        "inflow": inflow,
        "co_rolled": co_rolled,
        "co_cured": co_cured,
        "calls": calls,
        "aht": aht,
    }


CALL_ACTIONS = ("call", "promise_request", "payment_plan", "hardship_review")


def contact_cost(mix: dict[str, int], cost: dict[str, float]) -> float:
    per = {
        "sms_payment_link": cost["sms"],
        "email": cost["email"],
        "push": cost["push"],
        "letter": cost["letter"],
    }
    per |= dict.fromkeys(CALL_ACTIONS, cost["call"])
    return sum(n * per.get(a, 0.0) for a, n in mix.items())


def model(d: dict, i: int | Callable[[tuple], Any]) -> dict[str, Any]:  # type: ignore[type-arg]
    """Annual benefit by component for scenario i (0 base, 1 low, 2 high), or with each assumption picked by a
    function of its (base, low, high) tuple: numpy arrays in, arrays out, for the simulation."""
    pick = (lambda t: t[i]) if isinstance(i, int) else i
    g = {t: (n, kept, paid, amt, amt_y) for t, n, kept, paid, amt, amt_y in d["payday"]}
    seen = sum(g[t][3] for t in ("0-2", "3-7", "8+"))
    promised_year = sum((v[4] or 0) for v in g.values())
    gap = sum(g[t][3] / seen * (g["0-2"][2] - g[t][2]) for t in ("3-7", "8+"))
    per_pass = contact_cost(d["legacy"], d["cost"]) - contact_cost(d["ours"], d["cost"])
    rolled_per_pt = d["inflow"][0] * 0.01 * d["co_rolled"][0] * d["co_rolled"][1]
    qa_hours = d["calls"] * QA_MANUAL_SHARE * QA_MINUTES / 60
    return {
        "Promises dated to payday": promised_year * pick(POLICY_VALUE_PTS) / 100 * pick(PAYDAY_COVERAGE),
        "Cheaper contact mix": per_pass * pick(BOOK_PASSES_PER_YEAR),
        "Agent wrap-up time (call summaries)": d["calls"]
        * pick(WRAPUP_SECONDS_SAVED)
        / 3600
        * pick(AGENT_COST_PER_HOUR),
        "QA reviewer time": qa_hours * pick(QA_TIME_SAVED) * pick(AGENT_COST_PER_HOUR),
        "Roll-rate cut: charge-offs avoided": rolled_per_pt * pick(ROLL_POINTS),
    } | {
        "_gap": gap,
        "_promised_year": promised_year,
        "_per_pass": per_pass,
        "_rolled_per_pt": rolled_per_pt,
        "_qa_hours": qa_hours,
    }


def render(d: dict) -> None:  # type: ignore[type-arg]
    style()
    scen = {name: model(d, i) for i, name in enumerate(("Base", "Low", "High"))}
    comps = [k for k in scen["Base"] if not k.startswith("_")]
    total = {s: sum(v for k, v in m.items() if not k.startswith("_")) for s, m in scen.items()}
    b = scen["Base"]
    g = {t: (n, kept, paid) for t, n, kept, paid, _, _ in d["payday"]}

    # 1. payday
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.3))
    ts = ["0-2", "3-7", "8+"]
    for ax, idx, title in ((axes[0], 1, "promises kept"), (axes[1], 2, "promised money actually paid")):
        vals = [100 * g[t][idx] for t in ts]
        ax.bar(ts, vals, width=0.5, color=[BLUE, BLUE, KEPT])
        for x, v in zip(ts, vals, strict=True):
            ax.text(x, v + 1, f"{v:.1f}%", ha="center", fontsize=8)
        ax.set_ylim(0, 75)
        ax.set_title(title, loc="left")
        ax.set_xlabel("days between payday and due date")
        tidy(ax, "y")
    save(fig, "bc_payday")

    # 2. action mix
    acts = ["call", "hardship_review", "sms_payment_link", "email", "push", "letter", "no action"]
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    x = list(range(len(acts)))
    ax.bar(
        [i - 0.2 for i in x],
        [d["legacy"].get(a, 0) for a in acts],
        width=0.38,
        color=MUTED,
        label="bank's current recommendation (open cases)",
    )
    ax.bar([i + 0.2 for i in x], [d["ours"].get(a, 0) for a in acts], width=0.38, color=BLUE, label="Kept")
    ax.set_xticks(x, [a.replace("_", " ") for a in acts], fontsize=8)
    ax.set_ylabel("open cases")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Same book, different moves: tonight's 96,000 open cases", loc="left")
    tidy(ax, "y")
    save(fig, "bc_mix")

    # 3. funnel
    roll_n, roll_rate = d["roll"]
    fig, ax = plt.subplots(figsize=(6.4, 2.0))
    steps = [
        ("enter at 1–30 days past due", d["inflow"][0]),
        ("roll by day 30", d["inflow"][0] * roll_rate),
        ("end up charged off", d["inflow"][0] * roll_rate * d["co_rolled"][0]),
    ]
    for i, (_, v) in enumerate(steps):
        ax.barh(2 - i, v, color=[BLUE, ORANGE, KEPT][i], height=0.6)
        ax.text(
            v + d["inflow"][0] * 0.015,
            2 - i,
            f"{v:,.0f}",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=INK,
        )
    ax.set_yticks([2, 1, 0], [s[0] for s in steps], fontsize=10.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xticks([])
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    ax.set_xlim(0, d["inflow"][0] * 1.18)
    ax.set_title("Cases a year, and how many roll and charge off", loc="left", fontsize=11)
    save(fig, "bc_funnel")

    # 4. scenarios stacked
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    cols = [BLUE, AQUA, ORANGE, MUTED, KEPT]
    names = ["Low", "Base", "High"]
    for j, s in enumerate(names):
        left = 0.0
        for c, k in zip(cols, comps, strict=True):
            v = scen[s][k] / 1e6
            ax.barh(
                2 - j,
                v,
                left=left,
                color=c,
                height=0.55,
                edgecolor="white",
                linewidth=1.5,
                label=k if j == 0 else None,
            )
            left += v
        ax.text(left + 0.05, 2 - j, f"${total[s] / 1e6:.2f}M", va="center", fontsize=8.5, fontweight="bold")
    ax.set_yticks([2, 1, 0], names)
    ax.set_xlabel("annual benefit, $M CAD")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.42), ncol=3, frameon=False, fontsize=7.5)
    ax.set_title("Annual value by scenario", loc="left")
    tidy(ax)
    save(fig, "bc_scenarios")

    # 5. sensitivity: swing each assumption low/high, others at base
    base_total = total["Base"]
    swings = []
    for label, key in (
        ("payday value 0.1–6.1 pts × coverage 24–75%", "Promises dated to payday"),
        ("book passes 26–104 a year", "Cheaper contact mix"),
        ("wrap-up saved 30–90 s", "Agent wrap-up time (call summaries)"),
        ("QA time saved 25–75%", "QA reviewer time"),
        ("roll-rate cut 0–1 pt", "Roll-rate cut: charge-offs avoided"),
    ):
        lo, hi = scen["Low"][key], scen["High"][key]
        swings.append((label, base_total - b[key] + lo, base_total - b[key] + hi))
    swings.sort(key=lambda s: s[2] - s[1])
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    for i, (_lab, lo, hi) in enumerate(swings):
        ax.barh(i, (base_total - lo) / 1e6, left=lo / 1e6, color=ORANGE, height=0.5)
        ax.barh(i, (hi - base_total) / 1e6, left=base_total / 1e6, color=BLUE, height=0.5)
    ax.axvline(base_total / 1e6, color=INK, linewidth=1)
    ax.set_yticks(range(len(swings)), [s[0] for s in swings], fontsize=8)
    ax.set_xlabel("annual benefit, $M CAD (base in the middle; orange = low end, blue = high end)")
    ax.set_title("What moves the number most", loc="left")
    tidy(ax)
    save(fig, "bc_sensitivity")

    # 6. break-even and the chance of paying back: every assumption drawn at once
    from scipy.stats import norm

    rng = np.random.default_rng(0)
    shared = rng.random(DRAWS)

    def drawer(together: bool) -> Callable[[tuple], np.ndarray]:  # type: ignore[type-arg]
        cache: dict[int, np.ndarray] = {}

        def draw(t: tuple) -> np.ndarray:  # type: ignore[type-arg]
            if id(t) not in cache:
                u = shared if together else rng.random(DRAWS)
                c, a, b_ = (float(v) for v in t)  # base, low, high
                if t is POLICY_VALUE_PTS:  # measured: normal on the 95% interval, negative effects allowed
                    cache[id(t)] = norm.ppf(u, c, (b_ - a) / 3.92)
                elif b_ > a:  # triangular(low, base, high) by its inverse CDF
                    f = (c - a) / (b_ - a)
                    cache[id(t)] = np.where(
                        u < f, a + np.sqrt(u * (b_ - a) * (c - a)), b_ - np.sqrt((1 - u) * (b_ - a) * (b_ - c))
                    )
                else:
                    cache[id(t)] = np.full(DRAWS, c)
            return cache[id(t)]

        return draw

    def simulate(together: bool) -> np.ndarray:
        m = model(d, drawer(together))
        return np.asarray(sum(v for k, v in m.items() if not k.startswith("_")))

    sim_total, sim_together = simulate(False), simulate(True)
    p_year1 = float((sim_total >= RUN_COST + BUILD_COST).mean())
    p_year1_together = float((sim_together >= RUN_COST + BUILD_COST).mean())
    p_run = float((sim_total >= RUN_COST).mean())
    pct = {q: float(np.percentile(sim_total, q)) for q in (5, 50, 95)}
    others = base_total - b["Promises dated to payday"]
    others_low = total["Low"] - scen["Low"]["Promises dated to payday"]
    breakeven = {  # payday effect, in points, at which year-one benefit covers build and run
        "base": (RUN_COST + BUILD_COST - others) / (b["Promises dated to payday"] / POLICY_VALUE_PTS[0]),
        "low": (RUN_COST + BUILD_COST - others_low) / (b["_promised_year"] * PAYDAY_COVERAGE[1] / 100),
    }
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    ax.hist(sim_total / 1e6, bins=60, color=BLUE)
    ax.axvline((RUN_COST + BUILD_COST) / 1e6, color=INK, linewidth=1)
    ax.text((RUN_COST + BUILD_COST) / 1e6, ax.get_ylim()[1] * 0.9, "  build + run, year one", fontsize=8)
    ax.set_xlabel("annual benefit, $M CAD")
    ax.set_yticks([])
    ax.set_title(f"{DRAWS:,} draws over every assumption: {p_year1:.2%} pay back build and run in year one", loc="left")
    tidy(ax)
    save(fig, "bc_simulation")

    year1 = {s: (total[s] - RUN_COST - BUILD_COST) / (RUN_COST + BUILD_COST) for s in names}
    payback = {s: 12 * BUILD_COST / max(total[s] - RUN_COST, 1) for s in names}
    calls_ours = sum(d["ours"].get(a, 0) for a in CALL_ACTIONS)
    calls_legacy = sum(d["legacy"].get(a, 0) for a in CALL_ACTIONS)
    rows = "\n".join(
        f"| {k} | ${scen['Low'][k]:,.0f} | **${scen['Base'][k]:,.0f}** | ${scen['High'][k]:,.0f} |"
        for k in comps
    )
    import json

    out = {
        "scenarios": {k: {c: round(v) for c, v in m.items()} for k, m in scen.items()},
        "total": {k: round(v) for k, v in total.items()},
        "year1_roi": year1,
        "payback_months": payback,
        "simulation": {"draws": DRAWS, "p_payback_year1": p_year1, "p_covers_run": p_run, "p_payback_year1_together": p_year1_together,
                       "percentiles_together": {q: float(np.percentile(sim_together, q)) for q in (5, 50, 95)}, "percentiles": pct},
        "breakeven_payday_pts": breakeven,
        "calls": {"kept": calls_ours, "legacy": calls_legacy},
        "mix": {"kept": d["ours"], "legacy": d["legacy"]},
        "cost": d["cost"],
        "roll": {
            "cases_since_2016": roll_n,
            "rate": roll_rate,
            "inflow_cases": d["inflow"][0],
            "inflow_overdue": d["inflow"][1],
            "chargeoff_if_rolled": d["co_rolled"][0],
            "avg_chargeoff": d["co_rolled"][1],
            "chargeoff_if_not": d["co_cured"],
        },
        "payday": d["payday"],
        "ev": d["ev"],
        "positive": d["positive"],
        "tiers": d["tiers"],
        "calls_year": d["calls"],
        "aht_s": d["aht"],
        "run_cost": RUN_COST,
        "build_cost": BUILD_COST,
        "rows": rows,
    }
    (REPO / "data" / "exports" / "reports" / "business_data.json").write_text(
        json.dumps(out, indent=1, default=str)
    )
    print(
        "figures + data/exports/reports/business_data.json written; compile with: uv run python scripts/reportlib.py"
    )


if __name__ == "__main__":
    render(collect())
