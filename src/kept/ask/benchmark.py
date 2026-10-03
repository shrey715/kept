"""Scorecard on the provided benchmark questions. Rerun on every prompt change."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from kept.ask.metrics import as_bool, json_array
from kept.config import ASK_ACCURACY_TARGET, ASK_REFUSAL_RECALL_TARGET
from kept.contracts.ask import AskAnswer, AskRequest, AskResponse, Refusal
from kept.contracts.enums import Role


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One row of benchmark_questions (data dictionary column names)."""

    question_id: str
    question_text: str
    question_type: str  # metric / drivers / comparison / rag_corpus / rag_customer / guardrail
    should_refuse: bool
    expected_tables: tuple[str, ...] = ()
    metric_id: str | None = None
    as_of_date: str | None = None
    refusal_reason: str | None = None
    tolerance: str | None = None  # e.g. "±0.1 pts"
    grading_rubric: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkOutcome:
    question_id: str
    refused: bool
    correct: bool | None  # None when refused


def load_benchmark(rows: list[dict[str, object]]) -> list[BenchmarkCase]:
    """Parse benchmark_questions rows (expected_tables arrives as a JSON array string,
    should_refuse as true/false text). Duplicate question_id -> ValueError.
    The released CSV only has question_id, question_text, difficulty, metric_id, as_of_date,
    tolerance, split: the other fields default (should_refuse False, type from metric_id)."""

    def opt(r: dict[str, object], k: str) -> str | None:
        v = r.get(k)
        return str(v) if v is not None and str(v).strip() and str(v).lower() != "nan" else None

    cases = [
        BenchmarkCase(
            question_id=str(r["question_id"]),
            question_text=str(r["question_text"]),
            question_type=opt(r, "question_type") or ("metric" if opt(r, "metric_id") else "unknown"),
            should_refuse=as_bool(r.get("should_refuse") or "false"),
            expected_tables=json_array(r.get("expected_tables") or ""),
            metric_id=opt(r, "metric_id"),
            as_of_date=opt(r, "as_of_date"),
            refusal_reason=opt(r, "refusal_reason"),
            tolerance=opt(r, "tolerance"),
            grading_rubric=opt(r, "grading_rubric"),
        )
        for r in rows
    ]
    if len({c.question_id for c in cases}) != len(cases):
        raise ValueError("duplicate question_id")
    return cases


def parse_tolerance(tolerance: str | None) -> tuple[float, str] | None:
    """ "±0.1 pts" -> (0.1, "pts"); "±2%" -> (2.0, "%"); "exact" or None -> None."""
    if tolerance is None or tolerance.strip().lower() in ("", "exact"):
        return None
    m = re.fullmatch(r"\s*[±+-]?\s*(\d+(?:\.\d+)?)\s*(%|[a-z]*)\s*", tolerance, re.I)
    if m is None:
        raise ValueError(f"unrecognised tolerance {tolerance!r}")
    return float(m[1]), m[2]


@dataclass(frozen=True, slots=True)
class Scorecard:
    accuracy: float  # correct / in-scope questions (a refusal of an in-scope question is wrong)
    refusal_recall: float  # refused / should-refuse questions
    refusal_precision: float  # should-refuse / refused
    n_in_scope: int
    n_should_refuse: int
    passed: bool  # accuracy >= 0.80 and refusal_recall >= 0.95
    accuracy_by_type: dict[str, float]  # per question_type (in-scope types only)


