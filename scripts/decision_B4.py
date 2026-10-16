# ruff: noqa: E501  (long tables of numbers and URLs)
"""B4: local vs hosted LLM, cost and quota. Tokens and latencies come from the audit log; volumes from the release
data; hosted prices are published list prices (no hosted API is ever called). Assumptions are the constants below.
Usage (capped): systemd-run --user --scope -q -p MemoryMax=6G -p MemorySwapMax=0 -- uv run python scripts/decision_B4.py
Writes data/exports/reports/decision_B4.json and docs/reports/figures/dec_B4.png.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import numpy as np
from reportlib import AQUA, BLUE, INK, KEPT, MUTED, ORANGE, plt, save, style, tidy

DATA = Path("/home/akshat/hackathons/kept/data")
OUT = DATA / "exports" / "reports" / "decision_B4.json"
MODEL = "llamacpp/qwen3.8-27b"  # the local model today; the audit holds its measured calls
CHECKED = "2026-10-16"
FX = 1.37  # CAD per USD, an assumption: only used to put Ontario power and the workstation in USD
HOSTED = {  # USD per 1M tokens (input, output), list price, no caching or batch discount
    "Gemini 3.5 Flash-Lite": (0.30, 2.50, "https://ai.google.dev/gemini-api/docs/pricing"),
    "Claude Haiku 5.5 (prompt up to 100k)": (
        0.10,
        0.50,
        "https://platform.claude.com/docs/en/about-claude/pricing",
    ),
    "Claude Sonnet 5.5": (2.00, 10.00, "https://platform.claude.com/docs/en/about-claude/pricing"),
}
# Local: one workstation with an RTX 5070 Ti (16 GB, 300 W board power, NVIDIA launch price USD 749 for the card alone).
WORKSTATION_CAD = 3500  # assumption: card, CPU, RAM, PSU, case. Doubled in the sensitivity run.
YEARS = 3
KWH_CAD = 0.157  # Ontario mid-peak price from 1 Nov 2025 (OEB); off-peak 0.098, on-peak 0.203
WATTS_BUSY, WATTS_IDLE = 450, 100  # 300 W card + rest of the box when generating; idle box
UTILISATION = 0.5  # share of a day a GPU can be kept generating (queueing, nightly batch vs daytime Ask)
# Questions and briefs per active agent per day: assumptions, no source data exists for them.
ASK_PER_AGENT = {"low": 1, "base": 5, "high": 15}
BRIEFS_PER_AGENT = {"low": 5, "base": 10, "high": 20}
ASK_PURPOSES = ["ask.scope", "ask.route", "ask.sql_candidate", "ask.narrate", "ask.chart"]


def audit() -> dict:
    c = duckdb.connect(str(DATA / "warehouse" / "audit.duckdb"), read_only=True)
    c.execute("SET memory_limit='3GB'; SET threads=4")
    rows = c.execute(
        """select json_extract_string(body,'$.payload.purpose'), count(*),
           avg(cast(json_extract(body,'$.payload.prompt_tokens') as double)),
           avg(cast(json_extract(body,'$.payload.completion_tokens') as double)),
           avg(cast(json_extract(body,'$.payload.latency_ms') as double)),
           median(cast(json_extract(body,'$.payload.latency_ms') as double))
           from audit_events where kind='llm_call' and json_extract_string(body,'$.payload.model')=?
           group by 1""",
        [MODEL],
    ).fetchall()
    return {
        p: {"calls": n, "prompt": pt, "completion": ct, "latency_ms_mean": lm, "latency_ms_median": ld}
        for p, n, pt, ct, lm, ld in rows
    }


def volumes() -> dict:
    c = duckdb.connect()
    c.execute("SET memory_limit='3GB'; SET threads=4")
    notes = c.execute(
        f"select count(*), sum((year(note_ts_utc)=2026)::int), sum((year(note_ts_utc)=2025)::int), "
        f"min(note_ts_utc), max(note_ts_utc) from read_csv('{DATA}/raw/agent_notes.csv')"
    ).fetchone()
    last = c.execute(f"select max(note_ts_utc) from read_csv('{DATA}/raw/agent_notes.csv')").fetchone()[0]
    days_2026 = (last - last.replace(month=1, day=1, hour=0, minute=0, second=0)).days + 1
    calls = c.execute(
        f"select sum((year(contact_ts_utc)=2026 and channel='call')::int), sum((year(contact_ts_utc)=2025 and channel='call')::int), "
        f"sum((year(contact_ts_utc)=2026 and transcript_id is not null)::int) from read_csv('{DATA}/raw/contact_history.csv', "
        "types={'contact_ts_utc':'TIMESTAMP','transcript_id':'VARCHAR','channel':'VARCHAR'}, ignore_errors=true)"
    ).fetchone()
    agents = c.execute(
        f"select count(*) from read_csv('{DATA}/raw/agents.csv') where status='active'"
    ).fetchone()[0]
    return {
        "notes_total": notes[0],
        "notes_per_day_2026": notes[1] / days_2026,
        "notes_per_day_2025": notes[2] / 365,
        "calls_per_day_2026": calls[0] / days_2026,
        "calls_per_day_2025": calls[1] / 365,
        "transcripts_per_day_2026": calls[2] / days_2026,
        "days_2026": days_2026,
        "active_agents": agents,
    }


def per_unit(a: dict) -> dict:
    """Tokens and GPU-seconds per question, per extraction, per brief (Qwen-era audit calls)."""
    scope = a["ask.scope"]["calls"]  # every question passes the scope check once
    q_calls = {p: a[p]["calls"] / scope for p in ASK_PURPOSES if p in a}
    ask = {
        "calls": sum(q_calls.values()),
        "prompt": sum(q_calls[p] * a[p]["prompt"] for p in q_calls),
        "completion": sum(q_calls[p] * a[p]["completion"] for p in q_calls),
        "seconds": sum(q_calls[p] * a[p]["latency_ms_mean"] for p in q_calls) / 1000,
    }

    def one(p: str) -> dict:
        return {
            "calls": 1,
            "prompt": a[p]["prompt"],
            "completion": a[p]["completion"],
            "seconds": a[p]["latency_ms_mean"] / 1000,
        }

    brief_calls = a["app.case_brief"]["calls"] + a["app.portfolio_brief"]["calls"]
    brief = {
        "calls": 1,
        "prompt": (
            a["app.case_brief"]["prompt"] * a["app.case_brief"]["calls"]
            + a["app.portfolio_brief"]["prompt"] * a["app.portfolio_brief"]["calls"]
        )
        / brief_calls,
        "completion": (
            a["app.case_brief"]["completion"] * a["app.case_brief"]["calls"]
            + a["app.portfolio_brief"]["completion"] * a["app.portfolio_brief"]["calls"]
        )
        / brief_calls,
        "seconds": (
            a["app.case_brief"]["latency_ms_mean"] * a["app.case_brief"]["calls"]
            + a["app.portfolio_brief"]["latency_ms_mean"] * a["app.portfolio_brief"]["calls"]
        )
        / brief_calls
        / 1000,
    }
    return {"ask_question": ask, "extract": one("text.extract"), "brief": brief}


def daily(v: dict, u: dict, scenario: str) -> dict:
    notes = {
        "low": v["notes_per_day_2025"],
        "base": v["notes_per_day_2026"],
        "high": v["notes_per_day_2026"],
    }[scenario]
    # high: every call is transcribed and extracted too (the release has transcripts for a sample only)
    transcripts = {"low": 0.0, "base": v["transcripts_per_day_2026"], "high": v["calls_per_day_2026"]}[
        scenario
    ]
    n = {
        "extract": notes + transcripts,
        "ask_question": v["active_agents"] * ASK_PER_AGENT[scenario],
        "brief": v["active_agents"] * BRIEFS_PER_AGENT[scenario],
    }
    return {
        "units": n,
        "prompt_tokens": sum(n[k] * u[k]["prompt"] for k in n),
        "completion_tokens": sum(n[k] * u[k]["completion"] for k in n),
        "gpu_seconds": sum(n[k] * u[k]["seconds"] for k in n),
        "llm_calls": sum(n[k] * u[k]["calls"] for k in n),
    }


def hosted_year(d: dict, price: tuple, mult: float = 1.0) -> float:
    return mult * 365 * (d["prompt_tokens"] * price[0] + d["completion_tokens"] * price[1]) / 1e6


def local_year(d: dict, mult: float = 1.0, workstation: float = WORKSTATION_CAD) -> tuple[int, float]:
    gpus = max(1, math.ceil(mult * d["gpu_seconds"] / (86400 * UTILISATION)))
    busy = min(1.0, mult * d["gpu_seconds"] / (86400 * gpus))
    kwh = gpus * 24 * 365 * (busy * WATTS_BUSY + (1 - busy) * WATTS_IDLE) / 1000
    return gpus, (gpus * workstation / YEARS + kwh * KWH_CAD) / FX


def main() -> None:
    a, v = audit(), volumes()
    u = per_unit(a)
    scen = {s: daily(v, u, s) for s in ASK_PER_AGENT}
    base = scen["base"]
    table = {}
    for s, d in scen.items():
        gpus, local = local_year(d)
        table[s] = {
            **d,
            "hosted_usd_year": {m: round(hosted_year(d, p)) for m, p in HOSTED.items()},
            "local_gpus": gpus,
            "local_usd_year": round(local),
        }
    # break-even: smallest volume multiple (of the base scenario) where local costs no more than hosted
    grid = np.logspace(-1, 2.5, 700)
    local_curve = [local_year(base, m)[1] for m in grid]
    hosted_curves = {m: [hosted_year(base, p, x) for x in grid] for m, p in HOSTED.items()}
    breakeven = {}
    for m, hc in hosted_curves.items():
        hit = next((float(x) for x, h, lo in zip(grid, hc, local_curve, strict=True) if lo <= h), None)
        breakeven[m] = hit  # None: local never cheaper in range; the grid's first value: cheaper everywhere
    backfill = {
        "notes": v["notes_total"],
        "local_days_one_gpu": v["notes_total"] * u["extract"]["seconds"] / 86400,
        "hosted_usd": {
            m: round(
                v["notes_total"] * (u["extract"]["prompt"] * p[0] + u["extract"]["completion"] * p[1]) / 1e6,
                2,
            )
            for m, p in HOSTED.items()
        },
    }
    night = base["units"]["extract"]
    quota = {
        "free_tier_requests_per_day_per_model": 500,
        "source": "docs/team/tracks/Track_B.md, 4 Oct: 500 requests per day per Google project per model",
        "extractions_per_night_base": night,
        "quota_days_for_one_night": night / 500,
        "quota_days_for_backfill": v["notes_total"] / 500,
        "quota_years_for_backfill": v["notes_total"] / 500 / 365,
    }
    sens = {
        "local_usd_year_workstation_x2": round(local_year(base, 1, WORKSTATION_CAD * 2)[1]),
        "kwh_range_cad": [0.098, 0.203],
    }
    one_gpu_cap = 86400 * UTILISATION / (base["gpu_seconds"])
    res = {
        "model_in_audit": MODEL,
        "checked": CHECKED,
        "audit_by_purpose": a,
        "per_unit": u,
        "volumes": v,
        "assumptions": {
            "ask_per_agent_per_day": ASK_PER_AGENT,
            "briefs_per_agent_per_day": BRIEFS_PER_AGENT,
            "fx_cad_per_usd": FX,
            "workstation_cad": WORKSTATION_CAD,
            "years": YEARS,
            "kwh_cad": KWH_CAD,
            "watts_busy": WATTS_BUSY,
            "watts_idle": WATTS_IDLE,
            "utilisation": UTILISATION,
        },
        "hosted_prices_usd_per_mtok": {
            m: {"input": p[0], "output": p[1], "url": p[2], "checked": CHECKED} for m, p in HOSTED.items()
        },
        "scenarios": table,
        "volume_multiple_one_gpu_covers_base": one_gpu_cap,
        "breakeven_volume_multiple_of_base": breakeven,
        "backfill": backfill,
        "quota": quota,
        "sensitivity": sens,
    }
    OUT.write_text(json.dumps(res, indent=2, default=float))
    style()
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    cols = [BLUE, AQUA, ORANGE]
    for (m, hc), col in zip(hosted_curves.items(), cols, strict=True):
        ax.plot(grid, hc, color=col, label=f"hosted: {m}")
    ax.step(grid, local_curve, where="post", color=KEPT, lw=2, label="local: RTX 5070 Ti workstations")
    for x in breakeven.values():
        if x and x > grid[0]:  # at the left edge the local curve is already below: no crossing in range
            ax.plot([x], [local_year(base, x)[1]], "o", color=INK, ms=5)
            ax.annotate(
                f"break-even {x:.1f}x",
                (x, local_year(base, x)[1]),
                textcoords="offset points",
                xytext=(6, -12),
                fontsize=7,
            )
    ax.axvline(1, color=MUTED, lw=0.8, ls=":")
    ax.text(1.05, ax.get_ylim()[0] * 1.3, "release volume", fontsize=7, color=MUTED)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(
        f"Volume, multiples of the release's base load ({base['units']['extract']:.0f} extractions, "
        f"{base['units']['ask_question']:.0f} questions, {base['units']['brief']:.0f} briefs a day)"
    )
    ax.set_ylabel("Annual cost, USD (log)")
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    tidy(ax, "y")
    save(fig, "dec_B4")
    print(
        json.dumps(
            {
                k: res[k]
                for k in (
                    "per_unit",
                    "volumes",
                    "scenarios",
                    "breakeven_volume_multiple_of_base",
                    "backfill",
                    "quota",
                    "sensitivity",
                    "volume_multiple_one_gpu_covers_base",
                )
            },
            indent=1,
            default=float,
        )
    )


if __name__ == "__main__":
    main()
