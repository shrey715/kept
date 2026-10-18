# ruff: noqa: E501  (deck number formatting)
"""Write numbers.tex: every number the deck shows, read from the reports and the warehouse, as LaTeX macros.

    uv run python docs/deck/build_numbers.py && (cd docs/deck && xelatex kept.tex && xelatex kept.tex)

No number in kept.tex is typed by hand: rerun this after a report changes and the slides follow.

    uv run python docs/deck/build_numbers.py --partial

writes only the macros that come from evidence.json and the uplift_*.json study files (`study_macros`) into the committed
numbers.tex and keeps every other value, for a machine that lacks the other report JSONs (model_card, business_data,
fairness_data, drift_data, the benchmark answers, the scratch warehouse copy). Run the full build where they all exist.
"""

from __future__ import annotations

import argparse
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


def rng_txt(lo: float, hi: float, unit: str = "") -> str:  # "-7 to +8" when it spans zero, else "55–67"
    return f"{lo:+.0f}{unit} to {hi:+.0f}{unit}" if lo < 0 < hi else f"{lo:.0f}–{hi:.0f}{unit}"


def study_macros() -> dict[str, str]:
    """Macros for the off-policy claim (evidence.json) and the uplift study (uplift_*.json); each source is optional."""
    out: dict[str, str] = {}
    if (REPORTS / "evidence.json").exists():
        ev = load("evidence.json")
        g, o = ev["offpolicy_per_1000"], ev["offpolicy_old_label_per_1000"]
        out |= {
            "offPolicy": f"{g[0]:+.0f}".replace("+0", "0").replace("-0", "0"), "offPolicyCI": rng_txt(g[1], g[2]),
            "offPolicyOld": f"{o[0]:+.0f}", "offPolicyOldCI": rng_txt(o[1], o[2]),
        }  # fmt: skip
    if (REPORTS / "uplift_learners.json").exists():  # the DR-learner against the champion, scripts/uplift_learners.py
        ul = load("uplift_learners.json")
        best, ut = ul["best"], ul["test"]
        out |= {"drName": esc(best)}
        for arm, k in (("call", "Call"), ("sms_payment_link", "Sms"), ("email", "Email")):
            out |= {f"dr{k}": f"{ut[arm][best]:+.4f}", f"ch{k}": f"{ut[arm]['Champion (live)']:+.4f}"}
    if (REPORTS / "uplift_diagnostics_part2.json").exists():  # the call effect on a clean payment, contact-attempt rows
        c = next(
            r for r in load("uplift_diagnostics_part2.json")["studies"]
            if r["label"] == "contact attempts" and r["arm"] == "call" and r["outcome"].startswith("clean payment")
        )  # fmt: skip
        out |= {"callEffect": f"{100 * c['ate']:+.1f}", "callEffectCI": f"{100 * c['ate_ci'][0]:+.1f} to {100 * c['ate_ci'][1]:+.1f}"}
    if (REPORTS / "uplift_policy.json").exists():
        pol = {p["rule"]: p for p in load("uplift_policy.json")["policies"] if p["arm"] == "call"}
        for key, rule in (("tree", "tree (depth 3)"), ("live", "live model, same share"), ("every", "treat everyone")):
            p = pol[rule]
            out |= {f"{key}Gain": f"{p['gain_per_1000_decisions']:+.1f}", f"{key}GainCI": f"{p['gain_ci'][0]:+.1f} to {p['gain_ci'][1]:+.1f}"}
    if (REPORTS / "uplift_seeds.json").exists():
        q = [r["qini_call"] for r in load("uplift_seeds.json")]
        out |= {"seedLo": f"{min(q):+.4f}", "seedHi": f"{max(q):+.4f}"}
    if (REPORTS / "uplift_framings.json").exists():
        h = load("uplift_framings.json")["best_hour"]
        e, w, pl = h["comparable_calls"], h["within_customer"], h["policy"]
        out |= {
            "eveningGap": f"{100 * e['evening_minus_day_rpc']:+.1f}", "eveningGapCI": f"{100 * e['ci'][0]:+.1f} to {100 * e['ci'][1]:+.1f}",
            "eveningWithin": f"{100 * w['evening_minus_day_rpc']:+.1f}", "hourLiftStudy": f"{100 * pl['lift_hourly_capacity']:+.1f}",
        }  # fmt: skip
    if (REPORTS / "best_hour.json").exists():  # the booking replay, scripts/best_hour_replay.py: against the bank's own hours, team volume
        b = load("best_hour.json")
        tv, g = b["team_volume"], b["team_volume"]["on_minus_bank_pts"]
        out |= {
            "hourBank": f"{100 * b['as_historically_booked']['predicted_rpc']:.1f}", "hourOn": f"{100 * tv['on']['predicted_rpc']:.1f}",
            "hourGain": f"{g[0]:+.1f}", "hourGainCI": f"{g[1]:+.1f} to {g[2]:+.1f}", "hourMoved": f"{100 * tv['share_moved_from_earliest']:.0f}",
        }  # fmt: skip
    return out


