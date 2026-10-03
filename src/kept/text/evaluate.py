"""Release gate for text features: F1 >= 0.80, hardship recall >= 0.90, on 300
notes labelled twice. A feature ships only if it passes."""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GateResult:
    feature: str
    f1: float
    recall: float
    precision: float
    n: int
    passed: bool
    reason: str


def binary_metrics(y_true: Sequence[bool], y_pred: Sequence[bool]) -> tuple[float, float, float]:
    """(precision, recall, f1) for the positive class. Undefined ratios (0/0) -> 0.0.
    Lengths differ or empty -> ValueError."""
    raise NotImplementedError("Track C")


def text_feature_gate(feature: str, y_true: Sequence[bool], y_pred: Sequence[bool]) -> GateResult:
    """Pass iff f1 >= 0.80; for feature == "hardship_signal" also recall >= 0.90.
    For hardship, positive = POSSIBLE or CLEAR (callers binarise)."""
    raise NotImplementedError("Track C")


def cohens_kappa(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> float:
    """Agreement between the two human labellings. Perfect agreement -> 1.0.
    Both raters constant on the same label -> 1.0. Lengths differ or empty -> ValueError."""
    raise NotImplementedError("Track C")


def adjudicate(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> list[int]:
    """Indices where the two labellings disagree (sent for a third look)."""
    raise NotImplementedError("Track C")
