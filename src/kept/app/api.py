"""HTTP API. Route owners: /cases, /queue, /approvals, /audit, /proposals, /demo (D),
/ask (B), /steward (A), /extractions (C).

The route signatures are the contract for the UI (web/ generates its types from this app's
OpenAPI schema). Services are injected so tests and the demo can swap in fakes.

Auth is out of scope for the hackathon: the caller passes user_id and role, and
every handler applies kept.governance.access before returning data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kept import __version__
from kept.common.audit import new_event_id
from kept.contracts.ask import AskRequest, AskResponse
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import Action, ReleaseTier, Role
from kept.contracts.features import TextExtraction
from kept.contracts.identity import GoldenCustomer
from kept.contracts.interfaces import (
    AskService,
    AuditLog,
    C360Reader,
    ExtractionStore,
    NBAEngine,
    ReleaseGate,
)
from kept.contracts.nba import NBACard, Proposal, ProposalStatus, ReleaseDecision, ReleaseResult
from kept.data.identity.steward import StewardQueue, StewardVerdict
from kept.governance.access import can_view_case, masked_view
from kept.text.extract import confirm

CASE_WIDE_ROLES = frozenset({Role.HARDSHIP_SPECIALIST, Role.TEAM_LEAD, Role.COMPLIANCE})


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Services:
    engine: NBAEngine
    release_gate: ReleaseGate
    ask: AskService
    c360: C360Reader
    audit_log: AuditLog
    proposals: dict[str, Proposal] = field(default_factory=dict)  # the engine's proposal store
    open_cases: Callable[[], list[str]] | None = None  # every open case ID (queue); real: from gold
    clock: Callable[[], datetime] = _utcnow  # demo runs on a business-hours clock
    add_note: Callable[[str, str, str, datetime], None] | None = None  # (case, text, user, now)
    steward: StewardQueue | None = None  # Track A: /steward routes
    extractions: ExtractionStore | None = None  # Track C: /extractions routes
    note_text: Callable[[str], str | None] | None = None  # source_id -> the note's text, for the panel
    demo: bool = False


class HealthResponse(BaseModel):
    status: str
    version: str
    now: datetime
    demo: bool


class QueueItem(BaseModel):
    case_id: str
    golden_customer_id: str
    display_name: str | None
    total_overdue: Decimal
    max_dpd: int
    current_bucket: str
    headline: str
    action: Action | None
    tier: ReleaseTier | None
    proposal_status: ProposalStatus | None
    expected_value: Decimal  # uplift x balance at risk of the recommended action; 0 for no action
    hardship: bool
    hard_stop: bool
    no_action_reason: str | None


class ApprovalItem(BaseModel):
    stage: Literal["specialist", "second_person", "green_batch", "assigned_agent"]
    proposal: Proposal
    first_approver: str | None = None


class NoteIn(BaseModel):
    text: str
    user_id: str
    role: Role


class StewardItemOut(BaseModel):
    item_id: str
    left_key: str
    right_key: str
    score: float
    reasons: list[str]


class StewardVerdictIn(BaseModel):
    verdict: str
    steward_id: str


class NoteExtraction(BaseModel):
    note: str
    extraction: TextExtraction


class ExtractionConfirmIn(BaseModel):
    agent_id: str
    edits: dict[str, object] = {}


def create_app(services: Services) -> FastAPI:
    """Routes and their contracts:

    GET  /health                                  200 HealthResponse
    GET  /queue?user_id&role                      200 list[QueueItem] the role may see, best first;
                                                  403 for roles without case access
    GET  /cases/{case_id}/nba?user_id&role[&now]  200 NBACard; 403 if access.can_view_case is
                                                  False; 404 unknown case
    GET  /cases/{case_id}/customer?user_id&role   200 GoldenCustomer, PII masked unless compliance
    GET  /approvals?user_id&role                  200 list[ApprovalItem] this role can act on
    GET  /audit?user_id&role[&case_id][&kind]     200 list[AuditEvent], newest first
    POST /proposals/{proposal_id}/decision        200 ReleaseResult; 422 if body.proposal_id
                                                  differs from the path
    POST /cases/{case_id}/notes                   200 NBACard after the note is extracted (live
                                                  extraction; /demo/... is the same route); 502
                                                  extraction failed; 503 no live extraction
    GET  /cases/{case_id}/extractions?user_id&role 200 list[NoteExtraction], newest first (20);
                                                  503 no store
    POST /ask                                     200 AskAnswer | Refusal | Clarification
    GET  /steward/queue                           200 list[StewardItemOut]
    POST /steward/items/{item_id}                 200 {"status": ...}; 404 unknown item
    POST /extractions/{source_id}/confirm         200 TextExtraction; 403 not the assigned agent;
                                                  404 unknown source/case; 422 bad edit; 503 no store
    """
    app = FastAPI(title="Kept", version=__version__)
    cards: dict[str, NBACard] = {}  # latest card per case; `kept score` warms it nightly (G3)

    def customer(case_id: str) -> GoldenCustomer:
        try:
            return services.c360.customer_for_case(case_id)
        except KeyError:
            raise HTTPException(404, f"unknown case {case_id}") from None

    def guard_case(case_id: str, user_id: str, role: Role) -> GoldenCustomer:
        # ponytail: user_id/role come from the query string; real auth (SSO) replaces this
        c = customer(case_id)
        if not can_view_case(role=role, user_id=user_id, assigned_agent_id=c.assigned_agent_id):
            raise HTTPException(403, "not your case")
        return c

    def card_for(case_id: str, now: datetime) -> NBACard:
        try:
            cards[case_id] = services.engine.recommend(case_id, now)
        except KeyError:
            raise HTTPException(404, f"unknown case {case_id}") from None
        return cards[case_id]

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__, now=services.clock(), demo=services.demo)

    @app.get("/queue", response_model=list[QueueItem])
    def queue(user_id: str, role: Role) -> list[QueueItem]:
        if role is not Role.AGENT and role not in CASE_WIDE_ROLES:
            raise HTTPException(403, "this role has no case queue")
        out = []
        for case_id in services.open_cases() if services.open_cases else []:
            c = customer(case_id)
            if not can_view_case(role=role, user_id=user_id, assigned_agent_id=c.assigned_agent_id):
                continue
            card = cards.get(case_id) or card_for(case_id, services.clock())
            p = card.proposal
            if p is not None and p.proposal_id in services.proposals:
                p = services.proposals[p.proposal_id]  # status moves on after review
            wait = next((a.p_paid_14d for a in card.probabilities if a.action is Action.WAIT), None)
            lift = (
                card.probabilities[0].p_paid_14d - wait
                if p and card.probabilities and wait is not None
                else 0.0
            )
            masked = masked_view(c, role)
            out.append(
                QueueItem(
                    case_id=case_id,
                    golden_customer_id=c.golden_customer_id,
                    display_name=masked.display_name,
                    total_overdue=c.total_overdue,
                    max_dpd=c.max_dpd,
                    current_bucket=c.current_bucket.value,
                    headline=card.headline,
                    action=p.action if p else None,
                    tier=p.tier if p else None,
                    proposal_status=p.status if p else None,
                    expected_value=(Decimal(str(max(lift, 0.0))) * c.total_overdue).quantize(Decimal("0.01")),
                    hardship=card.hardship_banner is not None,
                    hard_stop=bool(card.hard_stop and card.hard_stop.blocked),
                    no_action_reason=card.no_action_reason,
                )
            )
        return sorted(out, key=lambda q: (q.action is None, -q.expected_value, q.case_id))

    @app.get("/cases/{case_id}/nba", response_model=NBACard)
    def get_nba(case_id: str, user_id: str, role: Role, now: datetime | None = None) -> NBACard:
        guard_case(case_id, user_id, role)
        if now is not None and now.tzinfo is None:
            raise HTTPException(422, "now must include a time zone")
        return card_for(case_id, now or services.clock())

    @app.get("/cases/{case_id}/customer", response_model=GoldenCustomer)
    def get_customer(case_id: str, user_id: str, role: Role) -> GoldenCustomer:
        return masked_view(guard_case(case_id, user_id, role), role)

    @app.get("/approvals", response_model=list[ApprovalItem])
    def approvals(user_id: str, role: Role) -> list[ApprovalItem]:
        first = getattr(services.release_gate, "first_approver", None)
        out = []
        for p in services.proposals.values():
            stage: str | None = None
            if (
                p.status is ProposalStatus.PENDING
                and p.tier is ReleaseTier.RED
                and role is Role.HARDSHIP_SPECIALIST
            ):
                stage = "specialist"
            elif p.status is ProposalStatus.APPROVED and role in (Role.TEAM_LEAD, Role.COMPLIANCE):
                stage = "second_person"
            elif (
                p.status is ProposalStatus.PENDING and p.tier is ReleaseTier.GREEN and role is Role.TEAM_LEAD
            ):
                stage = "green_batch"
            elif (
                p.status is ProposalStatus.PENDING
                and p.tier is ReleaseTier.AMBER
                and role is Role.AGENT
                and customer(p.case_id).assigned_agent_id == user_id
            ):
                stage = "assigned_agent"
            if stage:
                who = first(p.proposal_id) if first else None
                out.append(ApprovalItem(stage=stage, proposal=p, first_approver=who[0] if who else None))  # type: ignore[arg-type]
        return sorted(out, key=lambda a: a.proposal.expires_at)

    @app.get("/audit", response_model=list[AuditEvent])
    def audit(
        user_id: str, role: Role, case_id: str | None = None, kind: AuditKind | None = None, limit: int = 200
    ) -> list[AuditEvent]:
        if case_id is not None:
            guard_case(case_id, user_id, role)
        elif role not in CASE_WIDE_ROLES:
            raise HTTPException(403, "only specialists, team leads and compliance see the whole log")
        events = services.audit_log.read(kind=kind)
        if case_id is not None:
            events = [e for e in events if e.subject_id == case_id or e.payload.get("case_id") == case_id]
        return list(reversed(events))[:limit]

    @app.post("/proposals/{proposal_id}/decision", response_model=ReleaseResult)
    def decide(proposal_id: str, decision: ReleaseDecision) -> ReleaseResult:
        if decision.proposal_id != proposal_id:
            raise HTTPException(422, "proposal_id in the body must match the path")
        return services.release_gate.release(decision, services.clock())  # server time decides expiry

    @app.post("/cases/{case_id}/notes", response_model=NBACard)
    @app.post("/demo/cases/{case_id}/notes", response_model=NBACard, include_in_schema=False)
    def add_note(case_id: str, note: NoteIn) -> NBACard:
        if services.add_note is None:
            raise HTTPException(503, "live extraction is not configured")
        guard_case(case_id, note.user_id, note.role)
        try:
            services.add_note(case_id, note.text, note.user_id, services.clock())
        except RuntimeError as e:  # the extraction model failed or timed out: nothing was stored
            raise HTTPException(502, str(e)) from None
        return card_for(case_id, services.clock())  # after extraction: the note is in the past

    @app.get("/cases/{case_id}/extractions", response_model=list[NoteExtraction])
    def case_extractions(case_id: str, user_id: str, role: Role) -> list[NoteExtraction]:
        if services.extractions is None:
            raise HTTPException(503, "extraction store not configured")
        guard_case(case_id, user_id, role)
        found = sorted(services.extractions.for_case(case_id), key=lambda x: x.extracted_at, reverse=True)
        text = services.note_text or (lambda _: None)
        return [NoteExtraction(note=text(x.source_id) or "", extraction=x) for x in found[:20]]

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        return services.ask.ask(request)  # Track B: CollectionsAsk does the work

    @app.get("/steward/queue", response_model=list[StewardItemOut])
    def steward_queue() -> list[StewardItemOut]:
        if services.steward is None:
            raise HTTPException(503, "steward queue not configured")
        return [
            StewardItemOut(
                item_id=i.item_id,
                left_key=f"{i.decision.pair.left.system.value}:{i.decision.pair.left.key}",
                right_key=f"{i.decision.pair.right.system.value}:{i.decision.pair.right.key}",
                score=i.decision.pair.score,
                reasons=list(i.reasons),
            )
            for i in services.steward.pending()
        ]

    @app.post("/steward/items/{item_id}")
    def steward_resolve(item_id: str, body: StewardVerdictIn) -> dict[str, str]:
        if services.steward is None:
            raise HTTPException(503, "steward queue not configured")
        try:
            verdict = StewardVerdict(body.verdict)
        except ValueError:
            raise HTTPException(422, f"verdict must be one of {[v.value for v in StewardVerdict]}") from None
        now = services.clock()
        try:
            services.steward.resolve(item_id, verdict, steward_id=body.steward_id, at=now)
        except KeyError:
            raise HTTPException(404, f"unknown item {item_id}") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        services.audit_log.append(
            AuditEvent(
                event_id=new_event_id(),
                at=now,
                kind=AuditKind.STEWARD_DECISION,
                actor_id=body.steward_id,
                actor_role=Role.DATA_STEWARD,
                subject_id=item_id,
                payload={"verdict": verdict.value},
            )
        )
        return {"status": "pending" if verdict is StewardVerdict.UNSURE else "resolved"}

    @app.post("/extractions/{source_id}/confirm", response_model=TextExtraction)
    def confirm_extraction(source_id: str, body: ExtractionConfirmIn) -> TextExtraction:
        if services.extractions is None:
            raise HTTPException(503, "extraction store not configured")
        x = services.extractions.get(source_id)
        if x is None:
            raise HTTPException(404, f"unknown extraction {source_id}")
        guard_case(x.case_id, body.agent_id, Role.AGENT)  # confirmed_by_agent_id: the assigned agent
        now = services.clock()
        try:
            confirmed = confirm(x, agent_id=body.agent_id, at=now, edits=body.edits)
        except ValueError as e:  # unknown field, or pydantic ValidationError on a bad value
            raise HTTPException(422, str(e)) from None
        services.extractions.put(confirmed)
        services.audit_log.append(
            AuditEvent(
                event_id=new_event_id(),
                at=now,
                kind=AuditKind.OVERRIDE,  # ponytail: no extraction-confirm kind in the shared contract
                actor_id=body.agent_id,
                actor_role=Role.AGENT,
                subject_id=x.case_id,
                payload={
                    "case_id": x.case_id,
                    "source_id": source_id,
                    "action": "extraction_confirm",
                    "edited_fields": sorted(body.edits),  # names only: values may be sensitive
                },
            )
        )
        return confirmed

    return app
