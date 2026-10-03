"""Role-based access (owner: Track D, used by the app and Ask).

Agents see only their own queue with personal data masked; analysts see
aggregates of 10 or more; only compliance can read protected attributes.
"""

from __future__ import annotations

from kept.contracts.enums import ReleaseTier, Role
from kept.contracts.identity import GoldenCustomer

_CASE_ROLES = frozenset({Role.HARDSHIP_SPECIALIST, Role.TEAM_LEAD, Role.COMPLIANCE})


def can_view_case(*, role: Role, user_id: str, assigned_agent_id: str | None) -> bool:
    """AGENT: only cases assigned to them. HARDSHIP_SPECIALIST, TEAM_LEAD, COMPLIANCE: any.
    ANALYST, DATA_STEWARD, ENGINEER: no case-level view."""
    if role is Role.AGENT:
        return assigned_agent_id is not None and assigned_agent_id == user_id
    return role in _CASE_ROLES


def can_read_restricted(role: Role) -> bool:
    """Only COMPLIANCE."""
    return role is Role.COMPLIANCE


def mask_phone(e164: str | None) -> str | None:
    """'+14165550123' -> '+1 ***-***-0123'. None -> None."""
    if e164 is None:
        return None
    digits = e164.lstrip("+")
    return f"+{digits[:-10]} ***-***-{digits[-4:]}"  # ponytail: assumes 10-digit national numbers (NANP)


def mask_email(email: str | None) -> str | None:
    """'jane.doe@example.com' -> 'j***@example.com'. None -> None."""
    if email is None:
        return None
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_name(name: str | None) -> str | None:
    """'Jane Doe' -> 'Jane D.'. None -> None."""
    if name is None:
        return None
    parts = name.split()
    return name if len(parts) < 2 else f"{parts[0]} {parts[-1][0]}."


def masked_view(customer: GoldenCustomer, role: Role) -> GoldenCustomer:
    """Copy with direct PII masked for every role except COMPLIANCE."""
    if role is Role.COMPLIANCE:
        return customer
    # model_copy skips validation on purpose: a masked phone is no longer valid E.164
    return customer.model_copy(
        update={
            "display_name": mask_name(customer.display_name),
            "primary_phone_e164": mask_phone(customer.primary_phone_e164),
            "email": mask_email(customer.email),
        }
    )


def can_release(tier: ReleaseTier, *, role: Role, is_assigned_agent: bool) -> bool:
    """Who may release (design §6 tier table) - the first reviewer's permission only:
    BLOCKED: nobody (compliance override is a separate path);
    RED: HARDSHIP_SPECIALIST (a second person is checked by the release gate);
    AMBER: the assigned AGENT;
    GREEN: TEAM_LEAD (daily batch)."""
    match tier:
        case ReleaseTier.RED:
            return role is Role.HARDSHIP_SPECIALIST
        case ReleaseTier.AMBER:
            return role is Role.AGENT and is_assigned_agent
        case ReleaseTier.GREEN:
            return role is Role.TEAM_LEAD
        case _:
            return False
