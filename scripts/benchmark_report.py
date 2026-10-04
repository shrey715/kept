# ruff: noqa: E501  (report prose)
"""Benchmark report: docs/reports/benchmark_report.pdf, from one `kept benchmark` run.

    uv run kept benchmark --out data/benchmark/answers.csv --scorecard data/exports/reports/scorecard.md
    uv run python scripts/benchmark_report.py --answers data/benchmark/answers.csv --scorecard data/exports/reports/scorecard.md

Reads the answers CSV (the submission format) and the scorecard `kept benchmark` writes; nothing is re-asked.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from reportlib import AQUA, BLUE, GRID, KEPT, MUTED, ORANGE, REPO, build_pdf, plt, save, style, tidy


def path_of(row: dict[str, str]) -> str:
    if row["refused"] == "true":
        return "refused"
    src = row["sql_or_sources"]
    if src.lstrip().upper().startswith(("SELECT", "WITH")):
        return "SQL"
    if "transcript" in src:
        return "calls"
    return "documents"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", type=Path, default=REPO / "data" / "benchmark" / "answers.csv")
    ap.add_argument("--scorecard", type=Path, default=REPO / "data" / "exports" / "reports" / "scorecard.md")
    ap.add_argument("--questions", type=Path, default=REPO / "data" / "benchmark" / "benchmark_questions.csv")
    a = ap.parse_args()
    with a.answers.open(encoding="utf-8") as f:
        answers = {r["question_id"]: r for r in csv.DictReader(f)}
    with a.questions.open(encoding="utf-8") as f:
        qs = {r["question_id"]: r for r in csv.DictReader(f)}
    card = a.scorecard.read_text()
    headline = next(line for line in card.splitlines() if line.startswith("Dev split:"))
    graded = {
        m[1]: m[3]
        for m in re.finditer(r"^\| (BQ-\d+) \| [^|]+ \| (answer|refuse) \| [^|]+ \| ([^|]*) \|", card, re.M)
    }
    expect = {m[1]: m[2] for m in re.finditer(r"^\| (BQ-\d+) \| [^|]+ \| (answer|refuse) \|", card, re.M)}

    style()
    # 1. status grid, one square per question
    ids = sorted(answers)
    color, label = {}, {}
    for q in ids:
        ans = answers[q]
        if q in expect:
            ok = (expect[q] == "refuse" and ans["refused"] == "true") or graded.get(q, "").strip() == "yes"
            color[q] = BLUE if ok else KEPT
            label[q] = "dev: right" if ok else "dev: wrong"
        else:
            color[q] = AQUA if ans["refused"] == "false" else ORANGE
            label[q] = "test: answered" if ans["refused"] == "false" else "test: refused"
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    for i, q in enumerate(ids):
        x, y = i % 12, -(i // 12)
        ax.add_patch(plt.Rectangle((x, y), 0.92, 0.92, color=color[q]))
        ax.text(
            x + 0.46,
            y + 0.46,
            q.removeprefix("BQ-"),
            ha="center",
            va="center",
            fontsize=7,
            color="white",
            fontweight="bold",
        )
    ax.set_xlim(-0.1, 12)
    ax.set_ylim(-(len(ids) // 12) - 0.1, 1)
    ax.axis("off")
    for c, t in (
        (BLUE, "dev, correct"),
        (KEPT, "dev, wrong"),
        (AQUA, "hidden test, answered"),
        (ORANGE, "hidden test, refused"),
    ):
        ax.scatter([], [], marker="s", color=c, label=t)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=4, frameon=False, fontsize=7.5)
    ax.set_title("All questions at a glance", loc="left")
    grid_fig = save(fig, "b_grid")

    # 2. answer paths
    paths = Counter(path_of(answers[q]) for q in ids)
    order = ["SQL", "documents", "calls", "refused"]
    fig, ax = plt.subplots(figsize=(7.2, 1.4))
    left = 0
    for p, c in zip(order, (BLUE, AQUA, ORANGE, MUTED), strict=True):
        ax.barh(0, paths[p], left=left, color=c, height=0.5, edgecolor="white", linewidth=2)
        if paths[p]:
            ax.text(
                left + paths[p] / 2,
                0,
                f"{p}\n{paths[p]}",
                ha="center",
                va="center",
                fontsize=7.5,
                color="white",
                fontweight="bold",
            )
        left += paths[p]
    ax.set_xlim(0, len(ids))
    ax.axis("off")
    ax.set_title("How each question got answered", loc="left")
    paths_fig = save(fig, "b_paths")

    # 3. dev by type
    types = Counter()
    good = Counter()
    for q, e in expect.items():
        t = (
            "should refuse"
            if e == "refuse"
            else ("metric" if qs[q]["metric_id"] else "lookup / policy / call")
        )
        types[t] += 1
        good[t] += label[q] == "dev: right"
    fig, ax = plt.subplots(figsize=(7.2, 1.6))
    ts = list(types)
    y = list(range(len(ts)))[::-1]
    ax.barh(y, [types[t] for t in ts], color=GRID, height=0.5)
    ax.barh(y, [good[t] for t in ts], color=BLUE, height=0.5)
    for yi, t in zip(y, ts, strict=True):
        ax.text(types[t] + 0.2, yi, f"{good[t]}/{types[t]}", va="center", fontsize=8)
    ax.set_yticks(y, ts)
    ax.set_xlabel("dev questions (blue = right)")
    ax.set_title("Dev split by kind of question", loc="left")
    tidy(ax)
    dev_fig = save(fig, "b_dev")

    rows = "\n".join(
        f"| {q} | {qs[q]['split']} | {qs[q]['question_text'][:70].replace('|', '/')} | {path_of(answers[q])} | {label[q]} |"
        for q in ids
    )
    md = f"""---
title: "Collections Ask: benchmark report"
subtitle: "{len(ids)} released questions, one run, no hand edits"
author: "Team Sharpe Shooters"
date: "{datetime.now(UTC):%d %B %Y}"
---

# TL;DR

{headline.replace("Dev split:", "**Dev split:**")}

The organisers score the hidden test split; here we can only show what the Ask did with it. Every refusal is on a
question that asks for a protected attribute, bulk personal data or something outside the data.

![]({grid_fig}){{ width=100% }}

# How the Ask gets there

A question climbs down a ladder and stops at the first step that can answer it:

1. **Rules** refuse protected attributes, bulk personal data, write actions and other people's cases, *before* any LLM.
2. **Certified metrics and SQL templates**: reviewed SQL for the 15 official metrics plus our templates (charge-offs in a
   window, 30-day cure rate, calls outside permitted hours). The LLM only picks one and fills filters, groups and dates.
3. **Dates are worked out in code** ("the 12 months to 28 Sep 2026" → 2025-09-29..2026-09-28), never by the model.
4. **Free SQL** only when nothing above fits: three drafts, the answer at least two agree on wins, with our own worked
   examples and table context in the prompt, then a guard (SELECT only, 17 tables, no personal columns, row limit, 10 s).
5. **Policy, incident and call questions** go to document search or the call's redacted transcript, with the source cited.
6. **Grounding:** every number in the sentence has to be in the result rows, or the sentence is dropped.

![]({paths_fig}){{ width=100% }}

![]({dev_fig}){{ width=100% }}

# Every question

| ID | Split | Question | Path | Result |
|---|---|---|---|---|
{rows}

*Rebuild:* run `kept benchmark` with `--out` and `--scorecard`, then `scripts/benchmark_report.py` on those files.
"""
    print(build_pdf(md, "benchmark_report"))


if __name__ == "__main__":
    main()
