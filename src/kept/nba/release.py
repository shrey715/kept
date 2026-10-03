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

from pydantic import ValidationError

from kept.common.audit import new_event_id
from kept.config import FEATURE_MAX_STALENESS
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import ACTION_CHANNEL, HardshipStatus, ReleaseTier, ReviewDecision, Role
from kept.contracts.interfaces import AuditLog, CaseContextBuilder
from kept.contracts.nba import CaseContext, Proposal, ProposalStatus, ReleaseDecision, ReleaseResult
from kept.governance.access import can_release
from kept.nba.rules import hard_stops, hardship_override, permission_gate
from kept.nba.tiers import assign_tier

_TIER_ORDER = list(ReleaseTier)  # declaration order = precedence (BLOCKED first)
SECOND_REVIEWER_ROLES = frozenset({Role.HARDSHIP_SPECIALIST, Role.TEAM_LEAD, Role.COMPLIANCE})


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
        self._proposals = proposals
        self._context = context
        self._log = audit_log
        self._first: dict[str, tuple[str, Role]] = {}  # Red proposals approved once: who approved

    def first_approver(self, proposal_id: str) -> tuple[str, Role] | None:
        """Who gave the first approval of a Red proposal now waiting for a second person."""
        return self._first.get(proposal_id)

    def release(self, decision: ReleaseDecision, now: datetime) -> ReleaseResult:
        """Not released (with reason) when: proposal unknown, not PENDING, expired
        (now >= expires_at), reviewer not permitted for the tier, RED without a distinct
        second reviewer, a hard stop now fires, consent/hours/cap now fail, or context
        lookup raises. Exactly one audit event (RELEASE or OVERRIDE) per call either way.
        ALTERNATIVE/OVERRIDE release the reviewer's action under the stricter of the two tiers;
        EDIT must keep the amount within the sizing's spare cash; REJECT marks it REJECTED.

        Red in two steps: a permitted first reviewer without a second_reviewer_id moves the
        proposal to APPROVED (every check still runs); a later ACCEPT by a different person in
        SECOND_REVIEWER_ROLES releases it, rechecking everything on fresh data."""
        d = decision
        kind = AuditKind.OVERRIDE if d.decision is ReviewDecision.OVERRIDE else AuditKind.RELEASE
        p = self._proposals.get(d.proposal_id)
        released, reason, final = False, "", p
        first = self._first.get(d.proposal_id)
        if p is not None and p.status is ProposalStatus.APPROVED and first is not None:
            if d.reviewer_id == first[0]:
                p, reason = None, "The second approval must come from a different person."
                final = self._proposals[d.proposal_id]
            elif d.decision not in (ReviewDecision.ACCEPT, ReviewDecision.REJECT):
                p, reason = None, "The second person can only approve or reject."
                final = self._proposals[d.proposal_id]
            elif d.decision is ReviewDecision.ACCEPT:
                d = d.model_copy(
                    update={
                        "reviewer_id": first[0],
                        "reviewer_role": first[1],
                        "second_reviewer_id": decision.reviewer_id,
                        "second_reviewer_role": decision.reviewer_role,
                    }
                )
                p = p.model_copy(update={"status": ProposalStatus.PENDING})  # re-run the full gate
        if p is None:
            reason = reason or "Unknown proposal."
        elif p.status is not ProposalStatus.PENDING and not (
            p.status is ProposalStatus.APPROVED and d.decision is ReviewDecision.REJECT
        ):
            reason = f"Proposal is already {p.status.value}."
        elif now >= p.expires_at:
            final = p.model_copy(update={"status": ProposalStatus.EXPIRED})
            reason = "Approval window expired; ask for a fresh recommendation."
        elif d.decision is ReviewDecision.REJECT:
            final = p.model_copy(update={"status": ProposalStatus.REJECTED})
            reason = "Rejected by the reviewer."
        else:
            try:
                ctx = self._context.build(p.case_id, now)
            except Exception as e:  # fresh data unavailable: never release blind
                reason = f"Could not recheck the case ({type(e).__name__}); not released."
            else:
                final, reason = self._check(p, d, ctx, now)
                released = final is not None and final.status is ProposalStatus.RELEASED
                if final is not None and final.status is ProposalStatus.APPROVED:
                    self._first[p.proposal_id] = (d.reviewer_id, d.reviewer_role)
                final = final or self._proposals[p.proposal_id]
        if final is not None:
            self._proposals[final.proposal_id] = final
            if final.status is not ProposalStatus.APPROVED:
                self._first.pop(final.proposal_id, None)
        event_id = new_event_id()
        self._log.append(
            AuditEvent(
                event_id=event_id,
                at=now,
                kind=kind,
                actor_id=decision.reviewer_id,
                actor_role=decision.reviewer_role,
                subject_id=d.proposal_id,
                payload={
                    "released": released,
                    "status": final.status.value if final else None,
                    "reason": reason,
                    "decision": decision.decision.value,
                    "first_reviewer_id": d.reviewer_id if d is not decision else None,
                    "case_id": p.case_id if p else None,
                    "action": final.action.value if final else None,
                    "tier": final.tier.value if final else None,
                    "second_reviewer_id": d.second_reviewer_id,
                    "override_reason": d.override_reason,
                },
            )
        )
        return ReleaseResult(
            proposal_id=d.proposal_id,
            released=released,
            reason=reason,
            audit_event_id=event_id,
            executed_at=now if released else None,
        )

    def _check(
        self, p: Proposal, d: ReleaseDecision, ctx: CaseContext, now: datetime
    ) -> tuple[Proposal | None, str]:
        """(updated proposal or None, reason). Status RELEASED only when every check passes."""
        action = d.alternative_action or p.action
        protective = (
            HardshipStatus.POSSIBLE
            if ctx.vulnerable and ctx.hardship_status is HardshipStatus.NONE
            else ctx.hardship_status
        )
        tier = min(
            p.tier,
            assign_tier(action=action, hard_stopped=False, hardship_status=protective),
            key=_TIER_ORDER.index,
        )
        if not can_release(
            tier, role=d.reviewer_role, is_assigned_agent=d.reviewer_id == ctx.assigned_agent_id
        ):
            return None, f"A {d.reviewer_role.value} can't release a {tier.value}-tier proposal."
        second = d.second_reviewer_id is not None and d.second_reviewer_role is not None
        if tier is ReleaseTier.RED and second and d.second_reviewer_role not in SECOND_REVIEWER_ROLES:
            return None, "The second person must be a hardship specialist, team lead or compliance."
        stop = hard_stops(ctx)
        if stop.blocked:
            return None, stop.rule_card or "Hard stop."
        if action not in hardship_override(ctx, [action]):
            return None, "Hardship or vulnerability now applies: only protective actions can be released."
        gate = permission_gate(ctx.model_copy(update={"now": now}), action)
        if not gate.allowed:
            return None, "; ".join(f"{c.check.value}: {c.detail}" for c in gate.checks if not c.passed)
        sizing = p.sizing
        if d.decision is ReviewDecision.EDIT:
            if sizing is None:
                return None, "Nothing to edit: this proposal has no amount or date."
            try:
                sizing = sizing.model_validate(
                    {
                        **sizing.model_dump(),
                        "amount": d.edited_amount or sizing.amount,
                        "due_date": d.edited_due_date or sizing.due_date,
                    }
                )
            except ValidationError:
                return None, "Edited amount must stay within the estimated spare cash."
        waiting = tier is ReleaseTier.RED and not second
        updated = p.model_copy(
            update={
                "action": action,
                "channel": ACTION_CHANNEL[action],
                "tier": tier,
                "sizing": sizing,
                "status": ProposalStatus.APPROVED if waiting else ProposalStatus.RELEASED,
            }
        )
        if waiting:
            return (
                updated,
                f"Approved by {d.reviewer_id}; waiting for a second person (team lead or compliance).",
            )
        return updated, f"Released ({tier.value} tier) by {d.reviewer_id}" + (
            f" and {d.second_reviewer_id}." if d.second_reviewer_id else "."
        )


def cancel_pending(
    case_id: str, *, reason: str, proposals: dict[str, Proposal], audit_log: AuditLog, now: datetime
) -> list[str]:
    """Payments or cease requests cancel pending proposals for the case. Returns cancelled IDs."""
    out = []
    for pid, p in list(proposals.items()):
        if p.case_id == case_id and p.status is ProposalStatus.PENDING:
            proposals[pid] = p.model_copy(update={"status": ProposalStatus.CANCELLED})
            audit_log.append(
                AuditEvent(
                    event_id=new_event_id(),
                    at=now,
                    kind=AuditKind.PROPOSAL_CANCELLED,
                    actor_id="system:release",
                    subject_id=pid,
                    payload={"case_id": case_id, "reason": reason},
                )
            )
            out.append(pid)
    return out
