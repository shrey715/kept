"""Kept: a guarded next best action for promises customers can keep.

Package layout follows the four layers of the system design
(docs/design/SharpeShooters_SystemDesign.pdf):

    kept.contracts   shared, fixed API between tracks (change only by team agreement)
    kept.config      every threshold the design commits to, in one place
    kept.common      LLM gateway, audit log, DuckDB connection
    kept.data        Layer 1  Data Product Factory           (Track A)
    kept.ask         Layer 2  Collections Ask                (Track B)
    kept.text        Layer 3  text features                  (Track C)
    kept.hardship    hardship signal combination             (Track C)
    kept.governance  fairness, protected-attribute lineage   (Track C) / access (Track D)
    kept.features    Layer 3  feature store                  (Track D, parity: Track A)
    kept.nba         Layer 4  models and decisioning         (Track D)
    kept.app         FastAPI service for the cards           (Track D, routes per owner)
"""

__version__ = "0.1.0"
