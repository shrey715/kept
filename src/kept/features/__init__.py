"""Layer 3 feature store (Track D; parity test Track A).

Each feature is written once in dbt SQL (dbt/models/features) and served by Feast
(feature_repo/). definitions.py holds the reference semantics as small pure
functions: they are the test oracle the dbt SQL must agree with.
"""
