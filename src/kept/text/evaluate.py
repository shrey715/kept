"""Release gate for text features: F1 >= 0.80, hardship recall >= 0.90, on 300
notes labelled twice. A feature ships only if it passes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

from kept.config import HARDSHIP_MIN_RECALL, TEXT_FEATURE_MIN_F1


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
    _check_pair(y_true, y_pred)
    tp = sum(t and p for t, p in zip(y_true, y_pred, strict=True))
    fp = sum(p and not t for t, p in zip(y_true, y_pred, strict=True))
    fn = sum(t and not p for t, p in zip(y_true, y_pred, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0  # from counts: exact at the 0.80 boundary
    return precision, recall, f1


def text_feature_gate(feature: str, y_true: Sequence[bool], y_pred: Sequence[bool]) -> GateResult:
    """Pass iff f1 >= 0.80; for feature == "hardship_signal" also recall >= 0.90.
    For hardship, positive = POSSIBLE or CLEAR (callers binarise)."""
    precision, recall, f1 = binary_metrics(y_true, y_pred)
    fails = []
    if f1 < TEXT_FEATURE_MIN_F1:
        fails.append(f"f1 {f1:.3f} < {TEXT_FEATURE_MIN_F1}")
    if feature == "hardship_signal" and recall < HARDSHIP_MIN_RECALL:
        fails.append(f"recall {recall:.3f} < {HARDSHIP_MIN_RECALL}")
    return GateResult(
        feature=feature,
        f1=f1,
        recall=recall,
        precision=precision,
        n=len(y_true),
        passed=not fails,
        reason="; ".join(fails) or "passed",
    )


def cohens_kappa(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> float:
    """Agreement between the two human labellings. Perfect agreement -> 1.0.
    Both raters constant on the same label -> 1.0. Lengths differ or empty -> ValueError."""
    _check_pair(labels_a, labels_b)
    n = len(labels_a)
    observed = sum(a == b for a, b in zip(labels_a, labels_b, strict=True)) / n
    count_a, count_b = Counter(labels_a), Counter(labels_b)
    expected = sum(count_a[k] * count_b[k] for k in count_a) / n**2
    if expected == 1.0:  # both raters constant on the same label
        return 1.0
    return (observed - expected) / (1 - expected)


def adjudicate(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> list[int]:
    """Indices where the two labellings disagree (sent for a third look)."""
    _check_pair(labels_a, labels_b)
    return [i for i, (a, b) in enumerate(zip(labels_a, labels_b, strict=True)) if a != b]


def _check_pair(a: Sequence[object], b: Sequence[object]) -> None:
    if not a or len(a) != len(b):
        raise ValueError(f"need two non-empty sequences of equal length, got {len(a)} and {len(b)}")
