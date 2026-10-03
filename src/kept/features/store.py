"""Feast-backed FeatureProvider. Training reads values as they were at each past
decision; live scoring reads the same values from the online store."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from kept.contracts.feature_registry import FEATURES, OUTCOME_DENY_LIST, STATED_REASON_FIELDS
from kept.contracts.features import FeatureVector

_DENIED = OUTCOME_DENY_LIST | STATED_REASON_FIELDS
VIEW = "case_features"  # feature_repo/features.py
_META = ("golden_customer_id", "feature_set_version", "as_of_value")
_NAMES = tuple(f.name for f in FEATURES)
_PARQUET_TYPE = {"decimal": "double", "date": "varchar", "category": "varchar"}


def export_features(conn: duckdb.DuckDBPyConnection, out_path: Path) -> int:
    """Write features.case_features to Parquet in the types Feast reads (as_of as UTC timestamptz,
    decimals as doubles, dates and enums as strings). Returns the row count."""
    casts = ",\n".join(
        f"cast({f.name} as {_PARQUET_TYPE[f.dtype]}) as {f.name}" if f.dtype in _PARQUET_TYPE else f.name
        for f in FEATURES
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("set TimeZone = 'UTC'")  # case_features.as_of is naive UTC
    select = f"""select case_id, golden_customer_id, feature_set_version,
        cast(as_of as timestamptz) as as_of, cast(as_of as timestamptz) as as_of_value, {casts}
        from features.case_features"""
    conn.execute(f"copy ({select}) to '{out_path}' (format parquet)")
    return int(conn.sql(f"select count(*) from read_parquet('{out_path}')").fetchone()[0])  # type: ignore[index]


def _clean(v: Any) -> Any:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


class FeastFeatureProvider:
    """Implements kept.contracts.interfaces.FeatureProvider."""

    def __init__(self, repo_path: Path) -> None:
        from feast import FeatureStore

        self._store = FeatureStore(repo_path=str(repo_path))
        self._refs = [f"{VIEW}:{n}" for n in (*_META, *_NAMES)]

    def get_online(self, case_id: str) -> FeatureVector:
        """Latest materialised values. Unknown case (or one older than the view's TTL) -> KeyError."""
        d = self._store.get_online_features(features=self._refs, entity_rows=[{"case_id": case_id}]).to_dict()
        row = {k: _clean(v[0]) for k, v in d.items()}
        as_of = row.pop("as_of_value")
        if as_of is None:
            raise KeyError(case_id)
        if isinstance(as_of, (int, float)):
            as_of = datetime.fromtimestamp(as_of, UTC)
        elif as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        return FeatureVector(as_of=as_of, **{k: v for k, v in row.items() if k in FeatureVector.model_fields})

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        """Point in time: for each (case_id, as_of) the latest values with event time <= as_of.
        Returns case_id, as_of, golden_customer_id, feature_set_version and every feature, in
        input row order. Never a denied column."""
        entity = pd.DataFrame(
            {
                "case_id": entity_rows["case_id"].to_numpy(),
                "event_timestamp": pd.to_datetime(entity_rows["as_of"], utc=True).to_numpy(),
                "_row": range(len(entity_rows)),
            }
        )
        entity["event_timestamp"] = pd.to_datetime(entity["event_timestamp"], utc=True)
        refs = [r for r in self._refs if not r.endswith(":as_of_value")]
        got = self._store.get_historical_features(entity_df=entity, features=refs).to_df()
        # the file store drops rows with no earlier feature row: put them back as missing
        values = got.drop(columns=["case_id", "event_timestamp"]).set_index("_row")
        out = entity.join(values, on="_row").rename(columns={"event_timestamp": "as_of"})
        out = out[["case_id", "as_of", "golden_customer_id", "feature_set_version", *_NAMES]]
        out.index = entity_rows.index
        assert_no_denied(out)
        return out


def drop_denied(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove every column in OUTCOME_DENY_LIST and STATED_REASON_FIELDS. Never mutates input."""
    return frame.drop(columns=[c for c in frame.columns if c in _DENIED])


def assert_no_denied(frame: pd.DataFrame) -> None:
    """Raise ValueError naming the offending columns if any denied column is present."""
    bad = sorted(c for c in frame.columns if c in _DENIED)
    if bad:
        raise ValueError(f"denied columns in a model frame: {', '.join(bad)}")
