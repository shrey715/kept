"""Real services for `kept serve` (Track D, S6): A's golden records, D's features (Feast) and
uplift model, C's extraction store and live extraction, B's Ask.

The API process holds one read-write connection to the warehouse and every reader takes a cursor
from it. DuckDB refuses a read-only and a read-write connection to one file in the same process,
and C's store and live extraction write; one connection also saves ~60 ms of connect per read.
The API owns the file while it runs (K5: no batch jobs against the warehouse it serves).
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import duckdb

from kept.app.api import QueueItem, Services
from kept.app.history import case_history
from kept.app.notifications import ReadState
from kept.app.voice import VoiceCalls
from kept.common.audit import DuckDBAuditLog
from kept.common.db import connect
from kept.config import EXPORT_DIR, RAW_DIR, REPO_ROOT, WAREHOUSE_PATH
from kept.contracts.enums import Action, HardshipSignal, HardshipStatus, HardStop, ReleaseTier, Role
from kept.contracts.interfaces import AuditLog
from kept.contracts.nba import CaseContext, ProposalStatus
from kept.data.c360_reader import DuckDBC360Reader
from kept.data.identity.steward import load_steward_queue
from kept.features.drift import load_alarm
from kept.features.store import FeastFeatureProvider
from kept.governance.access import mask_name
from kept.hardship.programs import HardshipProgram, ProgramCase, eligible_programs
from kept.nba.context import KeptContextBuilder, duckdb_case_reader
from kept.nba.engine import KeptEngine
from kept.nba.promise_model import load_model
from kept.nba.release import Releaser
from kept.text.store import DuckDBExtractionStore


class SharedC360Reader(DuckDBC360Reader):
    """A's reader, through a cursor on the API's connection instead of a read-only one per call."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        super().__init__()
        self._conn = conn

    def _query(self, sql: str, params: list[str]) -> list[dict[str, object]]:
        with self._conn.cursor() as c:
            cursor = c.execute(sql, params)
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def real_services(
    *,
    warehouse: Path = WAREHOUSE_PATH,
    feature_repo: Path = REPO_ROOT / "feature_repo",
    model: Path = EXPORT_DIR / "models" / "uplift.pkl",
) -> Services:
    """Needs a built warehouse (kept build), materialised features (kept features) and a trained
    model (kept train). Live extraction needs C's text extra (Presidio); without it the card's
    add-note path answers 503 and everything else works."""
    conn = connect(warehouse)
    audit_log = DuckDBAuditLog(os.environ.get("KEPT_AUDIT_LOG_PATH", str(warehouse.parent / "audit.duckdb")))
    c360 = SharedC360Reader(conn)
    features = FeastFeatureProvider(feature_repo)
    store = DuckDBExtractionStore(warehouse)
    context = KeptContextBuilder(
        c360=c360,
        features=features,
        cases=duckdb_case_reader(warehouse, conn=conn),
        holdout_salt=os.environ["KEPT_HOLDOUT_SALT"],
        extractions=store,
    )
    proposals: dict = {}  # type: ignore[type-arg]
    engine = KeptEngine(
        context=context,
        features=features,
        scorer=pickle.loads(model.read_bytes()),  # our own file, written by kept train
        audit_log=audit_log,
        proposals=proposals,
        programs=_programs(conn),
        drift_alarm=load_alarm(EXPORT_DIR / "features"),
        promise_model=load_model(EXPORT_DIR / "models" / "promise.pkl"),
    )
    typed: dict[str, str] = {}  # notes typed in this session: source_id -> text

    def note_text(source_id: str) -> str | None:
        if source_id in typed:
            return typed[source_id]
        with conn.cursor() as c:
            row = c.execute(
                "select note_text from silver.agent_notes where note_id = ?", [source_id]
            ).fetchone()
        return row[0] if row else None

    from kept.app.charts import ChartChoice, ChartRequest, choose_chart
    from kept.ask.service import build_ask

    ask = build_ask(conn.cursor(), audit_log)
    # ponytail: the chart picker borrows the Ask's gateway and redactor (one Presidio in memory) without
    # changing how the Ask is built; give build_ask an llm/redactor argument pair once #100 is integrated.
    llm, redactor = getattr(ask, "_llm", None), getattr(ask, "_redactor", None)

    def chart(request: ChartRequest) -> ChartChoice:
        return choose_chart(request, llm=llm, redactor=redactor)

    return Services(
        engine=engine,
        release_gate=Releaser(proposals=proposals, context=context, audit_log=audit_log),
        ask=ask,
        c360=c360,
        audit_log=audit_log,
        proposals=proposals,
        add_note=_live_extraction(warehouse, audit_log, typed),
        extractions=store,
        note_text=note_text,
        steward=load_steward_queue(warehouse=warehouse),
        scored_queue=_scored_queue(conn),
        chart=chart,
        calls=VoiceCalls(  # the voice pack's files/voice next to the release's files/transcripts
            EXPORT_DIR / "voice" / "voice_extractions.parquet",
            Path(os.environ.get("KEPT_VOICE_DIR", RAW_DIR / "files" / "voice")),
        ),
        history=lambda case_id: case_history(conn, case_id),
        reads=ReadState(warehouse.parent / "app_state.duckdb"),  # not the warehouse: kept score writes that
    )


