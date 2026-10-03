"""Human approval -> release gate -> execute and log.

The model never sends anything itself. A proposal is a record a person approves;
the release step rechecks hard stops and consent on fresh data; approvals expire;
errors or stale data mean "no action"; a kill switch reverts to the old strategy.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from datetime import datetime

from kept.config import FEATURE_MAX_STALENESS
from kept.contracts.interfaces import AuditLog, CaseContextBuilder
from kept.contracts.nba import Proposal, ReleaseDecision, ReleaseResult


def in_holdout(golden_customer_id: str, *, salt: str, share: float = 0.05) -> bool:
    """Permanent, deterministic hold-out on the old strategy: hash(salt, id) -> [0, 1) < share.
    Same inputs always give the same answer; independent of call order."""
    digest = hashlib.sha256(f"{salt}:{golden_customer_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < share


def sample_for_batch_review(
    proposals: Sequence[Proposal], *, n: int = 20, rng: random.Random
) -> list[Proposal]:
    """Green batch: the team lead samples n cases (all of them if fewer). No duplicates."""
    return rng.sample(list(proposals), min(n, len(proposals)))


def is_stale(features_as_of: datetime, *, now: datetime) -> bool:
    """True when now - features_as_of > FEATURE_MAX_STALENESS or features_as_of is in the future."""
    return features_as_of > now or now - features_as_of > FEATURE_MAX_STALENESS


class Releaser:
    """Implements kept.contracts.interfaces.ReleaseGate."""

    def __init__(
        self, *, proposals: dict[str, Proposal], context: CaseContextBuilder, audit_log: AuditLog
    ) -> None:
        raise NotImplementedError("Track D")

    def release(self, decision: ReleaseDecision, now: datetime) -> ReleaseResult:
        """Not released (with reason) when: proposal unknown, not PENDING, expired
        (now >= expires_at), reviewer not permitted for the tier, RED without a distinct
        second reviewer, a hard stop now fires, consent/hours/cap now fail, or context
        lookup raises. Exactly one audit event (RELEASE or OVERRIDE) per call either way."""
        raise NotImplementedError("Track D")


def cancel_pending(
    case_id: str, *, reason: str, proposals: dict[str, Proposal], audit_log: AuditLog, now: datetime
) -> list[str]:
    """Payments or cease requests cancel pending proposals for the case. Returns cancelled IDs."""
    raise NotImplementedError("Track D")
