"""Demo services for `kept serve --demo`: the real engine and release gate over three
in-memory cases, so the UI runs before the real C360, Feast and model land (G3/G4).
Ask and the steward queue are other tracks' services; the demo answers them minimally."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from kept.app.api import Services
from kept.common.audit import DuckDBAuditLog
from kept.contracts.ask import AskRequest, AskResponse, Clarification, Refusal, RefusalReason
from kept.contracts.enums import (
    Action,
    HardshipStatus,
    HardStop,
    MatchReviewStatus,
    PayrollFrequency,
    SourceSystem,
)
from kept.contracts.features import FeatureVector
from kept.contracts.identity import ContactPermissions, GoldenCustomer, SourceKey
from kept.contracts.nba import CaseContext, Proposal
from kept.nba.engine import KeptEngine
from kept.nba.release import Releaser

PROBS = {
    "wait": 0.22,
    "email": 0.25,
    "push": 0.23,
    "sms_payment_link": 0.30,
    "call": 0.58,
    "promise_request": 0.40,
    "payment_plan": 0.55,
    "hardship_review": 0.47,
}


class _Scorer:
    model_version = "demo-0"

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame([PROBS] * len(features), index=features.index)

    def contributions(self, row: pd.DataFrame, action: Action) -> dict[str, float]:
        return {"days_to_next_payroll": 0.09, "pay_change_vs_3m_avg": 0.06, "answer_rate_after_18h": 0.04}


@dataclass
class _Cases:
    contexts: dict[str, CaseContext]

    def build(self, case_id: str, now: datetime) -> CaseContext:
        ctx = self.contexts[case_id]
        return ctx.model_copy(update={"now": now, "features_as_of": now - timedelta(hours=6)})


@dataclass
class _Features:
    vectors: dict[str, FeatureVector]

    def get_online(self, case_id: str) -> FeatureVector:
        return self.vectors[case_id].model_copy(update={"as_of": datetime.now(UTC) - timedelta(hours=6)})

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("demo")


@dataclass
class _C360:
    customers: dict[str, GoldenCustomer] = field(default_factory=dict)

    def get_customer(self, golden_customer_id: str) -> GoldenCustomer:
        return self.customers[golden_customer_id]

    def resolve(self, key: SourceKey) -> str | None:
        return None

    def customer_for_case(self, case_id: str) -> GoldenCustomer:
        for c in self.customers.values():
            if c.open_case_id == case_id:
                return c
        raise KeyError(case_id)


class _Ask:
    def ask(self, request: AskRequest) -> AskResponse:
        if "gender" in request.question.lower():
            return Refusal(
                reason=RefusalReason.PROTECTED_ATTRIBUTE,
                message="This needs gender_code, which is excluded from collections analytics.",
                suggestion="Try: promise kept rate by product",
            )
        return Clarification(
            question="The Ask isn't connected in demo mode (Track B). "
            "Try a protected-attribute question to see a refusal."
        )


def demo_services() -> Services:
    now = datetime.now(UTC)
    payday = (now + timedelta(days=3)).date()
    cases: dict[str, dict[str, Any]] = {
        "CS-DEMO-CALL": dict(hardship_status=HardshipStatus.NONE),
        "CS-DEMO-HARDSHIP": dict(hardship_status=HardshipStatus.POSSIBLE),
        "CS-DEMO-STOP": dict(
            hardship_status=HardshipStatus.NONE, hard_stop_flags=frozenset({HardStop.CEASE})
        ),
    }
    contexts, vectors, customers = {}, {}, {}
    for i, (case_id, over) in enumerate(cases.items(), start=1):
        gid = f"G-90000{i}"
        contexts[case_id] = CaseContext(
            case_id=case_id,
            golden_customer_id=gid,
            assigned_agent_id="agent-7",
            now=now,
            time_zone="America/Toronto",
            sunday_contact_permitted=True,
            contact_permissions=ContactPermissions(call=True, sms=True, email=True, push=True),
            do_not_contact=False,
            contacts_last_7d=1,
            balance_at_risk=Decimal("420.00"),
            expected_next_payroll_date=payday,
            payroll_frequency=PayrollFrequency.MONTHLY,
            estimated_monthly_spare_cash=Decimal("160.00"),
            features_as_of=now,
            **over,
        )
        vectors[case_id] = FeatureVector(
            case_id=case_id,
            golden_customer_id=gid,
            as_of=now,
            feature_set_version="demo",
            days_to_next_payroll=3,
            pay_change_vs_3m_avg=-0.2672,
            answer_rate_after_18h=0.8,
            max_dpd=18,
        )
        customers[gid] = GoldenCustomer(
            golden_customer_id=gid,
            source_keys=(SourceKey(system=SourceSystem.CRM, key=f"DEMO-{i}"),),
            match_review_status=MatchReviewStatus.AUTO,
            total_overdue=Decimal("420.00"),
            max_dpd=18,
            current_bucket="1-30",
            open_case_id=case_id,
            assigned_agent_id="agent-7",
            contact_permissions=ContactPermissions(call=True, sms=True, email=True, push=True),
            do_not_contact=False,
            collections_hold=False,
            hardship_status=over["hardship_status"],
            as_of_date=date.today(),
            refreshed_at=now,
        )
    proposals: dict[str, Proposal] = {}
    log = DuckDBAuditLog()
    ctx = _Cases(contexts)
    engine = KeptEngine(
        context=ctx, features=_Features(vectors), scorer=_Scorer(), audit_log=log, proposals=proposals
    )
    return Services(
        engine=engine,
        release_gate=Releaser(proposals=proposals, context=ctx, audit_log=log),
        ask=_Ask(),
        c360=_C360(customers),
        audit_log=log,
    )
