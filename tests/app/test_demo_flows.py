"""The product flows over HTTP, on the demo services (real engine and release gate)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.demo import demo_services

pytestmark = pytest.mark.track_d
CASE = "CS-2026-118204"  # agent-7, plain Amber call


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(demo_services()))


def who(user: str, role: str) -> dict[str, str]:
    return {"user_id": user, "role": role}


def decide(
    client: TestClient, pid: str, user: str, role: str, decision: str = "accept", **kw: Any
) -> dict[str, Any]:
    now = client.get("/health").json()["now"]
    body = {
        "proposal_id": pid,
        "reviewer_id": user,
        "reviewer_role": role,
        "decision": decision,
        "decided_at": now,
        **kw,
    }
    r = client.post(f"/proposals/{pid}/decision", json=body)
    assert r.status_code == 200
    return r.json()  # type: ignore[no-any-return]


def test_health_reports_demo_clock(client: TestClient) -> None:
    h = client.get("/health").json()
    assert h["demo"] is True and datetime.fromisoformat(h["now"]).tzinfo is not None


def test_agent_queue_is_own_cases_ranked_and_masked(client: TestClient) -> None:
    q = client.get("/queue", params=who("agent-7", "agent")).json()
    assert q and all(i["display_name"] is None or i["display_name"].endswith(".") for i in q)  # "Jane D."
    ev = [float(i["expected_value"]) for i in q if i["action"]]
    assert ev == sorted(ev, reverse=True)
    assert all(i["action"] for i in q[: len(ev)]) and not any(
        i["action"] for i in q[len(ev) :]
    )  # no-action last
    assert {i["case_id"] for i in q}.isdisjoint({"CS-2026-803311", "CS-2026-904518"})  # agent-8's


def test_team_lead_sees_every_case_analyst_none(client: TestClient) -> None:
    assert len(client.get("/queue", params=who("tl-1", "team_lead")).json()) == 12
    assert client.get("/queue", params=who("an-1", "analyst")).status_code == 403


def test_customer_masked_for_agent_not_compliance(client: TestClient) -> None:
    agent = client.get(f"/cases/{CASE}/customer", params=who("agent-7", "agent")).json()
    comp = client.get(f"/cases/{CASE}/customer", params=who("c-1", "compliance")).json()
    assert agent["display_name"] == "Jane D." and comp["display_name"] == "Jane Doe"
    assert "*" in agent["email"] and len(agent["source_keys"]) == 4


def test_note_flips_hardship_and_the_red_handoff_releases(client: TestClient) -> None:
    card = client.post(
        f"/demo/cases/{CASE}/notes",
        json={"text": "customer lost shifts at the plant", **who("agent-7", "agent")},
    ).json()
    p = card["proposal"]
    assert card["hardship_banner"] and p["tier"] == "red"
    assert not decide(client, p["proposal_id"], "agent-7", "agent")["released"]  # agents can't release Red
    first = decide(client, p["proposal_id"], "hs-1", "hardship_specialist")
    assert not first["released"] and "waiting" in first["reason"]
    inbox = client.get("/approvals", params=who("tl-1", "team_lead")).json()
    item = next(a for a in inbox if a["proposal"]["proposal_id"] == p["proposal_id"])
    assert item["stage"] == "second_person" and item["first_approver"] == "hs-1"
    assert decide(client, p["proposal_id"], "tl-1", "team_lead")["released"]
    kinds = [
        e["kind"] for e in client.get("/audit", params={"case_id": CASE, **who("c-1", "compliance")}).json()
    ]
    assert kinds[:3] == ["release", "release", "release"] and "hardship_change" in kinds


def test_amber_released_by_assigned_agent_and_queue_shows_it(client: TestClient) -> None:
    p = client.get(f"/cases/{CASE}/nba", params=who("agent-7", "agent")).json()["proposal"]
    assert decide(client, p["proposal_id"], "agent-7", "agent")["released"]
    q = {i["case_id"]: i for i in client.get("/queue", params=who("agent-7", "agent")).json()}
    assert q[CASE]["proposal_status"] == "released"


def test_audit_access(client: TestClient) -> None:
    assert client.get("/audit", params=who("agent-7", "agent")).status_code == 403  # whole log
    assert client.get("/audit", params={"case_id": CASE, **who("agent-8", "agent")}).status_code == 403
    assert client.get("/audit", params=who("c-1", "compliance")).status_code == 200


def test_demo_ask_refuses_protected_attributes(client: TestClient) -> None:
    r = client.post("/ask", json={"question": "kept rate by gender", **who("an-1", "analyst")}).json()
    assert r["kind"] == "refusal" and r["reason"] == "protected_attribute"


def test_notes_only_in_demo(make_customer) -> None:  # type: ignore[no-untyped-def]
    from kept.app.api import Services
    from tests.app.test_api import FakeAsk, FakeEngine, FakeGate
    from tests.fakes import DictC360Reader, InMemoryAuditLog

    app = create_app(
        Services(
            FakeEngine(),
            FakeGate(),
            FakeAsk(),
            DictC360Reader({"G-004817": make_customer()}),
            InMemoryAuditLog(),
        )
    )
    r = TestClient(app).post(
        "/demo/cases/C-118204/notes", json={"text": "x", "user_id": "agent-7", "role": "agent"}
    )
    assert r.status_code == 404


# ----------------------------------------------------------------- notes -> extraction panel
def test_note_extraction_carries_evidence_and_confirm_moves_hardship() -> None:
    from kept.app.demo import demo_app

    client = TestClient(demo_app())
    note = "Cust says shifts were cut at the plant; can pay 140 on the 2nd. Her husband was on the line."
    client.post(f"/demo/cases/{CASE}/notes", json={"text": note, **who("agent-7", "agent")})
    (row,) = client.get(f"/demo/cases/{CASE}/extractions", params=who("agent-7", "agent")).json()
    ex = row["extraction"]
    assert row["note"] == note and ex["hardship_signal"]["value"] == "possible"
    ev = ex["hardship_signal"]["evidence"]
    assert note[ev["char_start"] : ev["char_end"]] == ev["quote"] == "shifts were cut"
    assert ex["promise_intent"]["value"] is True and ex["promised_amount"]["value"] == "140.00"
    assert ex["promised_amount"]["evidence"]["quote"] == "140"
    assert ex["third_party_present"]["value"] is True and ex["stated_reason"]["value"] == "reduced_income"

    card = client.get(f"/cases/{CASE}/nba", params=who("agent-7", "agent")).json()
    assert "Possible hardship" in card["hardship_banner"] and "Eligible programmes" in card["hardship_banner"]

    sid = ex["source_id"]
    confirmed = client.post(
        f"/demo/extractions/{sid}/confirm", json={"agent_id": "agent-7", "edits": {}}
    ).json()
    assert confirmed["confirmed_by_agent_id"] == "agent-7"
    assert (
        client.get(f"/cases/{CASE}/customer", params=who("agent-7", "agent")).json()["hardship_status"]
        == "confirmed"
    )

    client.post(
        f"/demo/extractions/{sid}/confirm", json={"agent_id": "agent-7", "edits": {"hardship_signal": "none"}}
    )
    assert (
        client.get(f"/cases/{CASE}/customer", params=who("agent-7", "agent")).json()["hardship_status"]
        == "none"
    )

    client.post(
        f"/demo/extractions/{sid}/confirm", json={"agent_id": "agent-7", "edits": {"cease_request": True}}
    )
    assert client.get(f"/cases/{CASE}/nba", params=who("agent-7", "agent")).json()["hard_stop"]["blocked"]

    bad = client.post(f"/demo/extractions/{sid}/confirm", json={"agent_id": "agent-7", "edits": {"nope": 1}})
    assert bad.status_code == 422
    assert client.get(f"/demo/cases/{CASE}/extractions", params=who("agent-8", "agent")).status_code == 403
