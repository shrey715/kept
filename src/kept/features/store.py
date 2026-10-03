"""Feast-backed FeatureProvider. Training reads values as they were at each past
decision; live scoring reads the same values from the online store."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from kept.contracts.feature_registry import OUTCOME_DENY_LIST, STATED_REASON_FIELDS
from kept.contracts.features import FeatureVector

_DENIED = OUTCOME_DENY_LIST | STATED_REASON_FIELDS


class FeastFeatureProvider:
    """Implements kept.contracts.interfaces.FeatureProvider."""

    def __init__(self, repo_path: Path) -> None:
        raise NotImplementedError("Track D")

    def get_online(self, case_id: str) -> FeatureVector:
        raise NotImplementedError("Track D")

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("Track D")


def drop_denied(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove every column in OUTCOME_DENY_LIST and STATED_REASON_FIELDS. Never mutates input."""
    return frame.drop(columns=[c for c in frame.columns if c in _DENIED])


def assert_no_denied(frame: pd.DataFrame) -> None:
    """Raise ValueError naming the offending columns if any denied column is present."""
    bad = sorted(c for c in frame.columns if c in _DENIED)
    if bad:
        raise ValueError(f"denied columns in a model frame: {', '.join(bad)}")
