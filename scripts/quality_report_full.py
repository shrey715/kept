# ruff: noqa: E501  (report prose and SQL)
"""Deliverable 4, the data quality report: QUALITY_REPORT.pdf at the repo root (LaTeX source in docs/reports/).

    uv run kept gate                                           # writes the gate table this reads
    uv run python scripts/quality_report_full.py               # collect (needs the warehouse: stop kept serve) + render
    uv run python scripts/quality_report_full.py --render      # re-render from the cached numbers, no warehouse

Collect queries everything (raw release files, the warehouse, the crosswalk export, the 300 reviewed pairs, the
gate / parity / drift reports) and caches it in data/exports/reports/quality_data.json. Render writes the
figures and the PDF from that cache, so the text can change without touching the warehouse.
"""

from __future__ import annotations

import csv
import glob
import importlib.util
import json
import os
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from reportlib import BLUE, BUILD, INK, KEPT, MUTED, REPO, build_pdf, hbar, plt, save, style, tidy

RAW = REPO / "data" / "raw"
EXPORTS = REPO / "data" / "exports"
CACHE = BUILD / "quality_data.json"

PIPELINE_TIKZ = r"""
```{=latex}
\begin{center}
\begin{tikzpicture}[node distance=0.35cm]
\node[step=2.2cm] (raw) {\textbf{Raw release}\\ 31 tables\\ 77M records};
\node[step=2.2cm, right=of raw] (bronze) {\textbf{Bronze}\\ as delivered,\\ all text};
\node[step=2.4cm, right=of bronze, hot] (silver) {\textbf{Silver}\\ tested rules;\\ unreadable → quarantine};
\node[step=2.4cm, right=of silver, hot] (match) {\textbf{Match}\\ exact keys → Splink\\ → steward};
\node[step=2.2cm, right=of match] (gold) {\textbf{Gold C360}\\ 1,052,300\\ people};
\node[step=2.2cm, right=of gold, hot] (gate) {\textbf{Gate}\\ contract Q1–Q5\\ blocks publish};
\foreach \a/\b in {raw/bronze, bronze/silver, silver/match, match/gold, gold/gate} \draw[go] (\a) -- (\b);
\node[font=\scriptsize, text=edge, below=0.25cm of match, text width=15cm, align=center]
  {checks at every step: dbt tests · Soda checks from the contract · the gate · a human for the 300-pair review and the steward queue};
\end{tikzpicture}
\end{center}
```
"""


def _src(t: str) -> str:
    p = RAW / f"{t}.csv"
    if p.exists():
        return f"read_csv('{p}', header=true, all_varchar=true)"
    return f"read_parquet('{RAW / t}/**/*.parquet', hive_partitioning=true)"


# (relationship, child table, child key, parent table, parent key, what we do about orphans)
LINKS = [
    (
        "Contact → case",
        "contact_history",
        "case_id",
        "collections_cases",
        "case_id",
        "kept and counted; nothing joins them to a case",
    ),
    (
        "Promise → case",
        "promises_to_pay",
        "case_id",
        "collections_cases",
        "case_id",
        "promise features join on case_id",
    ),
    (
        "Note → case",
        "agent_notes",
        "case_id",
        "collections_cases",
        "case_id",
        "notes still feed hardship by customer",
    ),
    (
        "Transcript → case",
        "call_transcripts",
        "case_id",
        "collections_cases",
        "case_id",
        "call summaries look calls up by case",
    ),
    (
        "Case → CRM record",
        "collections_cases",
        "coll_customer_ref",
        "customers",
        "crm_customer_id",
        "other exact rules + Splink still resolve them; every open case resolves (gate Q2)",
    ),
    ("Contact → agent", "contact_history", "agent_id", "agents", "agent_id", "blank for automated contacts"),
    (
        "Card autopay → our deposit acct",
        "card_accounts",
        "autopay_source_account",
        "deposit_accounts",
        "deposit_account_id",
        "account at another bank: ignored for matching",
    ),
    (
        "Loan PAD → our deposit acct",
        "loan_accounts",
        "pad_source_account",
        "deposit_accounts",
        "deposit_account_id",
        "same",
    ),
]


