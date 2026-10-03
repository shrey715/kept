"""SetFit classifier trained on LLM labels; fills in the 1.5M historical notes."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from kept.contracts.enums import HardshipSignal
from kept.contracts.features import RedactedText


class SetFitBackfill:
    def __init__(self, *, base_model: str = "sentence-transformers/paraphrase-MiniLM-L6-v2") -> None:
        raise NotImplementedError("Track C")

    def fit(self, texts: Sequence[RedactedText], labels: Sequence[HardshipSignal]) -> None:
        """Lengths differ or fewer than 2 classes -> ValueError."""
        raise NotImplementedError("Track C")

    def predict(self, texts: Sequence[RedactedText]) -> list[HardshipSignal]:
        """Not fitted -> RuntimeError."""
        raise NotImplementedError("Track C")

    def save(self, path: Path) -> None:
        raise NotImplementedError("Track C")

    @classmethod
    def load(cls, path: Path) -> SetFitBackfill:
        raise NotImplementedError("Track C")
