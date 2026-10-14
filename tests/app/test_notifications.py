"""The bell: notifications are views of audit events for one person, and read state only moves forward."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.demo import demo_services
from kept.app.notifications import ReadState, build
from kept.contracts import AuditEvent, AuditKind, Role

T0 = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def _ev(n: int, kind: AuditKind, actor: str = "tl-1", **payload: object) -> AuditEvent:
    return AuditEvent(
        event_id=f"E{n}", at=T0 + timedelta(minutes=n), kind=kind, actor_id=actor, payload=payload
    )


def test_an_agent_hears_about_their_own_cases_only_and_never_their_own_actions() -> None:
    events = [
        _ev(1, AuditKind.RELEASE, released=True, case_id="C-1", action="call", tier="amber"),
        _ev(2, AuditKind.RELEASE, released=True, case_id="C-9", action="call", tier="amber"),  # not theirs
        _ev(3, AuditKind.RELEASE, actor="agent-7", released=True, case_id="C-1"),  # their own release
        _ev(
            4,
            AuditKind.RELEASE,
            actor="customer:self-serve",
            source="customer",
            case_id="C-1",
            installments=3,
            amount="140.00",
            due_date="2026-10-17",
        ),
    ]
    feed = build(events, user_id="agent-7", role=Role.AGENT, my_cases={"C-1"}, waiting={})
    assert [n.id for n in feed] == ["E4", "E1"]  # newest first
    assert feed[0].severity == "success" and "3 × $140.00" in feed[0].body and feed[0].href == "/cases/C-1"


def test_a_new_count_waiting_is_a_new_notification() -> None:
    one = build(
        [], user_id="hs-1", role=Role.HARDSHIP_SPECIALIST, my_cases=None, waiting={"specialist": (2, T0)}
    )
    two = build(
        [], user_id="hs-1", role=Role.HARDSHIP_SPECIALIST, my_cases=None, waiting={"specialist": (3, T0)}
    )
    assert one[0].title.startswith("2 Red") and one[0].id != two[0].id and one[0].href == "/approvals"


def test_a_first_approval_notifies_the_second_person_roles_only() -> None:
    e = [_ev(1, AuditKind.RELEASE, actor="hs-1", released=False, status="approved", case_id="C-1")]
    assert build(e, user_id="tl-1", role=Role.TEAM_LEAD, my_cases=None, waiting={})[0].severity == "action"
    assert build(e, user_id="x", role=Role.HARDSHIP_SPECIALIST, my_cases=None, waiting={}) == []


def test_read_state_never_moves_backwards() -> None:
    reads = ReadState()
    reads.mark("u", T0 + timedelta(hours=1))
    reads.mark("u", T0)  # an older tab
    assert reads.get("u") == T0 + timedelta(hours=1) and reads.get("nobody") is None


def test_route_counts_unread_until_marked_read() -> None:
    services = demo_services()
    services.audit_log.append(
        _ev(1, AuditKind.OVERRIDE, actor="agent-7", case_id="C-1", override_reason="spoke to her")
    )
    client = TestClient(create_app(services))
    q = {"user_id": "c-1", "role": "compliance"}
    feed = client.get("/notifications", params=q).json()
    assert feed["unread"] >= 1 and feed["items"][0]["title"] == "Override on C-1"
    assert (
        client.post(
            "/notifications/read", json={"user_id": "c-1", "upto": feed["items"][0]["at"]}
        ).status_code
        == 200
    )
    assert client.get("/notifications", params=q).json()["unread"] == 0