def write_html(plain: dict[str, str], data: str) -> None:
    tpl = (Path(__file__).parent / "present" / "template.html").read_text()
    html = re.sub(r"\{\{(K\w+)\}\}", lambda mm: plain[mm[1]], tpl).replace("/*DATA*/{}", data)
    (Path(__file__).parent / "present" / "index.html").write_text(html)


def partial() -> None:
    """Patch the study macros into the committed numbers.tex and rebuild the HTML deck from it (chart data kept as is)."""
    out = Path(__file__).with_name("numbers.tex")
    lines = out.read_text().splitlines()
    new = study_macros()
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"\\newcommand\{\\K(\w+)\}\{", line)
        if m and m[1] in new:
            lines[i], _ = f"\\newcommand{{\\K{m[1]}}}{{{new[m[1]]}}}", done.add(m[1])
    lines += [f"\\newcommand{{\\K{k}}}{{{v}}}" for k, v in new.items() if k not in done]
    out.write_text("\n".join(lines) + "\n")
    plain = {}
    for line in lines:
        m = re.match(r"\\newcommand\{\\(K\w+)\}\{(.*)\}$", line)
        if m:
            plain[m[1]] = m[2].replace("\\$", "$").replace("\\%", "%").replace("\\_", "_").replace("\\&", "&")
    old = (Path(__file__).parent / "present" / "index.html").read_text()
    write_html(plain, re.search(r"const DATA = (\{.*\});", old)[1])  # type: ignore[index]
    print(f"{len(new)} macros patched in {out}: {sorted(new)}")


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
    ev = load("evidence.json")

    def pt(v: list[float], unit: str = "") -> str:  # "+6.1" and "2.8–10.6"
        return f"{v[0]:+.1f}{unit}"

    def iv(lo: float, hi: float) -> str:
        return f"{lo:+.1f} to {hi:+.1f}" if lo < 0 < hi else f"{lo:.1f}–{hi:.1f}"

    wide, blend = ev["auc|Kept, wide: LightGBM + random forest, averaged ranks|all"], ev["auc|Kept's wide model and the bank's score, averaged ranks|all"]
    wide_fair = ev["auc|Kept, wide: LightGBM + random forest, averaged ranks|before_due"]
    placebo = [v for k, v in ev.items() if k.startswith("placebo_")]
    sim, be = biz["simulation"], biz["breakeven_payday_pts"]
    con = duckdb.connect(str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"), read_only=True)
    per_week = con.execute(
        "select count(*) / 52.0 from silver.promises_to_pay"
        " where ptp_created_ts >= date '2025-09-28' and ptp_created_ts < date '2026-09-28'"  # the 12 months to the snapshot
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
        "bankAuc": f"{wide[0] - wide[1] / 100:.3f}",
        "wideAuc": f"{wide[0]:.3f}", "wideGap": f"{wide[1]:+.1f}", "wideGapCI": iv(*wide[2:]),
        "wideFairGap": f"{wide_fair[1]:+.1f}", "wideFairGapCI": iv(*wide_fair[2:]),
        "blendAuc": f"{blend[0]:.3f}", "blendGap": f"{blend[1]:+.1f}", "blendGapCI": iv(*blend[2:]),
        "cellAll": f"\\${ev['cell_top100'][0] / 1e3:+.0f}K", "cellTop": f"\\${ev['cell_top10'][0] / 1e3:+.0f}K",
        "pPayback": f"{100 * sim['p_payback_year1']:.2f}\\%", "pPaybackTogether": f"{100 * sim['p_payback_year1_together']:.1f}\\%",
        "breakevenLow": f"{be['low']:.1f}",
        "weeksFive": f"{weeks(ev['payday_kept'][0] / 100, 0.05):.0f}", "weeksTwenty": f"{weeks(ev['payday_kept'][0] / 100, 0.20):.0f}",
    }
    m |= study_macros()
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
    write_html(plain, json.dumps(data))
    out = Path(__file__).with_name("numbers.tex")
    out.write_text(
        "% written by build_numbers.py from data/exports/reports and the warehouse: don't edit by hand\n"
        + "\n".join(lines)
        + "\n"
    )
    print(f"{len(lines)} macros -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--partial", action="store_true", help="only the evidence/uplift-study macros, rest from numbers.tex")
    partial() if ap.parse_args().partial else main()