def score(cases: list[BenchmarkCase], outcomes: list[BenchmarkOutcome]) -> Scorecard:
    """Outcomes are matched to cases by question_id. Missing or duplicate outcome,
    or an outcome for an unknown question -> ValueError."""
    by_id = {o.question_id: o for o in outcomes}
    if len(by_id) != len(outcomes) or by_id.keys() != {c.question_id for c in cases}:
        raise ValueError("outcomes must match the cases one to one")

    def ratio(n: int, d: int) -> float:
        return n / d if d else 1.0  # nothing to get wrong

    in_scope = [c for c in cases if not c.should_refuse]
    must_refuse = [c for c in cases if c.should_refuse]
    right = {c.question_id: by_id[c.question_id].correct is True for c in in_scope}
    n_refused = sum(o.refused for o in outcomes)
    types = sorted({c.question_type for c in in_scope})
    accuracy = ratio(sum(right.values()), len(in_scope))
    recall = ratio(sum(by_id[c.question_id].refused for c in must_refuse), len(must_refuse))
    return Scorecard(
        accuracy=accuracy,
        refusal_recall=recall,
        refusal_precision=ratio(sum(by_id[c.question_id].refused for c in must_refuse), n_refused),
        n_in_scope=len(in_scope),
        n_should_refuse=len(must_refuse),
        passed=accuracy >= ASK_ACCURACY_TARGET and recall >= ASK_REFUSAL_RECALL_TARGET,
        accuracy_by_type={
            t: ratio(
                sum(right[c.question_id] for c in in_scope if c.question_type == t),
                sum(c.question_type == t for c in in_scope),
            )
            for t in types
        },
    )


ANSWER_COLUMNS = ("question_id", "answer", "sql_or_sources", "refused")