def _live_extraction(warehouse: Path, audit_log: AuditLog, typed: dict[str, str]):  # type: ignore[no-untyped-def]
    """The card's add-note path: C's live extraction, redactor and model built once here (about
    5 s a note warm vs 12 s built per call). None without C's text extra installed."""
    try:
        from kept.text.redact import PresidioRedactor
    except ImportError:
        print("kept serve: Presidio is not installed (make setup-c), so notes can't be added")
        return None
    from kept.common.llm import LiteLLMGateway
    from kept.text.live import DEFAULT_MODEL, extract_into, typed_note

    redactor = PresidioRedactor()
    llm = LiteLLMGateway(
        model=os.environ.get("KEPT_TEXT_LLM_MODEL", DEFAULT_MODEL), audit_log=audit_log, timeout_s=120
    )

    def add(case_id: str, text: str, user_id: str, now: object) -> None:
        source = typed_note(text, case_id=case_id)
        (result,) = extract_into(warehouse, [source], redactor=redactor, llm=llm)
        if result.extraction is None:
            raise RuntimeError(f"extraction failed: {result.error}")
        typed[source.source_id] = text

    return add


def _scored_queue(conn: duckdb.DuckDBPyConnection):  # type: ignore[no-untyped-def]
    """/queue from `kept score`'s nba.cards: an agent's own cases, other roles the top 500, best
    first. Names masked for every role but compliance (governance.access.masked_view's rule)."""

    def queue(user_id: str, role: Role) -> list[QueueItem]:
        where, params = ("where assigned_agent_id = ?", [user_id]) if role is Role.AGENT else ("", [])
        with conn.cursor() as c:
            if not c.execute(
                "select count(*) from duckdb_tables() where schema_name = 'nba' and table_name = 'cards'"
            ).fetchone()[0]:  # type: ignore[index]
                return []  # kept score hasn't run
            rows = c.execute(
                "select case_id, golden_customer_id, display_name, total_overdue, max_dpd, current_bucket,"
                " headline, action, tier, expected_value, hardship, hard_stop, no_action_reason"
                f" from nba.cards {where} order by action is null, expected_value desc, case_id limit 500",
                params,
            ).fetchall()
        return [
            QueueItem(
                case_id=r[0],
                golden_customer_id=r[1],
                display_name=r[2] if role is Role.COMPLIANCE else mask_name(r[2]),
                total_overdue=r[3],
                max_dpd=r[4],
                current_bucket=r[5],
                headline=r[6],
                action=Action(r[7]) if r[7] else None,
                tier=ReleaseTier(r[8]) if r[8] else None,
                proposal_status=ProposalStatus.PENDING if r[7] else None,
                expected_value=r[9],
                hardship=r[10],
                hard_stop=r[11],
                no_action_reason=r[12],
            )
            for r in rows
        ]

    return queue


