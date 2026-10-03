"""HTTP contract for the UI, with every service faked."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kept.app.api import Services, create_app
from kept.contracts import (
    Action,
    AskRequest,
    Channel,
    GoldenCustomer,
    NBACard,
    Proposal,
    Refusal,
    RefusalReason,
    ReleaseDecision,
    ReleaseResult,
    ReleaseTier,
    Role,
)

from ..fakes import DictC360Reader, InMemoryAuditLog

NOW = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)


class FakeEngine:
    def recommend(self, case_id: str, now: datetime) -> NBACard:
        if case_id != "C-118204":
            raise KeyError(case_id)
        p = Proposal(
            proposal_id="P-1",
            case_id=case_id,
            golden_customer_id="G-004817",
            action=Action.CALL,
            channel=Channel.CALL,
            tier=ReleaseTier.AMBER,
            model_version="nba-0.3",
            features_as_of=now - timedelta(hours=16),
            created_at=now,
            expires_at=now + timedelta(hours=4),
        )
        return NBACard(
            case_id=case_id,
            golden_customer_id="G-004817",
            model_version="nba-0.3",
            features_as_of=p.features_as_of,
            headline="Call today 18:00-20:00",
            proposal=p,
            probabilities=(),
        )


class FakeGate:
    def release(self, decision: ReleaseDecision, now: datetime) -> ReleaseResult:
        return ReleaseResult(
            proposal_id=decision.proposal_id,
            released=True,
            reason="ok",
            audit_event_id="E-1",
            executed_at=now,
        )


class FakeAsk:
    def ask(self, request: AskRequest) -> Refusal:
        return Refusal(
            reason=RefusalReason.PROTECTED_ATTRIBUTE,
            message="This needs gender_code ...",
            suggestion="Try: x",
        )


@pytest.fixture
def client(make_customer: Callable[..., GoldenCustomer]) -> TestClient:
    c360 = DictC360Reader({"G-004817": make_customer()})
    services = Services(
        engine=FakeEngine(), release_gate=FakeGate(), ask=FakeAsk(), c360=c360, audit_log=InMemoryAuditLog()
    )
    return TestClient(create_app(services))


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_assigned_agent_gets_card(client: TestClient) -> None:
    r = client.get(
        "/cases/C-118204/nba", params={"user_id": "agent-7", "role": "agent", "now": NOW.isoformat()}
    )
    assert r.status_code == 200
    card = NBACard.model_validate(r.json())
    assert card.proposal is not None and card.proposal.action is Action.CALL


def test_other_agent_forbidden(client: TestClient) -> None:
    r = client.get("/cases/C-118204/nba", params={"user_id": "agent-8", "role": "agent"})
    assert r.status_code == 403


def test_unknown_case_404(client: TestClient) -> None:
    r = client.get("/cases/C-404/nba", params={"user_id": "tl-1", "role": "team_lead"})
    assert r.status_code == 404


def _decision(pid: str = "P-1") -> dict[str, Any]:
    return ReleaseDecision(
        proposal_id=pid,
        reviewer_id="agent-7",
        reviewer_role=Role.AGENT,
        decision="accept",  # type: ignore[arg-type]
        decided_at=NOW,
    ).model_dump(mode="json")


def test_decision_returns_release_result(client: TestClient) -> None:
    r = client.post("/proposals/P-1/decision", json=_decision())
    assert r.status_code == 200 and ReleaseResult.model_validate(r.json()).released


def test_decision_path_body_mismatch_422(client: TestClient) -> None:
    assert client.post("/proposals/P-2/decision", json=_decision("P-1")).status_code == 422


def test_ask_returns_discriminated_response(client: TestClient) -> None:
    r = client.post(
        "/ask", json={"question": "kept rate by gender_code", "user_id": "an-1", "role": "analyst"}
    )
    assert r.status_code == 200 and r.json()["kind"] == "refusal"


def test_openapi_lists_every_route(client: TestClient) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/health",
        "/cases/{case_id}/nba",
        "/proposals/{proposal_id}/decision",
        "/ask",
        "/steward/queue",
        "/steward/items/{item_id}",
        "/extractions/{source_id}/confirm",
    } <= paths