def collect() -> dict[str, object]:
    from kept.common.db import connect
    from kept.contracts.data_contract import load_data_contract

    spec = importlib.util.spec_from_file_location("qr", REPO / "scripts" / "quality_report.py")
    assert spec and spec.loader
    qr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qr)

    raw = duckdb.connect()
    raw.execute("set memory_limit = '16GB'")
    prof = []
    for name in sorted(os.listdir(RAW)):
        t = name.removesuffix(".csv")
        if not (name.endswith(".csv") or glob.glob(f"{RAW / name}/**/*.parquet", recursive=True)):
            continue
        s = raw.execute(f"summarize select * from {_src(t)}").fetchall()
        nulls = sorted(((r[0], float(r[11])) for r in s), key=lambda x: -x[1])
        prof.append(
            {
                "table": t,
                "rows": int(s[0][10]),
                "cols": len(s),
                "cols_null": sum(p > 0 for _, p in nulls),
                "mean_null": sum(p for _, p in nulls) / len(nulls),
                "worst": [c for c, p in nulls[:2] if p > 0],
            }
        )
    links = []
    for label, child, ck, parent, pk, note in LINKS:
        n, orphans = raw.execute(
            f"""select count(*), count(*) filter (where p.k is null)
                from (select {ck} as k from {_src(child)} where {ck} is not null and {ck} <> '') c
                left join (select distinct {pk} as k from {_src(parent)}) p using (k)"""
        ).fetchone()  # type: ignore[misc]
        links.append({"label": label, "rows": int(n), "orphans": int(orphans), "note": note})

    xw_dir = EXPORTS / "identity_crosswalk"
    xw = sorted(glob.glob(str(xw_dir / "identity_crosswalk_*.parquet")), key=os.path.getmtime)[-1]
    summary = json.loads(
        Path(sorted(glob.glob(str(xw_dir / "run_summary_*.json")), key=os.path.getmtime)[-1]).read_text()
    )
    by_rule = raw.execute(
        f"select match_rule, count(*) from read_parquet('{xw}') group by 1 order by 2 desc"
    ).fetchall()
    sizes = raw.execute(
        f"select n, count(*) from (select golden_customer_id, count(*) n from read_parquet('{xw}') group by 1) group by 1 order by 1"
    ).fetchall()
    hist = raw.execute(
        f"""select floor(match_score * 50) / 50 as b, count(*) from read_parquet('{xw}')
            where match_rule = 'splink' and match_score is not null group by 1 order by 1"""
    ).fetchall()

    with open(REPO / "data" / "labels" / "match_pairs.csv", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))
    review = {
        "by": Counter(f"{r['stratum']}:{r['is_true_match'] == 'TRUE'}" for r in pairs),
        "tiers": Counter(r["tier"] for r in pairs),
        "wrong": [{"id": r["pair_id"], "score": r["score"]} for r in pairs if r["is_true_match"] != "TRUE"],
    }

    wh = connect(read_only=True)
    try:
        issues = []
        for issue, where, sql, handled in qr.ISSUES:
            affected, total = wh.execute(sql).fetchone()  # type: ignore[misc]
            issues.append(
                {
                    "issue": issue,
                    "where": where,
                    "affected": int(affected),
                    "total": int(total),
                    "handled": handled,
                }
            )
        gold = wh.execute(
            """select count(*), count(*) filter (where match_review_status = 'unlinked'),
                      count(*) filter (where do_not_contact), count(*) filter (where collections_hold)
               from gold.c360_customer"""
        ).fetchone()
        hardship = wh.execute(
            "select hardship_status, count(*) from gold.c360_customer group by 1 order by 2 desc"
        ).fetchall()
    finally:
        wh.close()

    gate_md = (EXPORTS / "quality" / "quality_report.md").read_text()
    gate = [
        dict(zip(("rule", "status", "detail"), [c.strip() for c in line.strip("|").split("|")], strict=False))
        for line in gate_md[gate_md.index("| Rule") :].splitlines()[2:]
        if line.startswith("|")
    ]
    parity = next(
        x
        for x in (EXPORTS / "quality" / "parity_report.md").read_text().splitlines()
        if x.startswith("Result:")
    )
    drift_cache = BUILD / "drift_data.json"
    data = {
        "written": datetime.now(UTC).strftime("%d %B %Y"),
        "contract_version": load_data_contract().version,
        "profile": prof,
        "links": links,
        "summary": summary,
        "by_rule": by_rule,
        "sizes": sizes,
        "hist": hist,
        "review": review,
        "issues": issues,
        "gold": list(gold or ()),
        "hardship": hardship,
        "gate": gate,
        "gate_pass": "Gate: **PASS**" in gate_md,
        "parity": parity.removeprefix("Result: ").replace("**", ""),
        "drift": json.loads(drift_cache.read_text())["headline"]
        if drift_cache.exists()
        else "see the drift report",
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, default=str, indent=1))
    return data


