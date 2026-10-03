"""Splink scoring on a tiny synthetic population (integration: needs `uv sync --extra data`)."""

from __future__ import annotations

import re

import pandas as pd
import pytest

from kept.data.identity.probabilistic import MATCH_COLUMNS, build_settings, score_pairs

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
def records() -> pd.DataFrame:
    rows = [
        # same person, two systems, cosmetic differences
        ("crm", "C1", "jane doe", "1990-04-03", "+14165550123", "M5V 3L9", "h1"),
        ("loan", "L1", "jane doe", "1990-04-03", "+14165550123", "M5V 3L9", None),
        # different person who shares a postal code
        ("card", "K1", "john smith", "1971-11-30", "+16045550199", "M5V 3L9", "h2"),
    ]
    # filler so Splink can estimate u-probabilities
    rows += [
        (
            "crm",
            f"F{i}",
            f"person {i}",
            f"19{50 + i % 40}-0{1 + i % 9}-1{i % 9}",
            f"+1416555{1000 + i}",
            "K1A 0B1",
            None,
        )
        for i in range(200)
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "source_system",
            "source_key",
            "name_key",
            "dob",
            "phone_e164",
            "postal_code",
            "national_id_hash",
        ],
    )


def test_settings_never_use_protected_attributes() -> None:
    text = str(build_settings()).lower()
    for banned in (r"gender", r"\bage\b", r"language", r"national_id"):
        assert not re.search(banned, text), banned


def test_settings_compare_on_match_columns() -> None:
    text = str(build_settings())
    for col in MATCH_COLUMNS:
        assert col in text


def test_score_pairs_ranks_true_match_above_postal_coincidence(records: pd.DataFrame) -> None:
    pytest.importorskip("splink")
    out = score_pairs(records)
    assert {"left_system", "left_key", "right_system", "right_key", "rule", "score"} <= set(out.columns)
    assert out["score"].between(0, 1).all()
    assert (out["rule"] == "splink").all()

    def s(a: str, b: str) -> float:
        hit = out[((out.left_key == a) & (out.right_key == b)) | ((out.left_key == b) & (out.right_key == a))]
        return float(hit["score"].iloc[0]) if len(hit) else 0.0

    assert s("C1", "L1") >= 0.95
    assert s("C1", "K1") < 0.80


def test_score_pairs_skips_excluded(records: pd.DataFrame) -> None:
    pytest.importorskip("splink")
    exclude = pd.DataFrame(
        [{"left_system": "crm", "left_key": "C1", "right_system": "loan", "right_key": "L1"}]
    )
    out = score_pairs(records, exclude_pairs=exclude)
    assert not (
        ((out.left_key == "C1") & (out.right_key == "L1"))
        | ((out.left_key == "L1") & (out.right_key == "C1"))
    ).any()


def test_score_pairs_trained_on_sample_scores_everyone(records: pd.DataFrame) -> None:
    pytest.importorskip("splink")
    # mod 1 trains on every record with a DOB, then rebuilds the linker from the saved model
    out = score_pairs(records, train_sample_mod=1)
    hit = out[
        ((out.left_key == "C1") & (out.right_key == "L1"))
        | ((out.left_key == "L1") & (out.right_key == "C1"))
    ]
    assert len(hit) and float(hit["score"].iloc[0]) >= 0.95
