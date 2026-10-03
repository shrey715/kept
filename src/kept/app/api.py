"""HTTP API. Route owners: /cases + /proposals (D), /ask (B), /steward (A), /extractions (C).

The route signatures are the contract for the UI. Services are injected so tests
(and the demo) can swap in fakes. Handlers are stubs.

Auth is out of scope for the hackathon: the caller passes user_id and role, and
every handler applies kept.governance.access before returning data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI
from pydantic import BaseModel

from kept import __version__
from kept.contracts.ask import AskRequest, AskResponse
from kept.contracts.enums import Role
from kept.contracts.features import TextExtraction
from kept.contracts.interfaces import AskService, AuditLog, C360Reader, NBAEngine, ReleaseGate
from kept.contracts.nba import NBACard, ReleaseDecision, ReleaseResult


@dataclass(frozen=True, slots=True)
class Services:
    engine: NBAEngine
    release_gate: ReleaseGate
    ask: AskService
    c360: C360Reader
    audit_log: AuditLog


class HealthResponse(BaseModel):
    status: str
    version: str


class StewardItemOut(BaseModel):
    item_id: str
    left_key: str
    right_key: str
    score: float
    reasons: list[str]


class StewardVerdictIn(BaseModel):
    verdict: str
    steward_id: str


class ExtractionConfirmIn(BaseModel):
    agent_id: str
    edits: dict[str, object] = {}


def create_app(services: Services) -> FastAPI:
    """Routes and their contracts:

    GET  /health                                  200 HealthResponse
    GET  /cases/{case_id}/nba?user_id&role[&now]  200 NBACard; 403 if access.can_view_case is
                                                  False; 404 unknown case
    POST /proposals/{proposal_id}/decision        200 ReleaseResult; 422 if body.proposal_id
                                                  differs from the path
    POST /ask                                     200 AskAnswer | Refusal | Clarification
    GET  /steward/queue                           200 list[StewardItemOut]
    POST /steward/items/{item_id}                 200 {"status": ...}; 404 unknown item
    POST /extractions/{source_id}/confirm         200 TextExtraction
    """
    app = FastAPI(title="Kept", version=__version__)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/cases/{case_id}/nba", response_model=NBACard)
    def get_nba(case_id: str, user_id: str, role: Role, now: datetime | None = None) -> NBACard:
        raise NotImplementedError("Track D")

    @app.post("/proposals/{proposal_id}/decision", response_model=ReleaseResult)
    def decide(proposal_id: str, decision: ReleaseDecision) -> ReleaseResult:
        raise NotImplementedError("Track D")

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        raise NotImplementedError("Track B")

    @app.get("/steward/queue", response_model=list[StewardItemOut])
    def steward_queue() -> list[StewardItemOut]:
        raise NotImplementedError("Track A")

    @app.post("/steward/items/{item_id}")
    def steward_resolve(item_id: str, body: StewardVerdictIn) -> dict[str, str]:
        raise NotImplementedError("Track A")

    @app.post("/extractions/{source_id}/confirm", response_model=TextExtraction)
    def confirm_extraction(source_id: str, body: ExtractionConfirmIn) -> TextExtraction:
        raise NotImplementedError("Track C")

    return app
