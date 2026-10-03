"""Public gold labels map onto TextExtraction fields."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from kept.contracts import HardshipSignal, StatedReason
from kept.text.labels import REASON_MAP, is_holdout, load_labels

CSV = (
    '"note_id","label_hardship","label_hardship_evidence","label_hardship_reason","label_ptp_mentioned",'
    '"label_ptp_amount","label_ptp_date","label_dispute","label_third_party_present","label_cease_request"\n'
    '"N-1","clear","position eliminated in Apr","ei_waiting","true","75","2026-10-03","false","true","false"\n'
    '"N-2","none",,,"false",,,"false","false","false"\n'
)


def test_load_labels_maps_fields(tmp_path: Path) -> None:
    p = tmp_path / "labels.csv"
    p.write_text(CSV)
    a, b = load_labels(p)
    assert a["hardship_signal"] is HardshipSignal.CLEAR and a["stated_reason"] is StatedReason.JOB_LOSS
    assert a["hardship_quote"] == "position eliminated in Apr"
    assert (a["promised_amount"], a["promised_date"]) == (Decimal("75"), date(2026, 10, 3))
    assert a["promise_intent"] and a["third_party_present"] and not a["dispute"]
    assert (
        b["stated_reason"] is StatedReason.NONE and b["promised_date"] is None and b["hardship_quote"] is None
    )


def test_every_release_reason_maps() -> None:
    release = {
        "",
        "reduced_income",
        "job_loss",
        "rate_reset",
        "separation",
        "illness",
        "disaster_evacuation",
        "disability",
        "ei_waiting",
        "other",
    }
    assert release <= REASON_MAP.keys()


def test_holdout_is_stable_and_about_30_percent() -> None:
    ids = [f"N-{i:07d}" for i in range(2000)]
    assert [is_holdout(i) for i in ids] == [is_holdout(i) for i in ids]
    assert 0.25 < sum(map(is_holdout, ids)) / len(ids) < 0.35
