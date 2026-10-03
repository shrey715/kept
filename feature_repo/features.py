"""Feast definitions (Track D).

One FeatureView over the Parquet export of features.case_features (kept.features.store.export_features).
Fields come from kept.contracts.feature_registry.FEATURES, so they can't drift from it. Event
timestamps make training reads point-in-time correct; live scoring reads the same values online.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource, ValueType
from feast.types import Bool, Float64, Int64, String, UnixTimestamp

from kept.contracts.feature_registry import FEATURES

VIEW = "case_features"
PARQUET = os.environ.get(
    "KEPT_FEATURES_PARQUET",
    str(Path(__file__).resolve().parents[1] / "data" / "exports" / "features" / "case_features.parquet"),
)
# Parquet types written by export_features: decimals as doubles, dates and enums as strings.
FEAST_TYPE = {
    "int": Int64,
    "float": Float64,
    "decimal": Float64,
    "category": String,
    "bool": Bool,
    "date": String,
}

case = Entity(
    name="case",
    join_keys=["case_id"],
    value_type=ValueType.STRING,
    description="Open collections case",
)
source = FileSource(name="case_features_parquet", path=PARQUET, timestamp_field="as_of")
case_features = FeatureView(
    name=VIEW,
    entities=[case],
    ttl=timedelta(days=8),  # weekly history spine plus a day; older values read as missing
    schema=[
        Field(name="golden_customer_id", dtype=String),
        Field(name="feature_set_version", dtype=String),
        Field(
            name="as_of_value", dtype=UnixTimestamp
        ),  # as_of again: online reads don't return the event time
        *(Field(name=f.name, dtype=FEAST_TYPE[f.dtype]) for f in FEATURES),
    ],
    source=source,
    online=True,
)
