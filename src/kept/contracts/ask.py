"""Collections Ask contracts (Layer 2 -> app/UI)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kept.config import ASK_DEFAULT_ROW_LIMIT, ASK_SQL_TIMEOUT_S
from kept.contracts.enums import Role


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AskRequest(_Frozen):
    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    user_id: str
    role: Role
    own_case_ids: frozenset[str] = frozenset()  # agents may only ask about their own queue
    clarification_round: int = Field(default=0, ge=0)


class RefusalReason(StrEnum):
    PROTECTED_ATTRIBUTE = "protected_attribute"
    BULK_PERSONAL_DATA = "bulk_personal_data"
    WRITE_ACTION = "write_action"
    OTHER_PEOPLES_CASES = "other_peoples_cases"
    DATA_UNAVAILABLE = "data_unavailable"
    LOW_CONFIDENCE = "low_confidence"
    SQL_GUARD = "sql_guard"
    SMALL_GROUP = "small_group"  # analyst aggregate under 10


class ScopeDecision(_Frozen):
    in_scope: bool
    reason: RefusalReason | None = None
    offending_terms: tuple[str, ...] = ()  # e.g. ("gender_code",)
    decided_by: Literal["rules", "classifier"]


class IntentKind(StrEnum):
    METRIC = "metric"  # certified definition from metric_definitions; SQL is compiled
    LOOKUP = "lookup"  # 3 LLM-written SQL candidates, majority result
    POLICY = "policy"  # LanceDB search over current policy documents


class Intent(_Frozen):
    """Router output: shown to the user as editable chips."""

    kind: IntentKind
    metric_id: str | None = None
    filters: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    group_by: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class SqlPolicy(_Frozen):
    allowed_tables: frozenset[str]  # schema-qualified, lower case, e.g. "gold.c360_customer"
    blocked_columns: frozenset[str]  # protected + direct PII, lower case
    # columns of each allowed table, lower case. SELECT * / t.* is refused over a table that has a
    # blocked column or whose columns are not listed here (fail closed).
    table_columns: dict[str, frozenset[str]] = Field(default_factory=dict)
    max_rows: int = Field(default=ASK_DEFAULT_ROW_LIMIT, gt=0)
    timeout_s: float = Field(default=ASK_SQL_TIMEOUT_S, gt=0)
    dialect: str = "duckdb"


class GuardResult(_Frozen):
    allowed: bool
    sql: str | None  # rewritten SQL (row limit applied) when allowed
    reason: str | None = None
    tables: frozenset[str] = frozenset()
    columns: frozenset[str] = frozenset()


class Citation(_Frozen):
    document_id: str
    section: str
    effective_from: date
    snippet: str  # verbatim from the source, so GET /ask/source can find and highlight it
    kind: Literal["policy", "transcript"] = "policy"
    ref: int = 0  # the [n] tag, 1-based, in the order the answer leans on them
    used: bool = True  # the answer names this source; False = retrieved, but the answer doesn't rely on it
    mention: str | None = None  # the exact words in the narrative that cite it ("POL-COLL-001 §7.3")
    source_id: str | None = None  # a transcript's text.redacted_notes source_id


class SourceText(_Frozen):
    """A cited source in full, with the cited passage located in it: the "verify" view of a citation."""

    title: str
    text: str
    highlight_start: int | None = None  # None when the snippet is no longer in the source
    highlight_end: int | None = None
    effective_from: date | None = None
    effective_to: date | None = None  # None = still current


class AskAnswer(_Frozen):
    kind: Literal["answer"] = "answer"
    question: str
    intent: Intent
    sql: str | None  # every answer shows the SQL ...
    tables_used: tuple[str, ...]  # ... the tables used ...
    data_freshness: datetime | None  # ... and data freshness
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    narrative: str  # numbers only from rows
    citations: tuple[Citation, ...] = ()


class Refusal(_Frozen):
    kind: Literal["refusal"] = "refusal"
    reason: RefusalReason
    message: str  # "This needs gender_code, which is excluded from collections analytics."
    suggestion: str | None = None  # "Try: <nearest allowed question>"


class Clarification(_Frozen):
    kind: Literal["clarification"] = "clarification"
    question: str
    intent: Intent | None = None


AskResponse = Annotated[AskAnswer | Refusal | Clarification, Field(discriminator="kind")]
