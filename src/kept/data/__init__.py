"""Layer 1: Data Product Factory (Track A).

bronze  land raw files as they arrive        (ingest.py)
silver  clean, fix data traps, quarantine    (clean.py, traps.py)
ids     exact links, then Splink             (identity/)
gold    C360 + crosswalk + restricted        (gold.py)
gate    quality rules from the contract      (quality.py)

SQL transformations live in dbt/models; the Python here is the reference
behaviour (and test oracle) plus the parts dbt can't do (Splink, steward queue).
"""
