"""#89: the customer's pay link offers only Kept-sized plans, and only for a released SMS proposal."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from kept.app.api import Services, create_app
from kept.contracts.enums import Action, Channel, PayrollFrequency, ReleaseTier
from kept.contracts.nba import Proposal, ProposalStatus
from kept.nba.sizing import promise_options, size_promise
from tests.fakes import InMemoryAuditLog

NOW = datetime(2026, 10, 5, 18, tzinfo=UTC)
SIZE = {
    "balance_due": Decimal("300"),
    "spare_cash_monthly": Decimal("400"),
    "expected_payday": date(2026, 10, 15),
    "payroll_frequency": PayrollFrequency.BIWEEKLY,
    "today": date(2026, 10, 5),
}


def test_options_fit_spare_cash_and_payday_and_match_size_promise() -> None:
    opts = promise_options(**SIZE)
    assert [o.installments for o in opts] == [2, 3]  # 300 > ~184 per pay; 150 and 100 fit
    assert all(o.amount <= o.spare_cash_estimate and (o.due_date - o.payday).days in (1, 2) for o in opts)
    assert size_promise(**SIZE) == opts[0]


class _Engine:
    def payment_options(self, case_id: str, now: datetime):  # type: ignore[no-untyped-def]
        return promise_options(**SIZE)


def _client(  # type: ignore[no-untyped-def]
    action: Action = Action.SMS_PAYMENT_LINK,
    status: ProposalStatus = ProposalStatus.RELEASED,
    engine: object = None,
):
    p = Proposal(
        proposal_id="P1",
        case_id="C1",
        golden_customer_id="G1",
        action=action,
        channel=Channel.SMS,
        tier=ReleaseTier.GREEN,
        model_version="t",
        features_as_of=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        status=status,
    )
    log = InMemoryAuditLog()
    services = Services(engine or _Engine(), None, None, None, log, proposals={"P1": p}, clock=lambda: NOW)  # type: ignore[arg-type]
    return TestClient(create_app(services)), log


def test_released_sms_gets_plans_and_the_choice_is_audited() -> None:
    client, log = _client()
    offer = client.get("/pay/P1").json()
    assert [o["installments"] for o in offer["options"]] == [2, 3]
    assert client.post("/pay/P1", json={"installments": 1}).status_code == 422  # not on offer
    assert client.post("/pay/P1", json={"installments": 3}).json()["amount"] == "100.00"
    (event,) = log.read()
    assert event.actor_id == "customer:self-serve" and event.payload["installments"] == 3


def test_no_link_for_a_call_or_an_unreleased_proposal() -> None:
    assert _client(action=Action.CALL)[0].get("/pay/P1").status_code == 404
    assert _client(status=ProposalStatus.PENDING)[0].get("/pay/P1").status_code == 404
    assert _client()[0].get("/pay/nope").status_code == 404


class _NoPlans:
    def payment_options(self, case_id: str, now: datetime):  # type: ignore[no-untyped-def]
        return []


def test_no_plan_means_no_amount() -> None:
    """No detected payday or spare cash: no plans and no amount, so the page never says "$0.00 is overdue"."""
    offer = _client(engine=_NoPlans())[0].get("/pay/P1").json()
    assert offer == {"amount_due": None, "options": [], "ask": True}  # the page asks about their pay


class _Unknown:  # the bank knows neither payday nor spare cash: only the customer's answers size a plan
    def payment_options(self, case_id: str, now: datetime, stated=None):  # type: ignore[no-untyped-def]
        if stated is None:
            return []
        return promise_options(
            **{**SIZE, "spare_cash_monthly": None, "expected_payday": stated.next_payday},
            stated_per_payday=stated.per_payday,
        )


def test_the_customer_answers_size_the_plan_and_are_audited() -> None:
    client, log = _client(engine=_Unknown())
    stated = {"next_payday": "2026-10-16", "frequency": "biweekly", "per_payday": "120"}
    offer = client.post("/pay/P1/plans", json=stated).json()
    assert [o["installments"] for o in offer["options"]] == [3] and not offer["ask"]  # 150 > 120 >= 100
    assert (
        offer["options"][0]["due_date"] == "2026-10-17"
        and "said they can afford" in offer["options"][0]["rationale"]
    )
    assert client.post("/pay/P1", json={"installments": 2, "stated": stated}).status_code == 422
    assert client.post("/pay/P1", json={"installments": 3, "stated": stated}).json()["amount"] == "100.00"
    (event,) = log.read()
    assert (
        event.payload["stated_next_payday"] == "2026-10-16" and event.payload["stated_per_payday"] == "120.00"
    )
    too_little = client.post("/pay/P1/plans", json={**stated, "per_payday": "50"}).json()
    assert too_little == {"amount_due": None, "options": [], "ask": False}  # the page offers a call instead
    assert client.post("/pay/P1/plans", json={**stated, "next_payday": "2026-12-01"}).status_code == 422
