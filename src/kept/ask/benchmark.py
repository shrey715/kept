"""Scorecard on the provided benchmark questions. Rerun on every prompt change."""

from __future__ import annotations

from dataclasses import dataclass

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
    should_refuse as true/false text). Duplicate question_id -> ValueError."""
    raise NotImplementedError("Track B")


def parse_tolerance(tolerance: str | None) -> tuple[float, str] | None:
    """ "±0.1 pts" -> (0.1, "pts"); "±2%" -> (2.0, "%"); "exact" or None -> None."""
    raise NotImplementedError("Track B")


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
    raise NotImplementedError("Track B")


__all__ = [
    "ASK_ACCURACY_TARGET",
    "ASK_REFUSAL_RECALL_TARGET",
    "BenchmarkCase",
    "BenchmarkOutcome",
    "Scorecard",
    "load_benchmark",
    "parse_tolerance",
    "score",
]
