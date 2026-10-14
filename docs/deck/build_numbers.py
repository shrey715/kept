# ruff: noqa: E501  (deck number formatting)
"""Write numbers.tex: every number the deck shows, read from the reports and the warehouse, as LaTeX macros.

    uv run python docs/deck/build_numbers.py && (cd docs/deck && xelatex kept.tex && xelatex kept.tex)

No number in kept.tex is typed by hand: rerun this after a report changes and the slides follow.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb

from kept.app.portfolio import overview

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "data" / "exports" / "reports"


def load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((REPORTS / name).read_text())


def esc(s: object) -> str:
    return str(s).replace("%", r"\%").replace("$", r"\$").replace("&", r"\&").replace("_", r"\_")


def main() -> None:
    card, biz, fair, drift = (
        load("model_card.json"),
        load("business_data.json"),
        load("fairness_data.json"),
        load("drift_data.json"),
    )
    inv = load("invariance_protected.json")
    p = overview(duckdb.connect(str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"), read_only=True))
    tot, roi, pay = biz["total"], biz["year1_roi"], biz["payback_months"]
    m: dict[str, str] = {
        # tonight's book
        "openCases": f"{p.cases:,}",
        "balanceAtRisk": f"\\${p.balance / 1e6:.1f}M",
        "expectedRecovery": f"\\${p.expected / 1e6:.2f}M",
        "actionableShare": f"{p.actionable / p.cases:.0%}".replace("%", r"\%"),
        "redCases": f"{p.red:,}",
        "hardStops": f"{p.hard_stops:,}",
        # business case
        "valueBase": f"\\${tot['Base'] / 1e6:.2f}M",
        "valueLow": f"\\${tot['Low'] / 1e6:.2f}M",
        "valueHigh": f"\\${tot['High'] / 1e6:.2f}M",
        "roiBase": f"{roi['Base']:.1f}",
        "paybackBase": f"{pay['Base']:.1f}",
        # models
        "promiseAuc": f"{card['promise']['auc']:.3f}",
        "promiseBrier": f"{card['promise']['brier']:.3f}",
        "promiseRows": f"{card['promise']['rows_test']:,}",
        "qiniAny": f"{card['uplift']['qini_any_contact']:.4f}",
        "qiniNoise": f"{card['uplift']['qini_noise']:.4f}",
        "upliftRows": f"{card['uplift']['rows_test']:,}",
        # governance
        "invarianceCards": f"{inv['cases']:,}",
        "invarianceDiffer": str(inv["cards_differ"]),
        "driftHeadline": esc(drift["headline"]),
        "fairnessAttributes": str(len(fair["attributes"])),
    }
    # the statistics behind each claim (scripts/evidence_report.py, scripts/uplift_learners.py, business_case.py)
    ev, ul = load("evidence.json"), load("uplift_learners.json")

    def pt(v: list[float], unit: str = "") -> str:  # "+6.1" and "2.8–10.6"
        return f"{v[0]:+.1f}{unit}"

    def iv(lo: float, hi: float) -> str:
        return f"{lo:+.1f} to {hi:+.1f}" if lo < 0 < hi else f"{lo:.1f}–{hi:.1f}"

    wide, blend = ev["auc|Kept, wide: LightGBM + random forest, averaged ranks|all"], ev["auc|Kept's wide model and the bank's score, averaged ranks|all"]
    wide_fair = ev["auc|Kept, wide: LightGBM + random forest, averaged ranks|before_due"]
    placebo = [v for k, v in ev.items() if k.startswith("placebo_")]
    sim, be = biz["simulation"], biz["breakeven_payday_pts"]
    best, ut = ul["best"], ul["test"]
    BANK = "The bank's strategy"
    con = duckdb.connect(str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"), read_only=True)
    per_week = con.execute(
        "select count(*) / 52.0 from silver.promises_to_pay where ptp_created_ts >= date '2025-09-28' - interval 1 year"
        " and ptp_created_ts < date '2025-09-28' + interval 0 day"
    ).fetchone()[0] or 1
    kept0 = 0.368  # kept rate of promises from June 2026 (evidence.md §7 window); the base the hold-out is measured on

    def weeks(delta: float, share: float) -> float:  # 80% power, two-sided 5%
        from scipy.stats import norm

        z = norm.ppf(0.975) + norm.ppf(0.8)
        p2 = kept0 + delta
        return z**2 * (kept0 * (1 - kept0) / share + p2 * (1 - p2) / (1 - share)) / delta**2 / per_week

    m |= {
        "payMoney": pt(ev["payday_money"]), "payMoneyCI": iv(*ev["payday_money"][1:]),
        "payKept": pt(ev["payday_kept"]), "payKeptCI": iv(*ev["payday_kept"][1:]),
        "payPromises": f"{ev['payday_promises']:,}",
        "onBefore": pt(ev["on_vs_before"]), "onBeforeCI": iv(*ev["on_vs_before"][1:]),
        "onAfter": pt(ev["on_vs_after"]), "onAfterCI": iv(*ev["on_vs_after"][1:]),
        "within": pt(ev["within_customer"]), "withinCI": iv(*ev["within_customer"][1:]),
        "placeboNull": f"{sum(lo < 0 < hi for _, lo, hi in placebo)} of {len(placebo)}",
        "wideAuc": f"{wide[0]:.3f}", "wideGap": f"{wide[1]:+.1f}", "wideGapCI": iv(*wide[2:]),
        "wideFairGap": f"{wide_fair[1]:+.1f}", "wideFairGapCI": iv(*wide_fair[2:]),
        "blendAuc": f"{blend[0]:.3f}", "blendGap": f"{blend[1]:+.1f}", "blendGapCI": iv(*blend[2:]),
        "offPolicy": f"{ev['offpolicy_per_1000'][0]:+.0f}", "offPolicyCI": f"{ev['offpolicy_per_1000'][1]:.0f}–{ev['offpolicy_per_1000'][2]:.0f}",
        "cellAll": f"\\${ev['cell_top100'][0] / 1e3:+.0f}K", "cellTop": f"\\${ev['cell_top10'][0] / 1e3:+.0f}K",
        "pPayback": f"{100 * sim['p_payback_year1']:.2f}\\%", "pPaybackTogether": f"{100 * sim['p_payback_year1_together']:.1f}\\%",
        "breakevenLow": f"{be['low']:.1f}",
        "drName": esc(best),
        "drCall": f"{ut['call'][best]:+.4f}", "drSms": f"{ut['sms_payment_link'][best]:+.4f}", "drEmail": f"{ut['email'][best]:+.4f}",
        "chCall": f"{ut['call']['Champion (live)']:+.4f}", "chSms": f"{ut['sms_payment_link']['Champion (live)']:+.4f}",
        "chEmail": f"{ut['email']['Champion (live)']:+.4f}",
        "bkCall": f"{ut['call'][BANK]:+.4f}", "bkSms": f"{ut['sms_payment_link'][BANK]:+.4f}",
        "bkEmail": f"{ut['email'][BANK]:+.4f}",
        "weeksFive": f"{weeks(ev['payday_kept'][0] / 100, 0.05):.0f}", "weeksTwenty": f"{weeks(ev['payday_kept'][0] / 100, 0.20):.0f}",
    }
    lines = [f"\\newcommand{{\\K{k}}}{{{v}}}" for k, v in m.items()]
    # value drivers, base case, in $k, largest first (for the value-tree bars)
    drivers = sorted(
        ((k, v) for k, v in biz["scenarios"]["Base"].items() if not k.startswith("_") and v),
        key=lambda kv: -kv[1],
    )
    lines.append(
        "\\newcommand{\\Kdrivers}{" + ",".join(f"{v / 1e3:.0f}/{{{esc(k)}}}" for k, v in drivers) + "}"
    )
    # the bank's A/B: kept rate and Wilson 95% interval per cell, in percent
    lines.append(
        "\\newcommand{\\Kab}{"
        + ",".join(
            f"{c.kept_rate * 100:.2f}/{c.kept_lo * 100:.2f}/{c.kept_hi * 100:.2f}"
            f"/{{{esc(c.test_cell.replace('_', ' '))}}}/{c.promises}"
            for c in p.ab_test
        )
        + "}"
    )
    # promise model reliability: predicted/observed per bin, in percent
    lines.append(
        "\\newcommand{\\Kreliability}{"
        + " ".join(
            f"({r['predicted'] * 100:.1f},{r['observed'] * 100:.1f})" for r in card["promise"]["reliability"]
        )
        + "}"
    )
    lines.append(
        "\\newcommand{\\Kreldots}{"
        + ",".join(
            f"{r['predicted'] * 100:.1f}/{r['observed'] * 100:.1f}" for r in card["promise"]["reliability"]
        )
        + "}"
    )
    lines.append(
        "\\newcommand{\\Kimportance}{"
        + ",".join(f"{f['share'] * 100:.0f}/{{{esc(f['label'])}}}" for f in card["promise"]["importance"])
        + "}"
    )
    # benchmarks: graded right of graded, per suite (the latest bench_run outputs)
    for suite, name in (("released", "Released"), ("stress", "Stress"), ("drill", "Drill")):
        rows = json.loads((REPORTS / f"{suite}_answers.json").read_text())
        graded = [r for r in rows if r.get("correct") is not None]
        lines.append(
            f"\\newcommand{{\\K{name}}}{{{sum(r['correct'] is True for r in graded)}/{len(graded)}}}"
        )
    # tuning: champion and tuned challenger on the test decisions (docs/reports/tuning.md)
    tune = {
        m[0]: m[1:]
        for m in re.findall(
            r"\| (Champion \(live\)|Tuned challenger) \| ([-\d.]+) \| ([-\d.]+) \| ([-\d.]+) \| ([-\d.]+) \|",
            (REPO / "docs/reports/tuning.md").read_text(),
        )
    }
    for key, name in (("Champion (live)", "Champ"), ("Tuned challenger", "Tuned")):
        call, noise, anyc, _ = tune[key]
        lines.append(f"\\newcommand{{\\Kq{name}}}{{{call}/{noise}/{anyc}}}")
    lines.append(
        "\\newcommand{\\Ktunerows}{"
        + " ".join(
            f"{label} & {tune[key][0]} & {tune[key][1]} & {tune[key][2]} \\\\"
            for key, label in (
                ("Champion (live)", "Champion (live)"),
                ("Tuned challenger", "Tuned challenger"),
            )
        )
        + "}"
    )
    n_trials = len(
        re.findall(r"^\| \d+ \| [-\d.]+ \|", (REPO / "docs/reports/tuning.md").read_text(), flags=re.M)
    )
    lines.append(f"\\newcommand{{\\Ktrials}}{{{n_trials}}}")
    # drift: the six largest PSIs; fairness: the flagged attribute/outcome pairs
    top = sorted(drift["rows"], key=lambda r: -r["psi"])[:6]
    lines.append(
        "\\newcommand{\\Kdrift}{"
        + ",".join(
            f"{min(r['psi'], 9.99):.2f}/{{{esc(r['feature'].replace('_', ' '))}}}/{r['status']}" for r in top
        )
        + "}"
    )
    flags = [
        (a, o, c["ratio"])
        for a, v in fair["attributes"].items()
        for o, c in v["outcomes"].items()
        if c["flagged"]
    ]
    lines.append(
        "\\newcommand{\\Kflags}{"
        + "; ".join(f"{esc(a.replace('_', ' '))}, {esc(o)}: {r:.2f}" for a, o, r in flags)
        + "}"
    )
    # the HTML deck: the same numbers, plain text, plus the chart data as JSON
    plain = {}
    for line in lines:
        m = re.match(r"\\newcommand\{\\(K\w+)\}\{(.*)\}$", line)
        if m:
            plain[m[1]] = m[2].replace("\\$", "$").replace("\\%", "%").replace("\\_", "_").replace("\\&", "&")
    data = {
        "qini": card["uplift"]["curve"],
        "qini_random": card["uplift"]["random_end"],
        "reliability": card["promise"]["reliability"],
        "importance": card["promise"]["importance"],
        "drivers": [{"label": k, "value": v} for k, v in drivers],
        "ab": [
            {
                "name": c.test_cell.replace("_", " "),
                "r": c.kept_rate * 100,
                "lo": c.kept_lo * 100,
                "hi": c.kept_hi * 100,
            }
            for c in p.ab_test
        ],
    }
    tpl = (Path(__file__).parent / "present" / "template.html").read_text()
    html = re.sub(r"\{\{(K\w+)\}\}", lambda mm: plain[mm[1]], tpl).replace("/*DATA*/{}", json.dumps(data))
    (Path(__file__).parent / "present" / "index.html").write_text(html)
    out = Path(__file__).with_name("numbers.tex")
    out.write_text(
        "% written by build_numbers.py from data/exports/reports and the warehouse: don't edit by hand\n"
        + "\n".join(lines)
        + "\n"
    )
    print(f"{len(lines)} macros -> {out}")


if __name__ == "__main__":
    main()