_LEVEL = {HardshipStatus.NONE: HardshipSignal.NONE, HardshipStatus.POSSIBLE: HardshipSignal.POSSIBLE,
          HardshipStatus.CONFIRMED: HardshipSignal.CLEAR}  # fmt: skip


def _programs(conn: duckdb.DuckDBPyConnection):  # type: ignore[no-untyped-def]
    """C's eligible_programs for the hardship banner: the hardship_programs table loaded once, the
    case's facts read per card. ponytail: uses in the last 12 months = hardship plans the
    customer's cases started in 12 months; a broken plan = a broken promise in 90 days."""
    import json

    with conn.cursor() as c:
        programs = [
            HardshipProgram(
                program_id=r[0],
                version=r[1],
                program_name=r[2],
                product_types=frozenset(json.loads(r[3])),
                policy_section=r[4] or "",
                min_hardship_level=HardshipSignal(r[5]),
                max_dpd=r[6],
                min_months_on_book=r[7],
                max_uses_12m=r[8],
                excludes_insolvency=bool(r[9]),
                excludes_broken_plan_90d=bool(r[10]),
                requires_income_evidence=bool(r[11]),
                payment_reduction_pct=r[12],
                duration_months=r[13],
                approver_level=Role(r[14]),
                effective_from=r[15],
                effective_to=r[16],
            )
            for r in c.execute(
                "select program_id, version, program_name, product_types, policy_section, min_hardship_level,"
                " max_dpd, min_months_on_book, max_uses_12m, excludes_insolvency, excludes_broken_plan_90d,"
                " requires_income_evidence, payment_reduction_pct, duration_months, approver_level,"
                " effective_from, effective_to from silver.hardship_programs"
            ).fetchall()
        ]

    def names(ctx: CaseContext) -> list[str]:
        today = ctx.now.date()
        with conn.cursor() as c:
            row = c.execute(
                """select c.primary_product, coalesce(c.current_dpd, 0),
                       coalesce(ca.months_on_book,
                                date_diff('month', coalesce(la.origination_date, da.open_date), ?), 0),
                       (select count(*) from silver.collections_cases p
                        where p.coll_customer_ref = c.coll_customer_ref
                          and p.hardship_plan_start > ? - interval 12 month),
                       exists (select 1 from silver.promises_to_pay b
                               where b.crm_customer_id = c.coll_customer_ref
                                 and b.ptp_status = 'broken' and b.ptp_due_date > ? - interval 90 day)
                   from silver.collections_cases c
                   left join silver.card_accounts ca on ca.card_account_id = c.primary_account_id
                   left join silver.loan_accounts la on la.loan_id = c.primary_account_id
                   left join silver.deposit_accounts da on da.deposit_account_id = c.primary_account_id
                   where c.case_id = ?""",
                [today, today, today, ctx.case_id],
            ).fetchone()
        if row is None:
            return []
        product, dpd, months, uses, broken = row
        level = _LEVEL[ctx.hardship_status]
        if ctx.vulnerable and level is HardshipSignal.NONE:
            level = HardshipSignal.POSSIBLE
        case = ProgramCase(
            product_type=product,
            hardship_level=level,
            dpd=int(dpd),
            months_on_book=int(months),
            uses_last_12m=int(uses),
            broken_plan_90d=bool(broken),
            insolvency=bool(ctx.hard_stop_flags & {HardStop.INSOLVENCY, HardStop.BANKRUPTCY}),
        )
        eligible = eligible_programs(case, programs, as_of=today)
        return [f"{p.program_name} ({p.program_id} {p.version})" for p in eligible]

    return names
