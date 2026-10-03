"""Scorecard on the provided benchmark questions. Rerun on every prompt change."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass

from kept.ask.metrics import as_bool, json_array
from kept.config import ASK_ACCURACY_TARGET, ASK_REFUSAL_RECALL_TARGET


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


__all__ = [
    "ANSWER_COLUMNS",
    "ASK_ACCURACY_TARGET",
    "ASK_REFUSAL_RECALL_TARGET",
    "BenchmarkCase",
    "BenchmarkOutcome",
    "Scorecard",
    "load_benchmark",
    "parse_tolerance",
    "score",
    "write_answers",
]
