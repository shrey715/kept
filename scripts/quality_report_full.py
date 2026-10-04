# ruff: noqa: E501  (report prose and SQL)
"""Numbers and figures for the data quality report (deliverable 4). The report itself is hand-written LaTeX,
docs/reports/quality_report.tex, compiled to QUALITY_REPORT.pdf at the repo root by scripts/reportlib.py.

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
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from reportlib import BLUE, BUILD, KEPT, REPO, hbar, plt, save, style, tidy

RAW = REPO / "data" / "raw"
EXPORTS = REPO / "data" / "exports"
CACHE = BUILD / "quality_data.json"


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


def render(d: dict) -> dict[str, str]:  # type: ignore[type-arg]
    """Figures for docs/reports/quality_report.tex (the prose is hand-written there)."""
    return figures(d)


if __name__ == "__main__":
    data = json.loads(CACHE.read_text()) if "--render" in sys.argv else collect()
    print(render(data))  # then: uv run python scripts/reportlib.py quality_report
