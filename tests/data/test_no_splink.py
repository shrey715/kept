"""Decision A4's evaluation switch: with Splink off the matcher links exact keys only; live code is untouched."""

import sys
from pathlib import Path

from kept.data.identity import pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from identity_injection import no_splink


def test_no_splink_patches_only_inside_the_block() -> None:
    real = pipeline.score_pairs
    with no_splink():
        assert pipeline.score_pairs is not real
        assert pipeline.score_pairs(None, exclude_pairs=None, model={}).empty
    assert pipeline.score_pairs is real
