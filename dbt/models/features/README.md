# features (Track D)

Each feature in `kept.contracts.feature_registry.FEATURES` is written once here and served by
Feast (`feature_repo/`). Reference semantics and tests: `src/kept/features/definitions.py`.
Every model must carry `case_id` and an event timestamp for point-in-time joins.
