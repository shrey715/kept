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
