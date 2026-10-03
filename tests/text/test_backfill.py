"""SetFit backfill (integration + slow: downloads a sentence-transformer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kept.contracts import HardshipSignal, RedactedText
from kept.text.backfill import SetFitBackfill

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _t(s: str) -> RedactedText:
    return RedactedText(text=s, redactor_version="test")


TRAIN = [
    (_t("lost my job last month, can't pay"), HardshipSignal.CLEAR),
    (_t("laid off, on EI now"), HardshipSignal.CLEAR),
    (_t("hours were cut, things are tight"), HardshipSignal.POSSIBLE),
    (_t("money is a bit tight this month"), HardshipSignal.POSSIBLE),
    (_t("will pay friday, forgot the due date"), HardshipSignal.NONE),
    (_t("paid online yesterday"), HardshipSignal.NONE),
] * 4


def test_validation() -> None:
    m = SetFitBackfill()
    with pytest.raises(ValueError):
        m.fit([_t("a")], [HardshipSignal.NONE, HardshipSignal.CLEAR])
    with pytest.raises(ValueError):
        m.fit([_t("a"), _t("b")], [HardshipSignal.NONE, HardshipSignal.NONE])
    with pytest.raises(RuntimeError):
        SetFitBackfill().predict([_t("a")])


def test_fit_predict_save_load(tmp_path: Path) -> None:
    pytest.importorskip("setfit")
    m = SetFitBackfill()
    m.fit([t for t, _ in TRAIN], [y for _, y in TRAIN])
    preds = m.predict([_t("got laid off and now on EI"), _t("paid online this morning")])
    assert len(preds) == 2 and all(isinstance(p, HardshipSignal) for p in preds)
    m.save(tmp_path / "m")
    assert SetFitBackfill.load(tmp_path / "m").predict([_t("paid online")]) == m.predict([_t("paid online")])


def test_extractions_rows_protect_without_quotes() -> None:
    import numpy as np

    class FakeSetFit:
        model_head = type("Head", (), {"classes_": np.array(["clear", "none", "possible"])})()

        def predict_proba(self, texts: list[str], as_numpy: bool) -> np.ndarray:
            return np.array([[0.7, 0.2, 0.1], [0.1, 0.8, 0.1]])

    m = SetFitBackfill()
    m._model = FakeSetFit()
    clear, none = m.extractions([_t("laid off"), _t("paid")], source_ids=["n1", "n2"], case_ids=["c1", "c2"])
    assert clear.extractor.startswith("setfit:") and clear.source_id == "n1"
    assert clear.hardship_signal.value is HardshipSignal.POSSIBLE  # no quote, so CLEAR -> POSSIBLE
    assert clear.hardship_signal.confidence == 0.7 and clear.hardship_signal.evidence is None
    assert none.hardship_signal.value is HardshipSignal.NONE and none.promise_intent.value is False