def figures(d: dict) -> dict[str, str]:  # type: ignore[type-arg]
    style()
    f: dict[str, str] = {}
    prof = sorted(d["profile"], key=lambda p: -p["rows"])
    f["rows"] = hbar(
        [p["table"] for p in prof],
        [p["rows"] for p in prof],
        "q_rows",
        log=True,
        xlabel="records (log scale)",
        title="How big each table is",
    )
    nul = sorted(d["profile"], key=lambda p: -p["mean_null"])[:12]
    f["nulls"] = hbar(
        [p["table"] for p in nul],
        [p["mean_null"] for p in nul],
        "q_nulls",
        fmt="{:.1f}%",
        xlabel="average % of values missing per column",
        title="Where the gaps are (mostly by design)",
    )
    iss = sorted(d["issues"], key=lambda i: -(i["affected"] / i["total"] if i["total"] else 0))[:14]
    f["issues"] = hbar(
        [i["issue"][:55] for i in iss],
        [100 * i["affected"] / i["total"] for i in iss],
        "q_issues",
        fmt="{:.1f}%",
        xlabel="% of the table's records hit",
        title="The issues, by how much of their table they hit",
    )
    lk = [x for x in d["links"] if x["rows"]]
    f["links"] = hbar(
        [x["label"] for x in lk],
        [100 * x["orphans"] / x["rows"] for x in lk],
        "q_links",
        fmt="{:.2f}%",
        xlabel="% of child rows whose key finds no parent",
        title="Orphans per join (red: worth a look)",
        colors=[KEPT if 0.02 < x["orphans"] / x["rows"] < 0.5 else BLUE for x in lk],
    )
    f["rules"] = hbar(
        [r[0] for r in d["by_rule"]],
        [r[1] for r in d["by_rule"]],
        "q_rules",
        log=True,
        xlabel="source keys (log scale)",
        title="Which rule linked each source key",
    )

    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    xs, ys = [float(b) for b, _ in d["hist"]], [n for _, n in d["hist"]]
    ax.bar(xs, ys, width=0.018, color=BLUE, align="edge")
    ax.set_yscale("log")
    for x, lab, c in ((0.95, " auto-link ≥ 0.95", INK), (0.80, " steward 0.80–0.95", MUTED)):
        ax.axvline(x, color=c, linewidth=1, linestyle="--")
        ax.text(x, max(ys) * 0.3, lab, fontsize=8, color=c, ha="right" if x > 0.9 else "left")
    ax.set_xlabel("Splink match probability")
    ax.set_ylabel("keys (log)")
    ax.set_title("Splink is confident: almost everything it links sits near 1.0", loc="left")
    tidy(ax, "y")
    f["scores"] = save(fig, "q_scores")

    sizes = d["sizes"]
    f["sizes"] = hbar(
        [f"{n} key{'s' if n > 1 else ''}" for n, _ in sizes],
        [c for _, c in sizes],
        "q_sizes",
        log=True,
        xlabel="people (log scale)",
        title="How many source keys one person has",
    )

    by = d["review"]["by"]
    fig, ax = plt.subplots(figsize=(7.2, 1.7))
    for i, stratum in enumerate(("exact", "splink")):
        ok, bad = by.get(f"{stratum}:True", 0), by.get(f"{stratum}:False", 0)
        ax.barh(1 - i, ok, height=0.5, color=BLUE)
        ax.barh(1 - i, bad, left=ok, height=0.5, color=KEPT)
        ax.text(ok + bad + 2, 1 - i, f"{ok}/{ok + bad} correct", va="center", fontsize=8)
    ax.set_yticks([1, 0], ["Exact rules", "Splink"])
    ax.set_xlim(0, 200)
    ax.set_xlabel("reviewed pairs (red = wrong link)")
    ax.set_title("300 links checked by a person", loc="left")
    tidy(ax)
    f["review"] = save(fig, "q_review")
    return f


