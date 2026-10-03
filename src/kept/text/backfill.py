"""SetFit classifier trained on LLM labels; fills in the 1.5M historical notes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kept.contracts.enums import HardshipSignal
from kept.contracts.features import ExtractedValue, RedactedText, StatedReason, TextExtraction
from kept.text.extract import FIELDS

MODEL_VERSION = "setfit-v1"  # bump when the base model or the training labels change

# SetFit only predicts hardship_signal; every other field gets its "nothing found" value.
_NOTHING: dict[str, Any] = {
    "stated_reason": StatedReason.NONE,
    "promise_intent": False,
    "promised_date": None,
    "promised_amount": None,
    "dispute": False,
    "cease_request": False,
    "third_party_present": False,
}
assert set(_NOTHING) == set(FIELDS) - {"hardship_signal"}


class SetFitBackfill:
    # ponytail: English-only base (the one cached on C's machine); notes are EN + FR, try a
    # multilingual base if French recall falls short on the held-out labels.
    def __init__(self, *, base_model: str = "BAAI/bge-small-en-v1.5") -> None:
        self.base_model = base_model
        self._model: Any = None

    def fit(self, texts: Sequence[RedactedText], labels: Sequence[HardshipSignal]) -> None:
        """Lengths differ or fewer than 2 classes -> ValueError."""
        if len(texts) != len(labels):
            raise ValueError(f"{len(texts)} texts but {len(labels)} labels")
        if len(set(labels)) < 2:
            raise ValueError("need at least 2 classes to train")
        from datasets import Dataset  # type: ignore[import-untyped]
        from setfit import SetFitModel, Trainer, TrainingArguments

        model = SetFitModel.from_pretrained(self.base_model)
        data = Dataset.from_dict({"text": [t.text for t in texts], "label": [str(y) for y in labels]})
        # 20 pairs per example (SetFit's classic setting): the default uses every unique pair,
        # 145K pairs from 518 labels, millions from 2,000. Long transcripts capped at 256 tokens.
        args = TrainingArguments(
            num_epochs=1,
            num_iterations=20,
            batch_size=32,
            max_length=256,
            show_progress_bar=False,
            report_to="none",
            save_strategy="no",
        )
        Trainer(model=model, args=args, train_dataset=data).train()
        self._model = model

    def predict(self, texts: Sequence[RedactedText]) -> list[HardshipSignal]:
        """Not fitted -> RuntimeError."""
        return [signal for signal, _ in self._predict(texts)]

    def extractions(
        self, texts: Sequence[RedactedText], *, source_ids: Sequence[str], case_ids: Sequence[str]
    ) -> list[TextExtraction]:
        """text.extractions rows for the backfill. SetFit has no quote, and CLEAR needs one
        (as in LLMExtractor), so CLEAR becomes POSSIBLE: an unquoted hardship still protects."""
        if not len(texts) == len(source_ids) == len(case_ids):
            raise ValueError("texts, source_ids and case_ids must have the same length")
        now = datetime.now(UTC)
        nothing = {f: ExtractedValue[Any](value=v, confidence=0.0) for f, v in _NOTHING.items()}
        return [
            TextExtraction(
                source_id=source_id,
                case_id=case_id,
                hardship_signal=ExtractedValue(
                    value=HardshipSignal.POSSIBLE if signal is HardshipSignal.CLEAR else signal,
                    confidence=confidence,
                ),
                **nothing,
                extractor=f"setfit:{MODEL_VERSION}",
                extracted_at=now,
            )
            for (signal, confidence), source_id, case_id in zip(
                self._predict(texts), source_ids, case_ids, strict=True
            )
        ]

    def _predict(self, texts: Sequence[RedactedText]) -> list[tuple[HardshipSignal, float]]:
        if self._model is None:
            raise RuntimeError("SetFitBackfill is not fitted; call fit() or load()")
        if not texts:
            return []
        proba = self._model.predict_proba([t.text for t in texts], as_numpy=True)
        classes = self._model.model_head.classes_
        return [(HardshipSignal(classes[row.argmax()]), float(row.max())) for row in proba]

    def save(self, path: Path) -> None:
        if self._model is None:
            raise RuntimeError("SetFitBackfill is not fitted; nothing to save")
        self._model.save_pretrained(str(path))

    @classmethod
    def load(cls, path: Path) -> SetFitBackfill:
        from setfit import SetFitModel

        m = cls(base_model=str(path))
        m._model = SetFitModel.from_pretrained(str(path))
        return m
