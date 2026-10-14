"""HTTP contract for the UI, with every service faked."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kept.app.api import Services, create_app
from kept.contracts import (
    Action,
    AskRequest,
    AuditKind,
    CandidatePair,
    Channel,
    ExtractedValue,
    GoldenCustomer,
    HardshipSignal,
    NBACard,
    Proposal,
    Refusal,
    RefusalReason,
    ReleaseDecision,
    ReleaseResult,
    ReleaseTier,
    Role,
    SourceKey,
    SourceSystem,
    StatedReason,
    TextExtraction,
)
from kept.data.identity.clustering import decide
from kept.data.identity.steward import StewardQueue

from ..fakes import DictC360Reader, InMemoryAuditLog, InMemoryExtractionStore

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


def test_naive_now_rejected(client: TestClient) -> None:
    r = client.get(
        "/cases/C-118204/nba", params={"user_id": "agent-7", "role": "agent", "now": "2026-10-02T22:00:00"}
    )
    assert r.status_code == 422


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


def _extraction() -> TextExtraction:
    def nothing(v: object) -> ExtractedValue[Any]:
        return ExtractedValue(value=v, confidence=0.9)

    return TextExtraction(
        source_id="N-1",
        case_id="C-118204",
        hardship_signal=nothing(HardshipSignal.NONE),
        stated_reason=nothing(StatedReason.NONE),
        promise_intent=nothing(False),
        promised_date=nothing(None),
        promised_amount=nothing(None),
        dispute=nothing(False),
        cease_request=nothing(False),
        third_party_present=nothing(False),
        extractor="llm:prompt-v1",
        extracted_at=NOW,
    )


Confirm = tuple[TestClient, InMemoryExtractionStore, InMemoryAuditLog]


@pytest.fixture
def confirm_setup(make_customer: Callable[..., GoldenCustomer]) -> Confirm:
    store, log = InMemoryExtractionStore(), InMemoryAuditLog()
    store.put(_extraction())
    services = Services(
        engine=FakeEngine(),
        release_gate=FakeGate(),
        ask=FakeAsk(),
        c360=DictC360Reader({"G-004817": make_customer()}),
        audit_log=log,
        clock=lambda: NOW,
        extractions=store,
    )
    return TestClient(create_app(services)), store, log


def test_confirm_extraction_sets_agent_and_audits(confirm_setup: Confirm) -> None:
    client, store, log = confirm_setup
    r = client.post("/extractions/N-1/confirm", json={"agent_id": "agent-7"})
    assert r.status_code == 200
    assert TextExtraction.model_validate(r.json()).confirmed_by_agent_id == "agent-7"
    saved = store.get("N-1")
    assert saved is not None and saved.confirmed_by_agent_id == "agent-7"
    (e,) = log.read(kind=AuditKind.OVERRIDE)
    assert e.actor_id == "agent-7" and e.payload["source_id"] == "N-1" and e.payload["edited_fields"] == []


def test_confirm_extraction_with_edit(confirm_setup: Confirm) -> None:
    client, store, _ = confirm_setup
    body = {"agent_id": "agent-7", "edits": {"promised_amount": "140.00"}}
    assert client.post("/extractions/N-1/confirm", json=body).status_code == 200
    saved = store.get("N-1")
    assert saved is not None
    assert saved.promised_amount.value == Decimal("140.00") and saved.promised_amount.confidence == 1.0


def test_confirm_cease_request(confirm_setup: Confirm) -> None:
    client, store, log = confirm_setup
    body = {"agent_id": "agent-7", "edits": {"cease_request": True}}
    assert client.post("/extractions/N-1/confirm", json=body).status_code == 200
    saved = store.get("N-1")
    # confirmed + cease true is what turns text_signals.cease_request_flag on
    assert (
        saved is not None and saved.cease_request.value is True and saved.confirmed_by_agent_id == "agent-7"
    )
    assert log.read()[0].payload["edited_fields"] == ["cease_request"]


@pytest.mark.parametrize("edits", [{"not_a_field": 1}, {"promised_date": "not a date"}])
def test_confirm_bad_edit_422(confirm_setup: Confirm, edits: dict[str, Any]) -> None:
    client, store, log = confirm_setup
    r = client.post("/extractions/N-1/confirm", json={"agent_id": "agent-7", "edits": edits})
    assert r.status_code == 422
    saved = store.get("N-1")
    assert saved is not None and saved.confirmed_by_agent_id is None and not log.read()


def test_confirm_unknown_extraction_404(confirm_setup: Confirm) -> None:
    client, _, _ = confirm_setup
    assert client.post("/extractions/N-404/confirm", json={"agent_id": "agent-7"}).status_code == 404


def test_confirm_other_agent_403(confirm_setup: Confirm) -> None:
    client, store, _ = confirm_setup
    assert client.post("/extractions/N-1/confirm", json={"agent_id": "agent-8"}).status_code == 403
    saved = store.get("N-1")
    assert saved is not None and saved.confirmed_by_agent_id is None


def test_confirm_without_store_503(client: TestClient) -> None:
    assert client.post("/extractions/N-1/confirm", json={"agent_id": "agent-7"}).status_code == 503


# ----------------------------------------------------------------- /steward (Track A)
def _steward_client(queue: StewardQueue | None, audit: InMemoryAuditLog) -> TestClient:
    services = Services(
        engine=FakeEngine(),
        release_gate=FakeGate(),
        ask=FakeAsk(),
        c360=DictC360Reader(),
        audit_log=audit,
        steward=queue,
        clock=lambda: NOW,
    )
    return TestClient(create_app(services))


def _queue_with_one_pair() -> tuple[StewardQueue, str]:
    pair = CandidatePair(
        left=SourceKey(system=SourceSystem.CRM, key="C1"),
        right=SourceKey(system=SourceSystem.LOAN, key="L1"),
        score=0.88,
        rule="splink",
    )
    queue = StewardQueue()
    item = queue.enqueue(decide(pair), reasons=("score_0.80_0.95",), at=NOW)
    return queue, item.item_id


def test_steward_queue_lists_pending_items() -> None:
    queue, item_id = _queue_with_one_pair()
    r = _steward_client(queue, InMemoryAuditLog()).get("/steward/queue")
    assert r.status_code == 200
    assert r.json() == [
        {
            "item_id": item_id,
            "left_key": "crm:C1",
            "right_key": "loan:L1",
            "score": 0.88,
            "reasons": ["score_0.80_0.95"],
        }
    ]


def test_steward_resolve_audits_and_drops_the_item_from_the_queue() -> None:
    queue, item_id = _queue_with_one_pair()
    audit = InMemoryAuditLog()
    client = _steward_client(queue, audit)
    r = client.post(f"/steward/items/{item_id}", json={"verdict": "same_person", "steward_id": "steward-1"})
    assert r.status_code == 200 and r.json() == {"status": "resolved"}
    assert client.get("/steward/queue").json() == []
    (event,) = audit.read(kind=AuditKind.STEWARD_DECISION)
    assert event.actor_id == "steward-1" and event.actor_role is Role.DATA_STEWARD
    assert event.subject_id == item_id and event.payload == {"verdict": "same_person"}


def test_steward_unsure_keeps_the_item_pending() -> None:
    queue, item_id = _queue_with_one_pair()
    client = _steward_client(queue, InMemoryAuditLog())
    r = client.post(f"/steward/items/{item_id}", json={"verdict": "unsure", "steward_id": "steward-1"})
    assert r.json() == {"status": "pending"} and len(client.get("/steward/queue").json()) == 1


def test_steward_queue_pages_and_reports_the_total() -> None:
    queue, _ = _queue_with_one_pair()
    client = _steward_client(queue, InMemoryAuditLog())
    first, past = client.get("/steward/queue?limit=1"), client.get("/steward/queue?offset=1")
    assert len(first.json()) == 1 and past.json() == []
    assert first.headers["x-total-count"] == past.headers["x-total-count"] == "1"


def test_steward_resolve_errors() -> None:
    queue, item_id = _queue_with_one_pair()
    client = _steward_client(queue, InMemoryAuditLog())
    body = {"verdict": "same_person", "steward_id": "steward-1"}
    assert client.post("/steward/items/SI-missing", json=body).status_code == 404
    assert client.post(f"/steward/items/{item_id}", json={**body, "verdict": "maybe"}).status_code == 422
    assert client.post(f"/steward/items/{item_id}", json=body).status_code == 200
    assert client.post(f"/steward/items/{item_id}", json=body).status_code == 409  # already resolved


def test_steward_routes_are_503_without_a_queue() -> None:
    client = _steward_client(None, InMemoryAuditLog())
    assert client.get("/steward/queue").status_code == 503
    body = {"verdict": "same_person", "steward_id": "s"}
    assert client.post("/steward/items/SI-1", json=body).status_code == 503