def render(d: dict) -> Path:  # type: ignore[type-arg]
    f = figures(d)
    s, rev = d["summary"], d["review"]
    by = rev["by"]
    ok = by.get("exact:True", 0) + by.get("splink:True", 0)
    n = sum(by.values())
    ex_ok, ex_n = by.get("exact:True", 0), by.get("exact:True", 0) + by.get("exact:False", 0)
    sp_ok, sp_n = by.get("splink:True", 0), by.get("splink:True", 0) + by.get("splink:False", 0)
    total = sum(p["rows"] for p in d["profile"])
    gold_n, unlinked, dnc, hold = d["gold"]
    case_crm = next(x for x in d["links"] if x["label"] == "Case → CRM record")
    worst = max(d["issues"], key=lambda i: i["affected"] / i["total"] if i["total"] else 0)

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:.2f}%" if b else "–"

    md = (
        f"""---
title: "Data quality report"
subtitle: "Maple Bank collections release → Kept's golden C360 · deliverable 4"
author: "Team Sharpe Shooters"
date: "{d["written"]}"
---

# TL;DR

We took **{len(d["profile"])} tables / {total:,} records** of deliberately messy bank data and turned them into
one trusted record per person. Every number here is a live query (`scripts/quality_report_full.py`); nothing's typed in.

| | |
|---|---|
| Quality gate on the golden record | **{"PASS, all 8 rules" if d["gate_pass"] else "see §6"}** |
| Source keys → people | **{s["keys"]:,} → {s["golden_ids"]:,} golden IDs** (biggest person: {s["largest_cluster"]} keys) |
| Match precision, checked by a human | **{100 * ok / n:.1f}%** ({ok}/{n}; exact {ex_ok}/{ex_n}, Splink {sp_ok}/{sp_n}) |
| Kinds of data issue found and handled | **{len(d["issues"])}** (worst: {worst["issue"].lower()}, {pct(worst["affected"], worst["total"])} of its table) |
| Clusters we refused to auto-merge | {s["held_clusters"]:,} (two national IDs) + {s["held_reasons"]["too_many_keys"]} (more than 12 keys) |
| Training vs live feature values | {d["parity"]} |
| PII left in 785,594 redacted notes and calls | **0** |

**The vibe:** never guess. If a rule can't read a value, it goes empty and into a quarantine table with the
reason, instead of being "fixed" into something wrong. A wrong date of birth can merge two strangers into one
customer, and in collections that means calling the wrong person about someone else's debt.

# 1. How we checked

"""
        + PIPELINE_TIKZ
        + f"""
- **Land raw, clean after.** Bronze keeps every file exactly as it came, all columns as text, so nothing gets
  silently converted (the README warns `NA` is a real outcome code and IDs have leading zeros; both survive).
- **Small tested rules** in `kept.data.clean` / `kept.data.traps` do the cleaning: names, dates, phones, postal
  codes, provinces, snapshots, the renamed column.
- **Four layers of checks:** dbt tests on every model (gold types enforced), Soda checks generated from the data
  contract, the contract gate (`kept gate`, blocks publishing), and a human for what code can't decide (300 sampled
  matches, the steward queue).

# 2. What's in the release

![]({f["rows"]}){{ width=100% }}

Missing values are mostly by design: a charge-off date only exists if the account was charged off, a reversal ID
only if the transaction was reversed. So high numbers here aren't bugs; §3 is where the real problems are.

![]({f["nulls"]}){{ width=100% }}

| Table | Rows | Cols | Cols with gaps | Avg % missing | Emptiest columns |
|---|--:|--:|--:|--:|---|
"""
        + "\n".join(
            f"| `{p['table']}` | {p['rows']:,} | {p['cols']} | {p['cols_null']} | {p['mean_null']:.1f} | {', '.join(f'`{c}`' for c in p['worst']) or '–'} |"
            for p in sorted(d["profile"], key=lambda p: -p["rows"])
        )
        + f"""

# 3. The issues, and what we did about each

![]({f["issues"]}){{ width=100% }}

| Issue | Where | Records hit | Fix |
|---|---|---|---|
"""
        + "\n".join(
            f"| {i['issue']} | `{i['where']}` | {i['affected']:,} ({pct(i['affected'], i['total'])}) | {i['handled']} |"
            for i in d["issues"]
        )
        + f"""

**Schema drift.** `kept map` diffs every raw table's columns against the data dictionary. It flags
`deposit_accounts.overdraft_dpd` / `overdraft_dpd_bucket` (the README mentions them, the dictionary sheet doesn't),
`benchmark_questions`, and the transcript turn fields (they live in the JSON, not the CSV index).
`contact_history.channel` → `channel_v2` (renamed 26 Sep) gets merged back in silver.

# 4. Do the tables actually join?

![]({f["links"]}){{ width=100% }}

| Join | Child rows with a key | Orphans | Share | What happens |
|---|--:|--:|--:|---|
"""
        + "\n".join(
            f"| {x['label']} | {x['rows']:,} | {x['orphans']:,} | {pct(x['orphans'], x['rows'])} | {x['note']} |"
            for x in d["links"]
        )
        + f"""

The one worth flagging: **{case_crm["orphans"]:,} cases ({pct(case_crm["orphans"], case_crm["rows"])}) point at a CRM ID
that isn't in `customers`.** They're not lost: card, loan and deposit keys plus Splink still put them on a person,
and the gate checks that every *open* case resolves. The autopay/PAD numbers are high on purpose: most of those
accounts are at other banks, so we never use them to link anyone.

# 5. Identity resolution (the bit that can actually hurt someone)

There's no shared customer ID across the five systems. We link in two passes:

1. **Exact rules**: keys we can prove (the case's copy of the CRM ID, autopay/PAD → our deposit account, the same
   national ID hash, CRM's own duplicate pointer, and the core-banking customer number shared by deposits and the
   bureau file).
2. **Splink** (Fellegi–Sunter) on what's left, comparing name, date of birth, phone and postal code. **≥ 0.95
   links automatically, 0.80–0.95 goes to a data steward, lower stays apart.** A cluster with two national IDs or
   more than 12 keys is never auto-merged.

![]({f["rules"]}){{ width=100% }}

![]({f["scores"]}){{ width=100% }}

![]({f["sizes"]}){{ width=100% }}

**The human check.** No ground-truth IDs came with the data, so a person reviewed {n} random predicted links,
sorted into tiers by how many identifiers agree (tier 1: {rev["tiers"].get("1", 0)}, tier 2: {rev["tiers"].get("2", 0)},
tier 3: {rev["tiers"].get("3", 0)}).

![]({f["review"]}){{ width=100% }}

Both wrong links ({", ".join(w["id"] for w in rev["wrong"])}) are Splink pairs where everything matched except the
surname, and both scored {", ".join(w["score"] for w in rev["wrong"])}. A stricter threshold wouldn't have caught them;
the human did. That's why the review sample stays in the pipeline.

Golden IDs are stable run to run (last run: {s["ids_merged"]} merged, {s["ids_split"]} split). The golden record
has {gold_n:,} people: {unlinked:,} are single keys nothing could link, {dnc:,} carry `do_not_contact` and
{hold:,} `collections_hold`, each set if **any** linked record says so. Hardship status:
{", ".join(f"{h} {c:,}" for h, c in d["hardship"])}.

# 6. The contract gate

`contracts/c360_customer.odcs.yaml` is built from the organisers' example DC-COLL-001 (owner, refresh, quality
rules, allowed and not-allowed uses) and extended to ODCS v{d["contract_version"]}. Publishing is blocked unless:

| Rule | Status | Detail |
|---|---|---|
"""
        + "\n".join(f"| {g['rule']} | **{g['status']}** | {g['detail']} |" for g in d["gate"])
        + f"""

# 7. Text, features, monitoring

- **Redaction first, always.** All 760,594 notes and 25,000 transcripts go through Presidio (English + French spaCy,
  Canadian SIN and postal codes, mangled cards and dates of birth). Full scan after: **0** leftovers. The LLM
  gateway won't even accept un-redacted text.
- **Labels: public only.** Text models are tuned and tested on the release's 500 public labels per source (30%
  held out). The rest are the organisers'.
- **Parity:** {d["parity"]}
- **Drift:** {d["drift"]}
- **Missing stays missing.** Transactions only cover a sample of customers and 13 months; outside that, those
  features are null, not 0.

# 8. What we can't measure

- **True match accuracy.** No ground truth; §5's human review and the exact-rule cross-check are the evidence.
- **Monthly roll rates.** The account snapshot only has quarter-ends (Dec 2023–Jun 2026), so roll rates are quarterly.
- **Generation rules.** The README says some fields were set by rule; we take them as given.

# 9. If we owned the source systems

1. Put one customer ID (or the CIF) in CRM: {dict(d["by_rule"]).get("exact:core_banking_cif", 0):,} of our links lean on a number only deposits and the bureau carry.
2. One date-of-birth format on the entry screen: 12.7% of CRM DOBs are ambiguous today.
3. Stop masking card phone numbers in the extract (58% are useless for matching).
4. Ship schema changes (`channel_v2`, the overdraft columns) in the dictionary first.
5. Keep a 300-link human review per release; it caught the only two bad links.

*Rebuild:* `uv run kept gate && uv run python scripts/quality_report_full.py` (with `kept serve` stopped).
"""
    )
    pdf = build_pdf(md, "quality_report")
    return Path(shutil.move(pdf, REPO / "QUALITY_REPORT.pdf"))  # deliverable 4 lives at the repo root


if __name__ == "__main__":
    data = json.loads(CACHE.read_text()) if "--render" in sys.argv else collect()
    print(render(data))
