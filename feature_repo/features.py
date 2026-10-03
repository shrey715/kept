"""Feast definitions (Track D).

One FeatureView per dbt features model; the field list must equal
kept.contracts.feature_registry.FEATURES. Event timestamps make training reads
point-in-time correct; live scoring reads the same values from the online store.

TODO(Track D): define FileSource(s) over data/exports/features/*.parquet and the
FeatureViews. Never include a column from OUTCOME_DENY_LIST.
"""

from feast import Entity, ValueType

case = Entity(
    name="case",
    join_keys=["case_id"],
    value_type=ValueType.STRING,
    description="Open collections case",
)
