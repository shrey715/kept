# ruff: noqa: E501  (deck number formatting)
"""Write numbers.tex: every number the deck shows, read from the reports and the warehouse, as LaTeX macros.

    uv run python docs/deck/build_numbers.py && (cd docs/deck && xelatex kept.tex && xelatex kept.tex)

No number in kept.tex is typed by hand: rerun this after a report changes and the slides follow.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import duckdb

from kept.app.portfolio import overview

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("KEPT_DATA_DIR", REPO / "data"))  # a git worktree has no data/: point at the checkout's
REPORTS = DATA / "exports" / "reports"


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
    p = overview(duckdb.connect(str(DATA / "warehouse" / "scratch_copy.duckdb"), read_only=True))
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
    con = duckdb.connect(str(DATA / "warehouse" / "scratch_copy.duckdb"), read_only=True)
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
    # the decision evidence (docs/reports/decisions.md): data/exports/reports/decision_<id>.json
    d = {i: load(f"decision_{i}.json") for i in ("A1", "A2", "A3", "A5", "B1", "B3", "B4", "B5", "B6", "B7", "B9", "B10", "C2")}
    A1 = d["A1"]

    def a1(engine: str, wl: str, scale: int) -> str:  # seconds, or why there is no number
        r = [r for r in A1["runs"] if (r["engine"], r["workload"], r["scale"]) == (engine, wl, scale)]
        return "skipped (disk)" if not r else f"{r[0]['median_s']:.1f} s" if r[0]["status"] == "ok" else "out of memory"

    def a1row(label: str, wl: str, scale: int) -> str:
        return f"{label} {scale}x & " + " & ".join(a1(e, wl, scale) for e in ("duckdb", "polars", "postgres", "spark")) + r" \\"

    rr = {s: a1("duckdb", "roll_rate", s).split()[0] for s in (10, 40)}
    ws = A1["duckdb_working_set"]["roll_rate"]
    rep, ctl, clk, tz = d["A2"]["replay"], d["A3"]["control_right_as_of"], d["A3"]["clock_snapshot_date_instead_of_as_of"], d["A3"]["timezone_utc_hour_instead_of_local"]
    sc, bq = d["B4"]["scenarios"]["base"], d["B4"]["quota"]
    b5, ac, sp = d["B5"]["settings"], d["B7"]["accuracy"], d["B7"]["speed_s_per_1000"]
    hrs, b9 = d["B7"]["hours_to_label_all_760594"], d["B9"]["models"]
    b10 = d["B10"]["test"]["total"]["models"]
    bd, c2, b6 = d["B10"]["paired_bootstrap_top30_live_vs_response"]["diff"], d["C2"]["systems"], d["B6"]["embedders"]["BAAI/bge-m3"]["configs"]
    pc = lambda x: f"{100 * x:.1f}\\%"  # noqa: E731
    b1, b3, a5 = d["B1"], d["B3"], d["A5"]["redteam_live"]
    m |= {  # B1: which model; B3: llama.cpp against Ollama; A5: the live red team
        **{f"decBone{k}{what}": v for k, name in (("Live", "live"), ("Fourteen", "qwen3-14b"), ("Eight", "qwen3-8b"), ("Gemma", "gemma3-12b"))
           for what, v in (("Vram", f"{b1[name]['vram']['peak_mib']:,}"), ("Right", str(b1[name]["asks"]["all"]["right"])),
                           ("Conf", str(b1[name]["asks"]["all"]["wrong_but_confident"])), ("Median", f"{b1[name]['asks']['all']['median_s']:g}"),
                           ("Notes", f"{b1[name]['extract']['notes']['fields']['hardship_signal']['f1']:g}" if name != "live" else f"{b1['live']['extract_from_doc']['Hardship']['notes_f1']:g}"),
                           ("Briefs", f"{b1[name]['briefs']['median_s']:g}" if "briefs" in b1[name] else "not run"))},
        "decBoneOf": str(b1["live"]["asks"]["all"]["graded"]),
        "decBthreeCtx": f"{b3['ollama_default']['context']['openai_endpoint']['prompt_tokens_reported']:,}", "decBthreeSent": f"{b3['llamacpp']['context']['prompt_tokens_sent']:,}",
        "decBthreeLlama": f"{b3['llamacpp']['throughput']['parallel_1']['tps_median']:g}", "decBthreeMatched": f"{b3['ollama_matched']['throughput']['parallel_1']['tps_median']:g}",
        "decBthreeLlamaSec": f"{b3['llamacpp']['extraction']['seconds']}", "decBthreeMatchedSec": f"{b3['ollama_matched']['extraction']['seconds']}",
        "decAfiveRefused": str(a5["refused"]), "decAfiveAttacks": str(a5["n_attacks"]), "decAfiveAnswered": str(len(a5["answered_or_clarified"])),
    }
    m |= {
        "decAoneRollTen": rr[10], "decAoneRollForty": rr[40], "decAoneSparkTen": a1("spark", "roll_rate", 10).split()[0],
        "decAoneMaxScale": f"{max(r['scale'] for r in A1['runs'] if r['engine'] == 'duckdb')}",
        "decAoneLimitScale": f"{ws['scale_at_24gb_extrapolated']:.0f}",
        "decAoneRows": " ".join([a1row("roll\\_rate", "roll_rate", 1), a1row("roll\\_rate", "roll_rate", 10),
                                 a1row("silver build", "silver_contact_history", 1), a1row("silver build", "silver_contact_history", 10)]),
        "decAtwoShare": pc(rep["share_changed_by_end_of_day"]), "decAtwoCards": f"{rep['cards_changed_by_end_of_day']:,}",
        "decAtwoOpen": f"{rep['cases_open_at_nightly']:,}", "decAtwoUncovered": pc(rep["changed_without_note_not_covered"] / rep["cases_open_at_nightly"]),
        "decAthreeClock": f"{clk['parity_sample']['cells_mismatched']:,}", "decAthreeZone": f"{tz['parity_sample']['cells_mismatched']:,}",
        "decAthreeControl": f"{ctl['parity_sample']['cells_mismatched']}", "decAthreeCells": f"{ctl['parity_sample']['cells']:,}",
        "decAthreeActions": f"{clk['cards_best_action_changed']:,}", "decAthreeFeastMs": f"{d['A3']['timing']['feast_online_ms_per_case']}",
        "decBfourLocal": f"{sc['local_usd_year']:,}", "decBfourHaiku": f"{sc['hosted_usd_year']['Claude Haiku 5.5 (prompt up to 100k)']:,}",
        "decBfourFlash": f"{sc['hosted_usd_year']['Gemini 3.5 Flash-Lite']:,}", "decBfourGpus": str(sc["local_gpus"]),
        "decBfourQuotaDays": f"{bq['quota_days_for_one_night']:.1f}", "decBfourNight": f"{bq['extractions_per_night_base']:,.0f}",
        "decBfivePlain": f"{b5['plain']['all']['right']}", "decBfiveRoute": f"{b5['route']['all']['right']}",
        "decBfiveLive": f"{b5['live']['all']['right']}", "decBfiveOf": f"{b5['live']['all']['graded']}",
        "decBfivePlainPct": pc(b5["plain"]["all"]["accuracy"]), "decBfiveRoutePct": pc(b5["route"]["all"]["accuracy"]),
        "decBfiveLivePct": pc(b5["live"]["all"]["accuracy"]),
        "decBfiveConfPlain": str(b5["plain"]["all"]["wrong_but_confident"]), "decBfiveConfLive": str(b5["live"]["all"]["wrong_but_confident"]), "decBfiveConfRoute": str(b5["route"]["all"]["wrong_but_confident"]),
        "decBfiveGainDrafts": str(b5["live"]["all"]["right"] - b5["templates"]["all"]["right"]),
        "decBsixDense": f"{b6['dense']['all']['mrr']:.3f}", "decBsixHybrid": f"{b6['hybrid']['all']['mrr']:.3f}",
        "decBsixDenseFr": f"{b6['dense']['fr']['mrr']:.3f}", "decBsixHybridFr": f"{b6['hybrid']['fr']['mrr']:.3f}",
        "decBsevenRules": f"{ac['keywords']['hardship']['f1']:.2f}", "decBsevenSetfit": f"{ac['setfit']['hardship']['f1']:.2f}",
        "decBsevenLlm": f"{ac['llm']['hardship']['f1']:.2f}", "decBsevenRulesRecall": f"{ac['keywords']['hardship']['recall']:.2f}",
        "decBsevenSetfitRecall": f"{ac['setfit']['hardship']['recall']:.2f}", "decBsevenLlmRecall": f"{ac['llm']['hardship']['recall']:.2f}",
        "decBsevenRulesPromise": f"{ac['keywords']['promise']['f1']:.2f}", "decBsevenLlmPromise": f"{ac['llm']['promise']['f1']:.2f}",
        "decBsevenRulesHours": f"{hrs['keywords']:.3f}", "decBsevenSetfitHours": f"{hrs['setfit_gpu']:.3f}",
        "decBsevenLlmHours": f"{hrs['llm_extrapolated']:,.0f}", "decBsevenLlmDays": f"{hrs['llm_days_extrapolated']:.0f}",
        "decBsevenSetfitSec": f"{d['B7']['parts']['setfit_all_notes']['seconds']:.0f}",
        "decBsevenRatio": f"{round(sp['llm_2_slots'] / sp['setfit_gpu'], -3):,.0f}",
        "decBnineSix": f"{b9['6-feature LightGBM, no calibration (as \u00a78)']['auc']:.3f}",
        "decBnineBank": f"{d['B9']['bank_auc']:.3f}",
        "decBtenResponse": f"{b10['Response model']['qini_noise_units']:.1f}", "decBtenT": f"{b10['T-learner (live settings)']['qini_noise_units']:.1f}",
        "decBtenChamp": f"{b10['Champion (live)']['qini_noise_units']:.1f}", "decBtenS": f"{b10['S-learner, larger trees']['qini_noise_units']:.1f}",
        "decBtenForest": f"{b10['Causal forest, larger leaves']['qini_noise_units']:.1f}", "decBtenBank": f"{b10[BANK]['qini_noise_units']:.1f}".replace("-", "−"),
        "decBtenTopT": f"{b10['T-learner (live settings)']['per_1000_top30']:.0f}", "decBtenTopResp": f"{b10['Response model']['per_1000_top30']:.0f}",
        "decBtenTopS": f"{b10['S-learner, larger trees']['per_1000_top30']:.0f}", "decBtenTopForest": f"{b10['Causal forest, larger leaves']['per_1000_top30']:.0f}",
        "decBtenDiff": f"{bd[0]:.0f} to {bd[1]:.0f}",
        "decBtenAloneT": pc(b10["T-learner (live settings)"]["p_pay_if_left_top30"]).replace(".0", ""),
        "decBtenAloneResp": pc(b10["Response model"]["p_pay_if_left_top30"]).replace(".0", ""),
        "decCtwoRule": f"{c2['rule_noei']['recall']:.3f}", "decCtwoModel": f"{c2['lgbm_noei_same_flag_rate']['recall']:.3f}",
        "decCtwoModelEi": f"{c2['lgbm_ei_same_flag_rate']['recall']:.3f}",
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
