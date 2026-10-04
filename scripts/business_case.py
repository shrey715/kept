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
from datetime import UTC, datetime

import duckdb
from reportlib import AQUA, BLUE, INK, KEPT, MUTED, ORANGE, REPO, build_pdf, plt, save, style, tidy

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
PAYDAY_CAPTURE = (
    0.5,
    0.25,
    0.75,
)  # share of the observed payday gap we actually capture when we pick the date
ROLL_POINTS = (
    0.0,
    0.0,
    1.0,
)  # roll-rate reduction counted (base 0: overlaps the payday gain; high adds the design's 1 pt)
QA_MANUAL_SHARE, QA_MINUTES = 0.02, 12  # today's manual QA sample and minutes per reviewed call
QA_TIME_SAVED = (0.5, 0.25, 0.75)  # share of QA reviewer time saved by pre-scoring every call
BUILD_COST = 300_000  # one-off: productionising (4 engineers x 3 months)
RUN_COST = 150_000  # a year: 1 ops FTE (~$120k) + GPU server, warehouse compute, hosted LLM at production volume (~$30k)


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


def model(d: dict, i: int) -> dict[str, float]:  # type: ignore[type-arg]
    """Annual benefit by component for scenario i (0 base, 1 low, 2 high)."""
    g = {t: (n, kept, paid, amt, amt_y) for t, n, kept, paid, amt, amt_y in d["payday"]}
    seen = sum(g[t][3] for t in ("0-2", "3-7", "8+"))
    promised_year = sum((v[4] or 0) for v in g.values())
    gap = sum(g[t][3] / seen * (g["0-2"][2] - g[t][2]) for t in ("3-7", "8+"))
    per_pass = contact_cost(d["legacy"], d["cost"]) - contact_cost(d["ours"], d["cost"])
    rolled_per_pt = d["inflow"][0] * 0.01 * d["co_rolled"][0] * d["co_rolled"][1]
    qa_hours = d["calls"] * QA_MANUAL_SHARE * QA_MINUTES / 60
    return {
        "Promises dated to payday": promised_year * gap * PAYDAY_CAPTURE[i],
        "Cheaper contact mix": per_pass * BOOK_PASSES_PER_YEAR[i],
        "Agent wrap-up time (call summaries)": d["calls"]
        * WRAPUP_SECONDS_SAVED[i]
        / 3600
        * AGENT_COST_PER_HOUR[i],
        "QA reviewer time": qa_hours * QA_TIME_SAVED[i] * AGENT_COST_PER_HOUR[i],
        "Fewer roll-forwards → charge-offs avoided": rolled_per_pt * ROLL_POINTS[i] / 1.0
        if ROLL_POINTS[i]
        else 0.0,
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
    payday_fig = save(fig, "bc_payday")

    # 2. action mix
    acts = ["call", "hardship_review", "sms_payment_link", "email", "push", "letter", "no action"]
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    x = list(range(len(acts)))
    ax.bar(
        [i - 0.2 for i in x],
        [d["legacy"].get(a, 0) for a in acts],
        width=0.38,
        color=MUTED,
        label="bank's current strategy",
    )
    ax.bar([i + 0.2 for i in x], [d["ours"].get(a, 0) for a in acts], width=0.38, color=BLUE, label="Kept")
    ax.set_xticks(x, [a.replace("_", " ") for a in acts], fontsize=8)
    ax.set_ylabel("open cases")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Same book, different moves: tonight's 96,000 open cases", loc="left")
    tidy(ax, "y")
    mix_fig = save(fig, "bc_mix")

    # 3. funnel
    roll_n, roll_rate = d["roll"]
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    steps = [
        ("enter at 1–30 DPD (12 months)", d["inflow"][0]),
        ("roll by day 30", d["inflow"][0] * roll_rate),
        ("end up charged off", d["inflow"][0] * roll_rate * d["co_rolled"][0]),
    ]
    for i, (lab, v) in enumerate(steps):
        ax.barh(2 - i, v, color=[BLUE, ORANGE, KEPT][i], height=0.55)
        ax.text(v + d["inflow"][0] * 0.01, 2 - i, f"{lab}: {v:,.0f}", va="center", fontsize=8)
    ax.set_xlim(0, d["inflow"][0] * 1.6)
    ax.axis("off")
    ax.set_title("Where charge-offs come from: only cases that roll", loc="left")
    funnel_fig = save(fig, "bc_funnel")

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
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=2, frameon=False, fontsize=7.5)
    ax.set_title("Annual value by scenario", loc="left")
    tidy(ax)
    scen_fig = save(fig, "bc_scenarios")

    # 5. sensitivity: swing each assumption low/high, others at base
    base_total = total["Base"]
    swings = []
    for label, key in (
        ("payday capture 25–75%", "Promises dated to payday"),
        ("book passes 26–104 a year", "Cheaper contact mix"),
        ("wrap-up saved 30–90 s", "Agent wrap-up time (call summaries)"),
        ("QA time saved 25–75%", "QA reviewer time"),
        ("roll-rate cut 0–1 pt", "Fewer roll-forwards → charge-offs avoided"),
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
    sens_fig = save(fig, "bc_sensitivity")

    year1 = {s: (total[s] - RUN_COST - BUILD_COST) / (RUN_COST + BUILD_COST) for s in names}
    payback = {s: 12 * BUILD_COST / max(total[s] - RUN_COST, 1) for s in names}
    calls_ours = sum(d["ours"].get(a, 0) for a in CALL_ACTIONS)
    calls_legacy = sum(d["legacy"].get(a, 0) for a in CALL_ACTIONS)
    rows = "\n".join(
        f"| {k} | ${scen['Low'][k]:,.0f} | **${scen['Base'][k]:,.0f}** | ${scen['High'][k]:,.0f} |"
        for k in comps
    )
    md = (
        f"""---
title: "Business case"
subtitle: "What Kept is worth to Maple Bank, from the bank's own data"
author: "Team Sharpe Shooters"
date: "{datetime.now(UTC):%d %B %Y}"
---

# TL;DR

**Base case: ${total["Base"] / 1e6:.1f}M a year** (low ${total["Low"] / 1e6:.1f}M, high ${total["High"] / 1e6:.1f}M) against
**${RUN_COST / 1e3:.0f}K a year to run** and **${BUILD_COST / 1e3:.0f}K to productionise**. First-year ROI
**{year1["Base"]:.1f}x** in the base case ({year1["Low"]:.1f}x low), payback in about **{payback["Base"]:.0f} month{"s" if payback["Base"] >= 1.5 else ""}**
({payback["Low"]:.0f} months low).

Where it comes from, biggest first:

1. **Promises dated to payday.** Promises due 0–2 days after payday get **{100 * g["0-2"][2]:.1f}%** of the promised money
   paid; 8+ days after, **{100 * g["8+"][2]:.1f}%**. Kept sizing puts the due date right after payday.
2. **A cheaper, kinder contact mix.** Same number of calls, but most become hardship reviews instead of collection calls,
   and $1.10 letters become near-free texts, emails and app pushes.
3. **Agent time.** Auto call summaries cut after-call work on {d["calls"]:,} agent calls a year.
4. **QA time.** Every call gets pre-scored, so reviewers listen to the ones that need it.

Plus an upside we don't count in the base case: **every point of roll rate is worth ~${b["_rolled_per_pt"] / 1e3:.0f}K a
year** in charge-offs avoided. The 5% hold-out measures it after launch.

![]({scen_fig}){{ width=100% }}

# 1. The payday effect (the core idea)

From {sum(g[t][0] for t in ts):,} resolved promises where we can see the customer's salary deposits:

![]({payday_fig}){{ width=100% }}

| Promise due | Promises | Kept | Promised money paid |
|---|--:|--:|--:|
"""
        + "\n".join(
            f"| {t} days after payday | {g[t][0]:,} | {100 * g[t][1]:.1f}% | {100 * g[t][2]:.1f}% |"
            for t in ts
        )
        + f"""

- **The gap:** weighting by where the money sits today, moving promises that fall 3+ days after payday to 0–2 days lifts the
  paid share by **{100 * b["_gap"]:.1f} points**.
- **The base:** **${b["_promised_year"] / 1e6:.1f}M** promised in the 12 months to 28 Sep 2026.
- **We only take half of it** in the base case (`PAYDAY_CAPTURE` = 50%): the gap is descriptive, and some of it is who
  gets which due date, not the date itself. That gives **${b["Promises dated to payday"] / 1e6:.2f}M a year**; the full
  gap would be ${b["_promised_year"] * b["_gap"] / 1e6:.2f}M.

# 2. Contact mix and cost

![]({mix_fig}){{ width=100% }}

- **Calls:** {calls_ours:,} call-type actions for Kept vs {calls_legacy:,} for the current strategy. Basically the same
  number, but **{d["ours"].get("hardship_review", 0):,} of ours are hardship reviews** (a specialist conversation)
  where the old strategy has {d["legacy"].get("call", 0):,} collection calls.
- **Letters → digital:** the old strategy sends {d["legacy"].get("letter", 0):,} letters at ${d["cost"]["letter"]:.2f}; Kept
  uses SMS links (${d["cost"]["sms"]:.2f}), email and app pushes (${d["cost"]["email"]:.3f}).
- **Cost per pass over the book** (channel costs from `contact_history`, Sep 2026): ${contact_cost(d["legacy"], d["cost"]):,.0f}
  old vs ${contact_cost(d["ours"], d["cost"]):,.0f} Kept, **${b["_per_pass"]:,.0f} saved each pass**. At
  {BOOK_PASSES_PER_YEAR[0]} passes a year (base) that's **${b["Cheaper contact mix"] / 1e3:.0f}K**.
- **Model's view:** tonight's {d["positive"]:,} positive-uplift proposals are expected to bring in **${d["ev"] / 1e6:.2f}M more
  within 14 days than waiting** (uplift × balance at risk). It's a model estimate, so it's not in the totals: the hold-out
  proves or disproves it.

# 3. Roll rate → charge-offs (the upside)

![]({funnel_fig}){{ width=100% }}

- **{100 * roll_rate:.1f}%** of cases that enter at 1–30 days past due have rolled by day 30 ({roll_n:,} cases since 2016).
- Of rolled cases, **{100 * d["co_rolled"][0]:.2f}%** end up charged off, averaging **${d["co_rolled"][1]:,.0f}**. Of
  cases that don't roll: **{100 * d["co_cured"]:.2f}%**. Rolling is the only road to a charge-off.
- **{d["inflow"][0]:,} cases (${d["inflow"][1] / 1e6:.1f}M overdue)** entered at 1–30 DPD in the last 12 months, so
  **1 point of roll rate ≈ ${b["_rolled_per_pt"] / 1e3:.0f}K a year** avoided.
- The design's hypothesis is 1–2 points. We keep it **out of the base case** because it overlaps the payday gain (kept
  promises are what stop rolls), and count 1 point in the high case only.

# 4. Time saved

- **Call summaries:** {d["calls"]:,} agent calls in 12 months, average handle time {d["aht"] / 60:.1f} min. Saving
  {WRAPUP_SECONDS_SAVED[0]} s of after-call work each at ${AGENT_COST_PER_HOUR[0]:.0f}/h is **${b["Agent wrap-up time (call summaries)"] / 1e3:.0f}K a year**
  (about {d["calls"] * WRAPUP_SECONDS_SAVED[0] / 3600 / 1800:.1f} agents' worth of hours back on the phones).
- **QA:** a {100 * QA_MANUAL_SHARE:.0f}% manual sample at {QA_MINUTES} min a call is {b["_qa_hours"]:,.0f} reviewer hours a
  year. Pre-scoring every call (88–100% agreement with human QA per item) lets reviewers skip the clean ones:
  **${b["QA reviewer time"] / 1e3:.0f}K** at {100 * QA_TIME_SAVED[0]:.0f}% time saved, and coverage goes from 2% of calls to all of them.

# 5. Cost, ROI, payback

| | Low | Base | High |
|---|--:|--:|--:|
{rows}
| **Total benefit / year** | **${total["Low"]:,.0f}** | **${total["Base"]:,.0f}** | **${total["High"]:,.0f}** |
| Run cost / year | ${RUN_COST:,.0f} | ${RUN_COST:,.0f} | ${RUN_COST:,.0f} |
| Build (one-off) | ${BUILD_COST:,.0f} | ${BUILD_COST:,.0f} | ${BUILD_COST:,.0f} |
| **Year-1 ROI** | **{year1["Low"]:.1f}x** | **{year1["Base"]:.1f}x** | **{year1["High"]:.1f}x** |
| **Payback** | {payback["Low"]:.1f} months | {payback["Base"]:.1f} months | {payback["High"]:.1f} months |

**Why it's cheap to run.** One nightly batch (~7 minutes for the whole book on one machine), a local open model for
text (no per-call fees, notes never leave the bank), a hosted model only for the Ask, and DuckDB/dbt instead of a
cluster. The run cost is mostly one ops person.

![]({sens_fig}){{ width=100% }}

**Assumptions (all in `scripts/business_case.py`, change them and re-run):**

| Assumption | Base | Low | High | Why |
|---|--:|--:|--:|---|
| Payday gap we capture | {100 * PAYDAY_CAPTURE[0]:.0f}% | {100 * PAYDAY_CAPTURE[1]:.0f}% | {100 * PAYDAY_CAPTURE[2]:.0f}% | the gap is descriptive; half is a cautious read |
| Passes over the open book a year | {BOOK_PASSES_PER_YEAR[0]} | {BOOK_PASSES_PER_YEAR[1]} | {BOOK_PASSES_PER_YEAR[2]} | weekly work-through under the 3-in-7-days cap |
| After-call work saved per call | {WRAPUP_SECONDS_SAVED[0]} s | {WRAPUP_SECONDS_SAVED[1]} s | {WRAPUP_SECONDS_SAVED[2]} s | the summary pre-fills the wrap-up note |
| Loaded agent cost | ${AGENT_COST_PER_HOUR[0]:.0f}/h | ${AGENT_COST_PER_HOUR[1]:.0f}/h | ${AGENT_COST_PER_HOUR[2]:.0f}/h | ~$50K salary + 30% on-cost |
| QA reviewer time saved | {100 * QA_TIME_SAVED[0]:.0f}% | {100 * QA_TIME_SAVED[1]:.0f}% | {100 * QA_TIME_SAVED[2]:.0f}% | reviewers skip pre-scored clean calls |
| Roll-rate points counted | {ROLL_POINTS[0]:.0f} | {ROLL_POINTS[1]:.0f} | {ROLL_POINTS[2]:.0f} | overlaps payday; high case only |
| Build / run cost | ${BUILD_COST / 1e3:.0f}K / ${RUN_COST / 1e3:.0f}K | | | 4 engineers × 3 months; 1 ops FTE + infra |

# 6. Things that don't fit in a spreadsheet

- **Fair treatment and regulator risk.** Hardship shows up when the customer *says* it (text) or the money *shows* it
  (late payroll, a pay cut, new EI), and it immediately limits contact to protective actions, with two people
  releasing anything sensitive. Every decision has a plain-English reason and an audit trail.
- **The cost of the protection, honestly.** {d["tiers"].get("red", 0):,} of tonight's cards are Red (a specialist
  reviews first). That's real specialist time. A rule for customers already on an active hardship plan would cut it;
  it's the next thing we'd ship.
- **Measured, not promised.** A permanent 5% hold-out stays on the old strategy, so every number above gets checked
  against reality, and a kill switch reverts everyone if it isn't working.

*Rebuild:* `uv run python scripts/business_case.py` (reads only the raw files and the cards export).
"""
    )
    print(build_pdf(md, "business_case"))


if __name__ == "__main__":
    render(collect())
