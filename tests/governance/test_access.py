"""Role-based access and PII masking (Track D owns kept.governance.access)."""

from __future__ import annotations

import pytest

from kept.contracts import ReleaseTier, Role
from kept.governance.access import (
    can_read_restricted,
    can_release,
    can_view_case,
    mask_email,
    mask_name,
    mask_phone,
    masked_view,
)

pytestmark = pytest.mark.track_d


@pytest.mark.parametrize(
    "role,user,assigned,ok",
    [
        (Role.AGENT, "agent-7", "agent-7", True),
        (Role.AGENT, "agent-7", "agent-8", False),
        (Role.AGENT, "agent-7", None, False),
        (Role.HARDSHIP_SPECIALIST, "hs-1", "agent-8", True),
        (Role.TEAM_LEAD, "tl-1", "agent-8", True),
        (Role.COMPLIANCE, "c-1", "agent-8", True),
        (Role.ANALYST, "an-1", "agent-8", False),
        (Role.DATA_STEWARD, "ds-1", "agent-8", False),
        (Role.ENGINEER, "eng-1", "agent-8", False),
    ],
)
def test_case_visibility(role: Role, user: str, assigned: str | None, ok: bool) -> None:
    assert can_view_case(role=role, user_id=user, assigned_agent_id=assigned) is ok


@pytest.mark.parametrize("role", list(Role))
def test_only_compliance_reads_restricted(role: Role) -> None:
    assert can_read_restricted(role) is (role is Role.COMPLIANCE)


@pytest.mark.parametrize(
    "fn,raw,expected",
    [
        (mask_phone, "+14165550123", "+1 ***-***-0123"),
        (mask_email, "jane.doe@example.com", "j***@example.com"),
        (mask_name, "Jane Doe", "Jane D."),
        (mask_name, "Cher", "Cher"),
        (mask_phone, None, None),
        (mask_email, None, None),
        (mask_name, None, None),
    ],
)
def test_masking(fn, raw, expected) -> None:  # type: ignore[no-untyped-def]
    assert fn(raw) == expected


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.COMPLIANCE])
def test_masked_view_hides_pii(make_customer, role: Role) -> None:  # type: ignore[no-untyped-def]
    c = make_customer()
    m = masked_view(c, role)
    assert m.primary_phone_e164 != c.primary_phone_e164 or m.primary_phone_e164 is None
    assert "jane.doe" not in (m.email or "")
    assert m.golden_customer_id == c.golden_customer_id and m.total_overdue == c.total_overdue


def test_compliance_sees_unmasked(make_customer) -> None:  # type: ignore[no-untyped-def]
    c = make_customer()
    assert masked_view(c, Role.COMPLIANCE) == c


@pytest.mark.parametrize(
    "tier,role,assigned,ok",
    [
        (ReleaseTier.BLOCKED, Role.COMPLIANCE, False, False),
        (ReleaseTier.BLOCKED, Role.TEAM_LEAD, False, False),
        (ReleaseTier.RED, Role.HARDSHIP_SPECIALIST, False, True),
        (ReleaseTier.RED, Role.AGENT, True, False),
        (ReleaseTier.AMBER, Role.AGENT, True, True),
        (ReleaseTier.AMBER, Role.AGENT, False, False),
        (ReleaseTier.AMBER, Role.ANALYST, True, False),
        (ReleaseTier.GREEN, Role.TEAM_LEAD, False, True),
        (ReleaseTier.GREEN, Role.AGENT, True, False),
    ],
)
def test_who_can_release(tier: ReleaseTier, role: Role, assigned: bool, ok: bool) -> None:
    assert can_release(tier, role=role, is_assigned_agent=assigned) is ok
