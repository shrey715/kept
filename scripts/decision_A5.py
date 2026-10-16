# ruff: noqa: E501
"""A5: privacy and guard architecture, measured (docs/reports/decisions.md).

    KEPT_DATA=/path/to/data uv run python scripts/decision_A5.py redaction [--sm /path/to/en_core_web_sm]
    KEPT_DATA=/path/to/data uv run python scripts/decision_A5.py redteam         # offline layers, no LLM
    uv run python scripts/decision_A5.py redteam-live --api http://localhost:8000  # needs kept serve + LLM
    uv run python scripts/decision_A5.py chart

redaction: kept.text.redact.PresidioRedactor on a stratified sample of 2,000 agent notes (note_language x
  redaction_status) and 500 call transcripts (language x direction), plus every benchmark question (they
  carry case ids, dates and amounts, which the BQ-107 bug removed). Independent regex checks count the PII left
  behind (Luhn card and SIN numbers, phones, emails, postal codes, birth dates, the customer's own name from
  silver.customers) and the amounts, case ids and dates the redactor removed by mistake. Run once with
  en_core_web_lg (live) and once with en_core_web_sm (French stays on fr_core_news_lg).
redteam: benchmarks/redteam_questions.csv through the Ask's deterministic layers in-process, with no LLM:
  question redaction, the safety rules, the SQL guard on the attack SQL a hijacked model could write (and,
  with the guard off, what that SQL does on a read-only connection), and the grounding check on an
  adversarial narration. A question the rules pass needs the LLM scope classifier: marked for a later run.
Numbers go to $KEPT_DATA/exports/reports/decision_A5.json; the chart to docs/reports/figures/dec_A5.png.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import warnings
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Any

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # CPU only

import duckdb

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KEPT_DATA", REPO / "data"))
RAW = DATA / "raw"
OUT = DATA / "exports" / "reports" / "decision_A5.json"
EVAL_DB = DATA / "warehouse" / "eval_copy.duckdb"
REDTEAM = REPO / "benchmarks" / "redteam_questions.csv"
SEED = "a5"  # stratified sample: rows ordered by hash(id || SEED)
N_NOTES, N_TRANSCRIPTS = 2000, 500

# ---------------------------------------------------------------- independent checks
_MONTHS_EN = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_MONTHS_FULL = "january|february|march|april|june|july|august|september|october|november|december"
_MONTHS_FR = "janv|févr|fév|avr|mai|juin|juil|août|sept|déc|janvier|février|mars|avril|juillet|septembre|octobre|novembre|décembre"
_MON = rf"(?:{_MONTHS_FULL}|{_MONTHS_FR}|{_MONTHS_EN})\.?"
_YEAR_BIRTH = r"(?:19[0-9]{2}|200[0-9]|2010)"
CHECKS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"(?<![\d-])(?:\+?1[-. ]?)?\(?([2-9]\d{2})\)?[-. ]?\d{3}[-. ]?\d{4}(?![\d-])"),
    "postal_code": re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.I),
    "digits_9_luhn": re.compile(r"(?<![\d-])\d{3}[- ]?\d{3}[- ]?\d{3}(?![\d-])"),
    "digits_12_19": re.compile(r"(?<![\d.])\d{2,5}(?:[- ]\d{2,5}){2,4}(?![\d.])|(?<![\d.])\d{12,19}(?![\d.])"),
    "birth_date": re.compile(
        rf"\b{_YEAR_BIRTH}[-/]\d{{1,2}}[-/]\d{{1,2}}\b|\b\d{{1,2}}[-/]\d{{1,2}}[-/]{_YEAR_BIRTH}\b"
        rf"|\b{_MON}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+{_YEAR_BIRTH}\b|\b\d{{1,2}}(?:er)?\s+{_MON},?\s+{_YEAR_BIRTH}\b",
        re.I,
    ),
    # corrupted DOBs in synthetic notes ("DOB 151-05-28", "DOB 1975-0911"): a DOB word, then digits
    "dob_word_digits": re.compile(r"\b(?:dob|ddn|born|birth\w*|naissance|née?)\b\W{0,3}(?:on\s+|le\s+)?\d", re.I),
}
_TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}  # the bank's own lines, not personal data


def _luhn(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n > 4 else n * 2) for i, n in enumerate(reversed(nums)))
    return total % 10 == 0


def pii_hits(text: str, names: tuple[str, ...]) -> Counter[str]:
    """PII the independent checks see in `text`: one count per match, by type."""
    hits: Counter[str] = Counter()
    for kind, pat in CHECKS.items():
        for m in pat.finditer(text):
            s = m.group(0)
            if kind == "phone" and m.group(1) in _TOLL_FREE:
                continue
            if kind == "digits_9_luhn":
                if not _luhn(s):
                    continue
                kind_ = "sin_luhn"
            elif kind == "digits_12_19":
                n = sum(c.isdigit() for c in s)
                if not 12 <= n <= 19:
                    continue
                kind_ = "card_luhn" if _luhn(s) else "card_like_digits"
            else:
                kind_ = kind
            hits[kind_] += 1
    for name in names:  # the case's own customer: Titlecase or ALL CAPS, whole word
        for form in {name.title(), name.upper()}:
            hits["customer_name"] += len(re.findall(rf"(?<![\w-]){re.escape(form)}(?![\w-])", text))
    return +hits  # drop zero counts


# What redaction must keep: money, case and record ids, ordinary dates (not birth dates).
KEEP: dict[str, re.Pattern[str]] = {
    "amount": re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:[.,]\d+)?\s?\$"),
    "record_id": re.compile(r"\b(?:CS|N|G|AG|L|C|D|CT|REC|BQ|KS|KD)-\d{3,}(?:-\d{3,})?\b"),
    "date": re.compile(
        rf"\b20(?:1[5-9]|2\d)-\d{{2}}-\d{{2}}\b|\b{_MON}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+20(?:1[5-9]|2\d))?\b"
        rf"|\b\d{{1,2}}(?:st|nd|rd|th|er)?\s+{_MON}(?:\s+20(?:1[5-9]|2\d))?\b|\bthe\s+\d{{1,2}}(?:st|nd|rd|th)\b",
        re.I,
    ),
}


def lost_tokens(original: str, redacted: str) -> Counter[str]:
    """Kept-class tokens in the original that are gone from the redacted text (multiset difference)."""
    births = [m.span() for m in CHECKS["birth_date"].finditer(original)]  # PII, not a date to keep
    lost: Counter[str] = Counter()
    for kind, pat in KEEP.items():
        before = Counter(
            m.group(0) for m in pat.finditer(original) if not any(m.start() < e and s < m.end() for s, e in births)
        )
        for tok, n in before.items():
            lost[kind] += max(0, n - redacted.count(tok))
    return +lost


def _demo() -> None:
    assert pii_hits("call 416-555-0123 or 1-800-555-0199", ())["phone"] == 1
    assert pii_hits("SIN 046 454 286", ())["sin_luhn"] == 1 and not pii_hits("SIN 046 454 287", ())
    assert pii_hits("card 4520 1234 5678 9012", ())  # 16 digits: card-like either way
    assert pii_hits("DOB 1987-04-13", ())["birth_date"] == 1 and pii_hits("DOB 151-05-28", ())["dob_word_digits"]
    assert pii_hits("Sure, it's December 8, 1994.", ())["birth_date"] == 1
    assert not pii_hits("promised $470 by Jul 24 2026", ("Cassie",))
    assert pii_hits("May I speak with Cassie Martinez?", ("Cassie", "Martinez"))["customer_name"] == 2
    assert lost_tokens("PTP $180 Jun 23, CS-2026-614370", "PTP <X> Jun 23, CS-2026-614370") == Counter(amount=1)
    assert not lost_tokens("DOB 1987-04-13", "DOB <DATE_OF_BIRTH>")
    assert not lost_tokens("Sure, it's December 25, 1990.", "Sure, it's <DATE_OF_BIRTH>.")


# ---------------------------------------------------------------- sample
def _strata_alloc(sizes: dict[Any, int], total: int) -> dict[Any, int]:
    """Equal allocation across strata, capped at each stratum's size; the surplus goes to the rest."""
    alloc = dict.fromkeys(sizes, 0)
    left = total
    open_ = {k for k, n in sizes.items() if n > 0}
    while left > 0 and open_:
        share = max(1, left // len(open_))
        for k in sorted(open_, key=str):
            take = min(share, sizes[k] - alloc[k], left)
            alloc[k] += take
            left -= take
            if alloc[k] >= sizes[k]:
                open_.discard(k)
            if left == 0:
                break
    return alloc


def load_sample() -> list[dict[str, Any]]:
    notes = duckdb.sql(
        f"""select note_id as id, crm_customer_id, note_language as s1, redaction_status as s2,
        coalesce(note_text, '') as text, hash(note_id || '{SEED}') as h
        from read_csv('{RAW}/agent_notes.csv', all_varchar=true)"""
    ).df()
    calls = duckdb.sql(
        f"""select transcript_id as id, crm_customer_id, language as s1, direction as s2, file_path,
        hash(transcript_id || '{SEED}') as h from read_csv('{RAW}/call_transcripts.csv', all_varchar=true)"""
    ).df()
    rows: list[dict[str, Any]] = []
    for src, df, n in (("note", notes, N_NOTES), ("transcript", calls, N_TRANSCRIPTS)):
        sizes = df.groupby(["s1", "s2"]).size().to_dict()
        alloc = _strata_alloc(sizes, n)
        for (s1, s2), k in alloc.items():
            part = df[(df.s1 == s1) & (df.s2 == s2)].sort_values("h").head(k)
            for r in part.itertuples():
                rows.append(
                    {
                        "source": src,
                        "id": r.id,
                        "stratum": f"{s1}/{s2}",
                        "weight": sizes[(s1, s2)] / k,  # population rows this sample row stands for
                        "crm_customer_id": r.crm_customer_id,
                        "text": r.text if src == "note" else None,
                        "file_path": None if src == "note" else r.file_path,
                    }
                )
    from kept.text.extract import transcript_text

    for r in rows:
        if r["file_path"]:
            r["text"] = transcript_text(json.loads((RAW / "files" / r.pop("file_path")).read_text())["turns"])
        r.pop("file_path", None)
    qs: list[dict[str, Any]] = []
    for p in [DATA / "benchmark" / "benchmark_questions_all.csv", *sorted((REPO / "benchmarks").glob("*_questions.csv"))]:
        if p.name == REDTEAM.name:
            continue
        with p.open(encoding="utf-8", newline="") as f:
            qs += [
                {"source": "question", "id": r["question_id"], "stratum": p.stem, "weight": 1.0, "crm_customer_id": None, "text": r["question_text"]}
                for r in csv.DictReader(f)
            ]
    names = _names({r["crm_customer_id"] for r in rows if r["crm_customer_id"]})
    for r in rows + qs:
        r["names"] = names.get(r["crm_customer_id"] or "", ())
    return rows + qs


def _names(ids: set[str]) -> dict[str, tuple[str, ...]]:
    con = duckdb.connect(str(EVAL_DB), read_only=True)
    con.execute("create temp table ids(i varchar)")
    con.executemany("insert into ids values (?)", [(i,) for i in ids])
    got = con.execute(
        "select crm_customer_id, first_name, last_name, preferred_name from silver.customers join ids on i = crm_customer_id"
    ).fetchall()
    con.close()
    month = set(_MONTHS_EN.split("|")) | set(_MONTHS_FULL.split("|"))
    out: dict[str, set[str]] = {}
    for cid, *parts in got:
        for p in parts:
            for w in re.findall(r"[^\W\d_]+", p or ""):
                if len(w) >= 3 and w.lower() not in month:
                    out.setdefault(cid, set()).add(w)
    return {k: tuple(sorted(v)) for k, v in out.items()}


# ---------------------------------------------------------------- redaction run
_R: Any = None


def _init(en_model: str) -> None:
    global _R
    warnings.filterwarnings("ignore")
    from kept.text.redact import SPACY_MODELS, PresidioRedactor

    _R = PresidioRedactor(models={**SPACY_MODELS, "en": en_model})


def _redact(text: str) -> str:
    return str(_R.redact(text).text)


def run_model(texts: list[str], en_model: str, workers: int) -> tuple[dict[str, str], float]:
    distinct = list(dict.fromkeys(texts))
    t0 = time.time()
    with Pool(workers, initializer=_init, initargs=(en_model,)) as pool:
        out = dict(zip(distinct, pool.map(_redact, distinct, chunksize=16), strict=True))
    return out, time.time() - t0


def summarise(rows: list[dict[str, Any]], red: dict[str, str]) -> dict[str, Any]:
    """Per source: texts, texts with PII before/after, residual and over-redaction per 1,000 texts (sample and,
    for notes and transcripts, population-weighted by stratum), and counts by type."""
    out: dict[str, Any] = {}
    for src in ("note", "transcript", "question"):
        part = [r for r in rows if r["source"] == src]
        w_tot = sum(r["weight"] for r in part)
        agg = Counter()
        before_t, after_t, lost_t = Counter(), Counter(), Counter()
        w_after = w_lost = w_before = 0.0
        examples: list[dict[str, str]] = []
        for r in part:
            b = pii_hits(r["text"], r["names"])
            a = pii_hits(red[r["text"]], r["names"])
            lost = lost_tokens(r["text"], red[r["text"]])
            before_t.update(b)
            after_t.update(a)
            lost_t.update(lost)
            agg["texts"] += 1
            agg["texts_with_pii"] += bool(b)
            agg["texts_with_residual_pii"] += bool(a)
            agg["texts_over_redacted"] += bool(lost)
            agg["keep_tokens"] += sum(
                len(list(p.finditer(r["text"]))) for p in KEEP.values()
            )
            w_before += r["weight"] * bool(b)
            w_after += r["weight"] * bool(a)
            w_lost += r["weight"] * bool(lost)
            if (a or lost) and len(examples) < 12:
                examples.append({"id": r["id"], "residual": dict(a), "lost": dict(lost)})
        n = agg["texts"] or 1
        out[src] = {
            **agg,
            "residual_pii_per_1000": round(1000 * agg["texts_with_residual_pii"] / n, 2),
            "over_redaction_per_1000": round(1000 * agg["texts_over_redacted"] / n, 2),
            "pii_present_per_1000": round(1000 * agg["texts_with_pii"] / n, 2),
            "weighted_residual_pii_per_1000": round(1000 * w_after / w_tot, 2) if src != "question" else None,
            "weighted_over_redaction_per_1000": round(1000 * w_lost / w_tot, 2) if src != "question" else None,
            "weighted_pii_present_per_1000": round(1000 * w_before / w_tot, 2) if src != "question" else None,
            "pii_found_before_by_type": dict(before_t),
            "pii_left_after_by_type": dict(after_t),
            "keep_tokens_lost_by_type": dict(lost_t),
            "pii_items_removed_share": round(1 - sum(after_t.values()) / sum(before_t.values()), 4)
            if before_t
            else None,
            "examples_ids": examples,
        }
    return out


def redaction(args: argparse.Namespace) -> dict[str, Any]:
    rows = load_sample()
    texts = [r["text"] for r in rows]
    strata = Counter((r["source"], r["stratum"]) for r in rows)
    result: dict[str, Any] = {
        "sample": {
            "notes": N_NOTES,
            "transcripts": N_TRANSCRIPTS,
            "questions": sum(r["source"] == "question" for r in rows),
            "distinct_texts": len(set(texts)),
            "strata": {f"{s}:{k}": n for (s, k), n in sorted(strata.items())},
            "seed": SEED,
        },
        "models": {},
    }
    models = {"en_core_web_lg": "en_core_web_lg"}
    if args.sm:
        models["en_core_web_sm"] = args.sm
    for label, model in models.items():
        red, secs = run_model(texts, model, args.workers)
        result["models"][label] = {
            "seconds": round(secs, 1),
            "workers": args.workers,
            "ms_per_distinct_text_per_worker": round(1000 * secs * args.workers / len(red), 2),
            **summarise(rows, red),
        }
        print(label, json.dumps({k: v for k, v in result["models"][label].items() if k in ("seconds",)}), flush=True)
        for src in ("note", "transcript", "question"):
            m = result["models"][label][src]
            print(f"  {src}: residual/1000={m['residual_pii_per_1000']} over/1000={m['over_redaction_per_1000']} "
                  f"left={m['pii_left_after_by_type']} lost={m['keep_tokens_lost_by_type']}", flush=True)
    import spacy

    result["versions"] = {
        "spacy": spacy.__version__,
        **{m: spacy.util.get_package_version(m) for m in ("en_core_web_lg", "fr_core_news_lg")},
        "en_core_web_sm": "3.8.0" if args.sm else None,
        "redactor": __import__("kept.text.redact", fromlist=["PresidioRedactor"]).PresidioRedactor.version,
    }
    return result



# ---------------------------------------------------------------- red team
def _statements(sql: str) -> list[Any]:
    import sqlglot

    try:
        return [t for t in sqlglot.parse(sql, dialect="duckdb") if t is not None]
    except Exception:
        return []


def guard_off(con: duckdb.DuckDBPyConnection, sql: str, blocked: frozenset[str]) -> dict[str, Any]:
    """What the SQL would do with the guard off. Evaluation only: a SELECT is bound with EXPLAIN on the read-only
    copy (proves it resolves and would execute, returns nothing); anything else is parse-only, never run."""
    from sqlglot import exp

    out: list[dict[str, Any]] = []
    for st in _statements(sql):
        if isinstance(st, exp.Select | exp.SetOperation):
            idents = {i.name.lower() for i in st.find_all(exp.Identifier)}
            tables = sorted({f"{t.db}.{t.name}".lower() for t in st.find_all(exp.Table) if t.name})
            try:
                con.execute("EXPLAIN " + st.sql(dialect="duckdb").replace("data/raw/", f"{RAW}/"))
                bound, err = True, None
            except Exception as e:
                bound, err = False, str(e).splitlines()[0][:100]
            out.append({"kind": "select", "binds_and_would_run": bound, "error": err, "tables": tables,
                        "blocked_columns_touched": sorted(idents & blocked), "star": any(not isinstance(x.parent, exp.Count) for x in st.find_all(exp.Star))})
        else:
            out.append({"kind": type(st).__name__.lower(), "binds_and_would_run": None, "note": "write/DDL/session statement: parsed only, not run"})
    return {"statements": out, "would_expose": any(o["kind"] == "select" and o["binds_and_would_run"] for o in out)}


def redteam(args: argparse.Namespace) -> dict[str, Any]:
    from kept.ask.grounding import ungrounded_numbers
    from kept.ask.scope import rule_check
    from kept.ask.service import build_sql_policy
    from kept.ask.sql_guard import guard_sql
    from kept.contracts.ask import AskRequest, Role
    from kept.contracts.data_contract import load_data_contract
    from kept.text.redact import PresidioRedactor

    contract = load_data_contract()
    con = duckdb.connect(str(EVAL_DB), read_only=True)
    con.execute("SET memory_limit='2GB'; SET threads=4")
    policy = build_sql_policy(con, contract)
    redactor = PresidioRedactor()
    with REDTEAM.open(encoding="utf-8", newline="") as f:
        cases = list(csv.DictReader(f))
    rows = []
    for c in cases:
        q = str(redactor.redact(c["question_text"]).text)  # the Ask redacts before the rules run
        req = AskRequest(question=q, user_id="redteam", role=Role(c["role"]),
                         own_case_ids=frozenset({"CS-2026-000001"}) if c["role"] == "agent" else frozenset())
        rule = rule_check(req, contract)
        guard = guard_sql(c["attack_sql"], policy) if c["attack_sql"] else None
        narr = c["attack_narrative"]
        grounded_block = None
        if narr:
            grounded_block = bool(ungrounded_numbers(narr, [(41.2,)], allow=frozenset()))
        first = ("rules" if rule else "guard" if guard and not guard.allowed else "grounding" if grounded_block else None)
        rows.append({
            "id": c["question_id"], "category": c["category"], "role": c["role"], "expected_layer": c["expected_layer"],
            "expected_outcome": c["expected_outcome"],
            "rules_block": rule.reason.value if rule and rule.reason else None,
            "guard_block": None if guard is None else (not guard.allowed),
            "guard_reason": None if guard is None or guard.allowed else guard.reason,
            "grounding_block": grounded_block,
            "first_offline_layer": first,
            "needs_llm_scope": first is None,
            "guard_off": guard_off(con, c["attack_sql"], policy.blocked_columns) if c["attack_sql"] else None,
        })
    con.close()
    attacks = [r for r in rows if r["expected_outcome"] == "refuse"]
    n = len(attacks)
    by_cat: dict[str, Counter[str]] = {}
    for r in attacks:
        by_cat.setdefault(r["category"], Counter())[r["first_offline_layer"] or "needs_llm_scope"] += 1
    sql_attacks = [r for r in attacks if r["guard_block"] is not None]
    off = [r for r in sql_attacks if r["guard_off"]["would_expose"]]
    summary = {
        "n_questions": len(rows), "n_attacks": n, "n_harmless": len(rows) - n,
        "stopped_by_rules": sum(r["rules_block"] is not None for r in attacks),
        "stopped_by_guard_alone": sum(bool(r["guard_block"]) for r in sql_attacks), "n_attack_sql": len(sql_attacks),
        "stopped_by_grounding": sum(bool(r["grounding_block"]) for r in attacks),
        "stopped_offline_any_layer": sum(r["first_offline_layer"] is not None for r in attacks),
        "left_for_llm_scope": [r["id"] for r in attacks if r["first_offline_layer"] is None],
        "first_layer_counts_by_category": {k: dict(v) for k, v in sorted(by_cat.items())},
        "guard_off_selects_that_would_run": len(off),
        "guard_off_selects_touching_blocked_columns": sum(bool(o["blocked_columns_touched"]) for r in sql_attacks for o in (r["guard_off"] or {}).get("statements", []) if o["kind"] == "select") ,
        "guard_off_non_select_statements_parse_only": sum(o["kind"] != "select" for r in sql_attacks for o in r["guard_off"]["statements"]),
        "expected_layer_matches_first_offline": sum(
            r["first_offline_layer"] == r["expected_layer"] for r in attacks if r["expected_layer"] in ("rules", "guard", "grounding")),
        "n_expected_rules_guard_grounding": sum(r["expected_layer"] in ("rules", "guard", "grounding") for r in attacks),
    }
    harmless = [{"id": r["id"], "guard_block": r["guard_block"], "guard_off": r["guard_off"]} for r in rows if r["expected_outcome"] != "refuse"]
    return {"summary": summary, "harmless": harmless, "rows": rows,
            "live": "pending: run `decision_A5.py redteam-live` when the GPU and the LLM are free"}


def redteam_live(args: argparse.Namespace) -> dict[str, Any]:
    """Every red-team question through POST /bench/question (role team_lead; the agent-role rows only exist offline).
    Records, per question, whether the Ask refused and which rung and reason. Needs `kept serve` and the local LLM."""
    from bench_run import ask

    with REDTEAM.open(encoding="utf-8", newline="") as f:
        cases = [c for c in csv.DictReader(f) if c["role"] != "agent"]
    out = []
    for c in cases:
        gold = {"gold_answer": "Refuse: red-team question"} if c["expected_outcome"] == "refuse" else None
        r = ask(args.api, {"question_id": c["question_id"], "question_text": c["question_text"]}, gold)
        resp = r["response"]
        out.append({"id": c["question_id"], "category": c["category"], "expected_layer": c["expected_layer"], "expected_outcome": c["expected_outcome"],
                    "kind": resp["kind"], "reason": resp.get("reason"), "rung": r["rung"], "correct": r["correct"], "ms": r["ms"]})
        print(c["question_id"], out[-1]["kind"], out[-1]["reason"], flush=True)
    atk = [o for o in out if o["expected_outcome"] == "refuse"]
    return {"n": len(out), "n_attacks": len(atk), "refused": sum(o["kind"] == "refusal" for o in atk),
            "answered_or_clarified": [o["id"] for o in atk if o["kind"] != "refusal"], "rows": out}


def chart() -> None:
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    from reportlib import BLUE, KEPT, MUTED, ORANGE, plt, save, style, tidy

    d = json.loads(OUT.read_text())
    style()
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1, 1.25]})
    labels = ["Residual PII", "Over-redaction"]
    x = range(2)
    for k, (m, col) in enumerate((("en_core_web_lg", KEPT), ("en_core_web_sm", MUTED))):
        v = [d["redaction"]["models"][m]["transcript"][f] for f in ("weighted_residual_pii_per_1000", "weighted_over_redaction_per_1000")]
        bars = a.bar([i + (k - 0.5) * 0.38 for i in x], v, 0.36, color=col, label=m)
        a.bar_label(bars, fmt="%.1f", padding=2, fontsize=9)
    a.set_xticks(list(x), labels)
    a.set_ylabel("per 1,000 call transcripts")
    a.set_title("Redaction, transcripts (notes: 0 in both)", loc="left", fontsize=11)
    a.legend(frameon=False)
    tidy(a, "y")
    cats = d["redteam"]["summary"]["first_layer_counts_by_category"]
    order = [("rules", KEPT), ("guard", BLUE), ("grounding", ORANGE), ("needs_llm_scope", MUTED)]
    left = [0] * len(cats)
    names = list(cats)
    for lay, col in order:
        vals = [cats[c].get(lay, 0) for c in names]
        b.barh(names, vals, left=left, color=col, label=lay.replace("_", " "))
        left = [a_ + v for a_, v in zip(left, vals, strict=True)]
    b.invert_yaxis()
    b.set_xlabel("attack questions, by the first layer that stops them (no LLM)")
    b.set_title("Red team: offline layers", loc="left", fontsize=11)
    b.legend(frameon=False, fontsize=8)
    tidy(b, "x")
    print(save(fig, "dec_A5"))

# ---------------------------------------------------------------- main
def write(key: str, value: Any) -> None:
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data[key] = value
    OUT.write_text(json.dumps(data, indent=2, default=str))
    print(f"wrote {OUT} [{key}]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["redaction", "redteam", "redteam-live", "chart", "demo"])
    ap.add_argument("--sm", help="path to an unpacked en_core_web_sm model (compared with en_core_web_lg)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    if args.mode == "demo":
        _demo()
        print("ok")
    elif args.mode == "redaction":
        _demo()
        write("redaction", redaction(args))
    elif args.mode == "redteam":
        write("redteam", redteam(args))
    elif args.mode == "redteam-live":
        write("redteam_live", redteam_live(args))
    else:
        chart()


if __name__ == "__main__":
    main()
