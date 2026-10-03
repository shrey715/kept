"""Runs stages 1-7 and builds the NBA card. Implements NBAEngine."""

from __future__ import annotations

from datetime import datetime

from kept.contracts.interfaces import AuditLog, CaseContextBuilder, FeatureProvider, UpliftScorer
from kept.contracts.nba import NBACard


class KeptEngine:
    def __init__(
        self,
        *,
        context: CaseContextBuilder,
        features: FeatureProvider,
        scorer: UpliftScorer,
        audit_log: AuditLog,
        kill_switch: bool = False,
    ) -> None:
        raise NotImplementedError("Track D")

    def recommend(self, case_id: str, now: datetime) -> NBACard:
        """An unknown case (KeyError from the context builder) propagates. After that it never
        raises: feature/model errors and stale features return a card with proposal None and
        no_action_reason set. Hard stops and the permission gate apply to every proposal,
        including legacy ones. Call windows lie inside customer-local calling hours.
        Hold-out cases and the kill switch return the legacy action
        (legacy.legacy_to_action(nba_recommendation_last), is_legacy_strategy True).
        The hardship banner names eligible programmes (hardship.programs), e.g.
        "HP-REDUCE v2 eligible". Logs one RECOMMENDATION audit event."""
        raise NotImplementedError("Track D")
