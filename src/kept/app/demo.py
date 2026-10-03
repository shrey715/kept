"""Demo services for `kept serve --demo`: the real engine and release gate over twelve
in-memory cases, so the UI runs before the real C360, Feast and model land (G3/G4).

Honest about what's fake: the case data is invented; the "model" is a hand-written function
of each case's features (labelled demo-0); the clock runs in business hours so releases can
pass the real calling-hours check at any time of day. The Ask's metric answer is real SQL over
the downloaded dataset (data/raw), not invented numbers. Policy search and steward are other
tracks' services and aren't faked here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from kept.app.api import Services
from kept.common.audit import DuckDBAuditLog, new_event_id
from kept.config import RAW_DIR
from kept.contracts.ask import (
    AskAnswer,
    AskRequest,
    AskResponse,
    Clarification,
    Intent,
    IntentKind,
    Refusal,
    RefusalReason,
)
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import (
    Action,
    DpdBucket,
    HardshipSignal,
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

ALL_CHANNELS = ContactPermissions(call=True, sms=True, email=True, push=True)

# case_id, name, tz, province, agent, overdue, dpd, extra context, feature values
CASES: list[tuple[str, str, str, str, str, str, int, dict[str, Any], dict[str, Any]]] = [
    (
        "CS-2026-118204",
        "Jane Doe",
        "America/Toronto",
        "ON",
        "agent-7",
        "420.00",
        18,
        {},
        {
            "answer_rate_after_18h": 0.8,
            "payment_link_usage": 0.2,
            "kept_promise_ratio": 0.5,
            "days_to_next_payroll": 3,
            "pay_change_vs_3m_avg": -0.27,
            "max_dpd": 18,
        },
    ),
    (
        "CS-2026-302680",
        "Marc Tremblay",
        "America/Toronto",
        "QC",
        "agent-7",
        "1617.64",
        34,
        {},
        {
            "answer_rate_after_18h": 0.3,
            "payment_link_usage": 0.9,
            "kept_promise_ratio": 0.7,
            "days_to_next_payroll": 9,
            "max_dpd": 34,
            "times_30plus_dpd_12m": 1,
        },
    ),
    (
        "CS-2026-344961",
        "Priya Sharma",
        "America/Vancouver",
        "BC",
        "agent-7",
        "2380.10",
        52,
        {"hardship_status": HardshipStatus.POSSIBLE},
        {
            "answer_rate_after_18h": 0.6,
            "payment_link_usage": 0.1,
            "kept_promise_ratio": 0.2,
            "days_to_next_payroll": 12,
            "pay_change_vs_3m_avg": -0.41,
            "payroll_delay_days": 6,
            "max_dpd": 52,
            "hardship_signal": HardshipSignal.POSSIBLE,
        },
    ),
    (
        "CS-2026-451121",
        "Owen MacLeod",
        "America/Halifax",
        "NS",
        "agent-7",
        "310.00",
        9,
        {},
        {
            "answer_rate_after_18h": 0.2,
            "payment_link_usage": 0.85,
            "kept_promise_ratio": 0.9,
            "days_to_next_payroll": 2,
            "max_dpd": 9,
        },
    ),
    (
        "CS-2026-520077",
        "Chloé Gagnon",
        "America/Toronto",
        "QC",
        "agent-7",
        "905.40",
        27,
        {"vulnerable": True},
        {
            "answer_rate_after_18h": 0.5,
            "payment_link_usage": 0.3,
            "kept_promise_ratio": 0.4,
            "days_to_next_payroll": 5,
            "max_dpd": 27,
        },
    ),
    (
        "CS-2026-612390",
        "Daniel Okafor",
        "America/Edmonton",
        "AB",
        "agent-7",
        "4120.00",
        64,
        {"hard_stop_flags": frozenset({HardStop.CEASE})},
        {"answer_rate_after_18h": 0.1, "max_dpd": 64, "cease_request_flag": True},
    ),
    (
        "CS-2026-700145",
        "Sofia Rossi",
        "America/Toronto",
        "ON",
        "agent-7",
        "760.25",
        21,
        {"in_holdout": True, "legacy_action": Action.SMS_PAYMENT_LINK},
        {"answer_rate_after_18h": 0.7, "payment_link_usage": 0.4, "kept_promise_ratio": 0.6, "max_dpd": 21},
    ),
    (
        "CS-2026-781002",
        "Liam Nguyen",
        "America/Winnipeg",
        "MB",
        "agent-7",
        "1250.00",
        41,
        {"contact_permissions": ContactPermissions()},
        {"answer_rate_after_18h": 0.4, "max_dpd": 41},
    ),
    (
        "CS-2026-803311",
        "Hannah Kowalski",
        "America/Regina",
        "SK",
        "agent-8",
        "540.00",
        15,
        {},
        {
            "answer_rate_after_18h": 0.75,
            "payment_link_usage": 0.5,
            "kept_promise_ratio": 0.8,
            "days_to_next_payroll": 4,
            "max_dpd": 15,
        },
    ),
    (
        "CS-2026-870420",
        "Ahmed Hassan",
        "America/St_Johns",
        "NL",
        "agent-8",
        "3305.90",
        58,
        {"hardship_status": HardshipStatus.CONFIRMED},
        {
            "answer_rate_after_18h": 0.55,
            "kept_promise_ratio": 0.3,
            "days_to_next_payroll": 10,
            "max_dpd": 58,
            "pay_change_vs_3m_avg": -0.35,
        },
    ),
    (
        "CS-2026-904518",
        "Grace Lee",
        "America/Vancouver",
        "BC",
        "agent-8",
        "199.99",
        6,
        {},
        {"answer_rate_after_18h": 0.15, "payment_link_usage": 0.95, "kept_promise_ratio": 0.95, "max_dpd": 6},
    ),
    (
        "CS-2026-955003",
        "Robert Fraser",
        "America/Toronto",
        "ON",
        "agent-8",
        "2875.00",
        47,
        {"hard_stop_flags": frozenset({HardStop.INSOLVENCY})},
        {"max_dpd": 47},
    ),
]
HARDSHIP_WORDS = (
    "lost",
    "shift",
    "laid off",
    "reduced hours",
    "hours cut",
    "medical",
    "sick",
    "can't afford",
    "cannot afford",
    "unemployed",
    "ei ",
)
CEASE_WORDS = ("stop calling", "stop contacting", "don't call", "do not call")


def _bucket(dpd: int) -> DpdBucket:
    for edge, b in (
        (0, DpdBucket.CURRENT),
        (30, DpdBucket.B1_30),
        (60, DpdBucket.B31_60),
        (90, DpdBucket.B61_90),
    ):
        if dpd <= edge:
            return b
    return DpdBucket.B91_120


class DemoScorer:
    """Not a trained model: P(paid | action) as a hand-written function of the features."""

    model_version = "demo-0"

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        f = features.astype(float).fillna(0.0)
        call = 0.25 + 0.45 * f["answer_rate_after_18h"]
        sms = 0.18 + 0.5 * f["payment_link_usage"]
        kept = f["kept_promise_ratio"]
        wait = 0.12 + 0.1 * kept
        out = pd.DataFrame(
            {
                "wait": wait,
                "email": wait + 0.03,
                "push": wait + 0.02,
                "sms_payment_link": sms,
                "call": call,
                "promise_request": 0.2 + 0.4 * kept,
                "payment_plan": 0.22 + 0.35 * kept + 0.1 * (f["pay_change_vs_3m_avg"] < 0),
                "hardship_review": 0.3 + 0.2 * (f["pay_change_vs_3m_avg"] < -0.2),
            },
            index=features.index,
        )
        return out.clip(0, 0.95)

    def contributions(self, row: pd.DataFrame, action: Action) -> dict[str, float]:
        v = row.iloc[0].astype(float).fillna(0.0)
        return {
            "answer_rate_after_18h": 0.45 * v["answer_rate_after_18h"] if action is Action.CALL else 0.0,
            "payment_link_usage": 0.5 * v["payment_link_usage"] if action is Action.SMS_PAYMENT_LINK else 0.0,
            "kept_promise_ratio": 0.35 * v["kept_promise_ratio"],
            "days_to_next_payroll": 0.06 if 0 < v["days_to_next_payroll"] <= 5 else 0.0,
            "pay_change_vs_3m_avg": 0.08 if v["pay_change_vs_3m_avg"] < -0.2 else 0.0,
            "max_dpd": 0.02 if v["max_dpd"] > 30 else 0.0,
        }


@dataclass
class DemoWorld:
    contexts: dict[str, CaseContext]
    vectors: dict[str, FeatureVector]
    customers: dict[str, GoldenCustomer]
    log: DuckDBAuditLog

    # CaseContextBuilder
    def build(self, case_id: str, now: datetime) -> CaseContext:
        return self.contexts[case_id].model_copy(
            update={"now": now, "features_as_of": now - timedelta(hours=6)}
        )

    # FeatureProvider
    def get_online(self, case_id: str) -> FeatureVector:
        return self.vectors[case_id]

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("demo")

    # C360Reader
    def get_customer(self, golden_customer_id: str) -> GoldenCustomer:
        return self.customers[golden_customer_id]

    def resolve(self, key: SourceKey) -> str | None:
        return next((g for g, c in self.customers.items() if key in c.source_keys), None)

    def customer_for_case(self, case_id: str) -> GoldenCustomer:
        for c in self.customers.values():
            if c.open_case_id == case_id:
                return c
        raise KeyError(case_id)

    def add_note(self, case_id: str, text: str, user_id: str, now: datetime) -> None:
        """Stand-in for live extraction (Track C): keyword rules on the note."""
        t = f" {text.lower()} "
        ctx = self.contexts[case_id]
        if any(w in t for w in CEASE_WORDS):
            self.contexts[case_id] = ctx.model_copy(
                update={"hard_stop_flags": ctx.hard_stop_flags | {HardStop.CEASE}}
            )
        elif any(w in t for w in HARDSHIP_WORDS) and ctx.hardship_status is HardshipStatus.NONE:
            self.contexts[case_id] = ctx.model_copy(update={"hardship_status": HardshipStatus.POSSIBLE})
            c = self.customer_for_case(case_id)
            self.customers[c.golden_customer_id] = c.model_copy(
                update={"hardship_status": HardshipStatus.POSSIBLE}
            )
            self.vectors[case_id] = self.vectors[case_id].model_copy(
                update={"hardship_signal": HardshipSignal.POSSIBLE}
            )
            self.log.append(
                AuditEvent(
                    event_id=new_event_id(),
                    at=now,
                    kind=AuditKind.HARDSHIP_CHANGE,
                    actor_id=user_id,
                    subject_id=case_id,
                    payload={
                        "case_id": case_id,
                        "from": "none",
                        "to": "possible",
                        "source": "agent note (demo rules)",
                    },
                )
            )


class DemoAsk:
    """Refuses protected-attribute questions; answers the kept-rate metric with real SQL over
    data/raw; everything else waits for Track B's CollectionsAsk."""

    PROTECTED = (
        "gender",
        "marital",
        "citizenship",
        "newcomer",
        "accent",
        "disab",
        "accessib",
        "child benefit",
    )
    SQL = """select c.primary_product as product,
       round(avg(case when p.ptp_status = 'kept' then 1.0 else 0.0 end), 3) as kept_rate,
       count(*) as promises
from read_csv_auto('{raw}/promises_to_pay.csv') p
join read_csv_auto('{raw}/collections_cases.csv') c using (case_id)
where p.ptp_status in ('kept', 'partially_kept', 'broken')
  and p.ptp_due_date > date '2026-09-28' - interval 90 day
group by 1 order by 2 desc"""

    def ask(self, request: AskRequest) -> AskResponse:
        q = request.question.lower()
        hit = next((w for w in self.PROTECTED if w in q), None)
        if hit:
            return Refusal(
                reason=RefusalReason.PROTECTED_ATTRIBUTE,
                message=f"This needs a protected attribute ({hit}...), excluded from collections analytics.",
                suggestion="Try: promise kept rate by product for the last 90 days",
            )
        if "kept rate" in q or "promise" in q:
            sql = self.SQL.format(raw=RAW_DIR)
            if not (RAW_DIR / "promises_to_pay.csv").exists():
                return Clarification(question="The dataset isn't in data/raw on this machine yet.")
            with duckdb.connect() as c:
                rel = c.sql(sql)
                cols, rows = tuple(rel.columns), tuple(tuple(r) for r in rel.fetchall())
            best = rows[0]
            return AskAnswer(
                question=request.question,
                intent=Intent(
                    kind=IntentKind.METRIC,
                    metric_id="promise_kept_rate",
                    group_by=("product",),
                    filters={"window": "last 90 days"},
                    confidence=0.9,
                ),
                sql=sql.replace(str(RAW_DIR), "data/raw"),
                tables_used=("promises_to_pay", "collections_cases"),
                data_freshness=datetime(2026, 9, 28, tzinfo=UTC),
                columns=cols,
                rows=rows,
                narrative=(
                    f"Over the last 90 days, {best[0].replace('_', ' ')} has the highest promise kept rate "
                    f"at {best[1]:.0%} of {best[2]:,} resolved promises."
                ),
            )
        return Clarification(
            question="Demo mode answers the promise kept-rate question and refuses protected-attribute ones. "
            "Everything else needs Track B's Ask."
        )


