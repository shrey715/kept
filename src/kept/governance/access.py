"""Role-based access (owner: Track D, used by the app and Ask).

Agents see only their own queue with personal data masked; analysts see
aggregates of 10 or more; only compliance can read protected attributes.
"""

from __future__ import annotations

from kept.contracts.enums import ReleaseTier, Role
from kept.contracts.identity import GoldenCustomer


def can_view_case(*, role: Role, user_id: str, assigned_agent_id: str | None) -> bool:
    """AGENT: only cases assigned to them. HARDSHIP_SPECIALIST, TEAM_LEAD, COMPLIANCE: any.
    ANALYST, DATA_STEWARD, ENGINEER: no case-level view."""
    raise NotImplementedError("Track D")


def can_read_restricted(role: Role) -> bool:
    """Only COMPLIANCE."""
    raise NotImplementedError("Track D")


def mask_phone(e164: str | None) -> str | None:
    """'+14165550123' -> '+1 ***-***-0123'. None -> None."""
    raise NotImplementedError("Track D")


def mask_email(email: str | None) -> str | None:
    """'jane.doe@example.com' -> 'j***@example.com'. None -> None."""
    raise NotImplementedError("Track D")


def mask_name(name: str | None) -> str | None:
    """'Jane Doe' -> 'Jane D.'. None -> None."""
    raise NotImplementedError("Track D")


def masked_view(customer: GoldenCustomer, role: Role) -> GoldenCustomer:
    """Copy with direct PII masked for every role except COMPLIANCE."""
    raise NotImplementedError("Track D")


def can_release(tier: ReleaseTier, *, role: Role, is_assigned_agent: bool) -> bool:
    """Who may release (design §6 tier table) - the first reviewer's permission only:
    BLOCKED: nobody (compliance override is a separate path);
    RED: HARDSHIP_SPECIALIST (a second person is checked by the release gate);
    AMBER: the assigned AGENT;
    GREEN: TEAM_LEAD (daily batch)."""
    raise NotImplementedError("Track D")