def write_answers(path: str, answers: Iterable[dict[str, object]]) -> None:
    """The release's submission format (labels/benchmark_answers_template.csv): one row per question.
    `refused` is written as true/false text."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ANSWER_COLUMNS)
        w.writeheader()
        for a in answers:
            w.writerow({**a, "refused": "true" if a["refused"] else "false"})


# ----------------------------------------------------------------- running and checking
# ratio columns of the certified metrics: the answer shows them as percentages, like the gold answers
_PCT = frozenset(
    {"kept_rate", "broken_rate", "cure_rate", "rpc_rate", "ptp_rate", "hardship_rate"}
    | {"delinquency_rate", "roll_rate", "payroll_delay_share"}
)


def _cell(col: str, v: object) -> object:
    if v is not None and col in _PCT:
        return round(float(v) * 100, 2)  # type: ignore[arg-type]
    return round(float(v), 4) if isinstance(v, float) else (float(v) if hasattr(v, "as_tuple") else v)  # type: ignore[arg-type]


def answer_row(question_id: str, response: AskResponse) -> dict[str, object]:
    """One row of the answers CSV for an Ask response."""
    if isinstance(response, AskAnswer):
        buf = io.StringIO()
        if response.rows:
            w = csv.writer(buf, lineterminator="\n")
            w.writerow([c + "_pct" if c in _PCT else c for c in response.columns])
            for r in response.rows[:50]:
                w.writerow([_cell(c, v) for c, v in zip(response.columns, r, strict=False)])
        text = (buf.getvalue() + response.narrative).strip()
        sources = response.sql or "; ".join(f"{c.document_id} {c.section}" for c in response.citations)
        return {"question_id": question_id, "answer": text, "sql_or_sources": sources, "refused": False}
    message = response.message if isinstance(response, Refusal) else response.question
    return {"question_id": question_id, "answer": f"Refuse: {message}", "sql_or_sources": "", "refused": True}


def apply_gold(cases: list[BenchmarkCase], gold: dict[str, dict[str, str]]) -> list[BenchmarkCase]:
    """Dev questions have gold answers; one that starts with "Refuse" is a question to refuse.
    Test-split questions keep should_refuse False: their answers are hidden, so they are not scored here."""
    return [
        replace(c, should_refuse=gold[c.question_id]["gold_answer"].startswith("Refuse"))
        if c.question_id in gold
        else c
        for c in cases
    ]


def _matches(cell: object, g: str, tol: float, pts: bool) -> bool:
    try:
        want = float(g)
    except ValueError:
        return str(cell).strip().lower() == g.strip().lower()
    try:
        got = float(cell)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    count = (
        want >= 20 and want == int(want) and "." not in g
    )  # a group size: silver and the reference differ by a few rows
    slack = max(tol, 0.02 * want) if count and tol > 0 else tol
    return abs(got - want) <= slack + 1e-9 or (pts and abs(got * 100 - want) <= tol + 1e-9)


def is_correct(case: BenchmarkCase, gold: dict[str, str], response: AskResponse) -> bool | None:
    """None when the answer can't be checked automatically (a tolerance we can't parse, or a refusal).
    Tables: every gold row must appear in the result, each gold number within the tolerance (a ratio
    also matches as a percentage). Documents: the gold sources are cited and the gold numbers are in the
    text."""
    if not isinstance(response, AskAnswer):
        return None
    sources = json.loads(gold["gold_sources"]) if gold.get("gold_sources") else []
    if sources:
        cited = {c.document_id for c in response.citations}
        figures = {str(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", gold["gold_answer"])}
        have = {str(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", response.narrative)}
        return (
            any(src.split()[0] in cited for src in sources if not src.startswith("transcript"))
            and figures <= have
        )
    try:
        parsed = parse_tolerance(case.tolerance)
    except ValueError:
        return None
    tol, unit = parsed if parsed else (0.0, "")
    want = list(csv.reader(io.StringIO(gold["gold_answer"])))[1:]
    if not want:
        return None
    return all(
        any(
            all(any(_matches(c, g, tol, unit == "pts") for c in row) for g in want_row)
            for row in response.rows
        )
        for want_row in want
    )


def run_benchmark(
    ask: Any, cases: list[BenchmarkCase], *, role: Role = Role.TEAM_LEAD, user_id: str = "benchmark"
) -> list[AskResponse]:
    """Ask every question once. clarification_round=1: there is nobody to answer a clarifying question,
    so an unsure Ask refuses. Role TEAM_LEAD sees exact counts (analysts get small groups suppressed)."""
    return [
        ask.ask(AskRequest(question=c.question_text, user_id=user_id, role=role, clarification_round=1))
        for c in cases
    ]


def scorecard_markdown(
    cases: list[BenchmarkCase], responses: list[AskResponse], gold: dict[str, dict[str, str]], card: Scorecard
) -> str:
    lines = [
        "| question | type | expected | got | correct |",
        "|---|---|---|---|---|",
    ]
    for c, r in zip(cases, responses, strict=True):
        if c.question_id not in gold:
            continue
        got = "refused" if not isinstance(r, AskAnswer) else "answered"
        ok = (
            ""
            if c.should_refuse
            else {True: "yes", False: "NO", None: "n/a"}[is_correct(c, gold[c.question_id], r)]
        )
        want = "refuse" if c.should_refuse else "answer"
        lines.append(f"| {c.question_id} | {c.question_type} | {want} | {got} | {ok} |")
    head = (
        f"Dev split: accuracy {card.accuracy:.0%} ({card.n_in_scope} in scope), "
        f"refusal recall {card.refusal_recall:.0%} ({card.n_should_refuse} to refuse), "
        f"refusal precision {card.refusal_precision:.0%}. Targets {ASK_ACCURACY_TARGET:.0%} / "
        f"{ASK_REFUSAL_RECALL_TARGET:.0%}: {'PASSED' if card.passed else 'not met'}.\n"
    )
    return head + "\n" + "\n".join(lines) + "\n"


__all__ = [
    "ANSWER_COLUMNS",
    "ASK_ACCURACY_TARGET",
    "ASK_REFUSAL_RECALL_TARGET",
    "BenchmarkCase",
    "BenchmarkOutcome",
    "Scorecard",
    "answer_row",
    "apply_gold",
    "is_correct",
    "load_benchmark",
    "parse_tolerance",
    "run_benchmark",
    "score",
    "scorecard_markdown",
    "write_answers",
]