def _business_clock() -> datetime:
    """Real time, shifted so it's mid-afternoon in Toronto while the demo runs."""
    return datetime.now(UTC) + _OFFSET


def _offset() -> timedelta:
    local = datetime.now(UTC).astimezone(ZoneInfo("America/Toronto"))
    if time(10) <= local.time() <= time(16) and local.weekday() < 5:
        return timedelta(0)
    target = local.replace(hour=14, minute=0, second=0, microsecond=0)
    while target.weekday() >= 5:  # a weekday, so Sunday rules don't hide the flow
        target += timedelta(days=1)
    return target - local


_OFFSET = _offset()


def demo_services() -> Services:
    now = _business_clock()
    contexts, vectors, customers = {}, {}, {}
    for i, (case_id, name, tz, prov, agent, overdue, dpd, ctx_over, feats) in enumerate(CASES, start=1):
        gid = f"G-{910000 + i}"
        local_today = now.astimezone(ZoneInfo(tz)).date()
        payday = local_today + timedelta(days=int(feats.get("days_to_next_payroll") or 14))
        contexts[case_id] = CaseContext(
            case_id=case_id,
            golden_customer_id=gid,
            assigned_agent_id=agent,
            now=now,
            time_zone=tz,
            permitted_call_start_local=time(8),
            permitted_call_end_local=time(20),
            do_not_contact=False,
            contacts_last_7d=i % 3,
            balance_at_risk=Decimal(overdue),
            expected_next_payroll_date=payday,
            payroll_frequency=PayrollFrequency.BIWEEKLY if i % 2 else PayrollFrequency.MONTHLY,
            estimated_monthly_spare_cash=Decimal(overdue) / 3 + Decimal("40"),
            features_as_of=now,
            **{"hardship_status": HardshipStatus.NONE, "contact_permissions": ALL_CHANNELS, **ctx_over},
        )
        vectors[case_id] = FeatureVector(
            case_id=case_id, golden_customer_id=gid, as_of=now, feature_set_version="demo", **feats
        )
        customers[gid] = GoldenCustomer(
            golden_customer_id=gid,
            source_keys=(
                SourceKey(
                    system=SourceSystem.CRM, key=f"{name[:1]}{name.split()[-1][:2].upper()}-{4000 + i * 37}"
                ),
                SourceKey(
                    system=SourceSystem.CARD if i % 2 else SourceSystem.LOAN,
                    key=f"{'C' if i % 2 else 'L'}-{88200 + i}",
                ),
                SourceKey(system=SourceSystem.DEPOSIT, key=f"D-{51000 + i * 11}"),
                SourceKey(system=SourceSystem.COLLECTIONS, key=case_id),
            ),
            match_confidence_min=round(0.9 + (i % 9) / 100, 2),
            match_review_status=MatchReviewStatus.AUTO,
            display_name=name,
            primary_phone_e164=f"+1416555{1000 + i:04d}",
            email=f"{name.split()[0].lower()}.{name.split()[-1].lower()}@example.com",
            province_code=prov,
            time_zone=tz,
            total_overdue=Decimal(overdue),
            max_dpd=dpd,
            current_bucket=_bucket(dpd),
            open_case_id=case_id,
            assigned_agent_id=agent,
            contact_permissions=contexts[case_id].contact_permissions,
            do_not_contact=False,
            collections_hold=HardStop.INSOLVENCY in contexts[case_id].hard_stop_flags,
            hardship_status=contexts[case_id].hardship_status,
            vulnerability_flag=contexts[case_id].vulnerable,
            expected_next_payroll_date=payday,
            as_of_date=date(2026, 9, 28),
            refreshed_at=now,
        )
    log = DuckDBAuditLog()
    world = DemoWorld(contexts, vectors, customers, log)
    proposals: dict[str, Proposal] = {}
    engine = KeptEngine(
        context=world, features=world, scorer=DemoScorer(), audit_log=log, proposals=proposals
    )
    return Services(
        engine=engine,
        release_gate=Releaser(proposals=proposals, context=world, audit_log=log),
        ask=DemoAsk(),
        c360=world,
        audit_log=log,
        proposals=proposals,
        open_cases=lambda: [c[0] for c in CASES],
        clock=_business_clock,
        add_note=world.add_note,
    )
