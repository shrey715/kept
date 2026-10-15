"""`kept score`: an NBA card for every open case (G3), written to nba.cards for the queue and
B's fairness report.

The same KeptContextBuilder and KeptEngine as the live API, fed by in-memory readers loaded in
bulk (gold, the feature table Feast serves, case rows, fresh or confirmed extractions), so each
card costs no database round trip. Audit events are buffered and written in one go at the end.
"""

from __future__ import annotations

import pickle
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from kept.common.audit import DuckDBAuditLog
from kept.common.db import connect
from kept.config import CENT, EXPORT_DIR
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import Action
from kept.contracts.feature_registry import model_inputs
from kept.contracts.features import FeatureVector, TextExtraction
from kept.contracts.identity import GoldenCustomer, SourceKey
from kept.contracts.nba import NBACard
from kept.data.c360_reader import _to_customer
from kept.features.drift import load_alarm
from kept.nba.context import CaseRow, KeptContextBuilder
from kept.nba.engine import KeptEngine
from kept.nba.promise_model import load_model
from kept.nba.uplift import TLearnerUplift
from kept.text.store import from_row

_CARDS_DDL = """
create schema if not exists nba;
create or replace table nba.cards (
    case_id varchar primary key, golden_customer_id varchar, assigned_agent_id varchar,
    display_name varchar, total_overdue decimal(18, 2), max_dpd integer, current_bucket varchar,
    scored_at timestamptz, features_as_of timestamptz, model_version varchar,
    action varchar, tier varchar, proposal_id varchar, headline varchar, no_action_reason varchar,
    p_paid_14d double, p_wait double, expected_value decimal(18, 2),
    hardship boolean, hard_stop boolean, is_legacy_strategy boolean, card json
)"""


class _Bulk:
    """C360Reader + FeatureProvider + ExtractionStore over dicts loaded once."""

    def __init__(
        self,
        customers: dict[str, GoldenCustomer],
        vectors: dict[str, FeatureVector],
        cases: dict[str, CaseRow],
        notes: dict[str, list[TextExtraction]],
    ) -> None:
        self.customers, self.vectors, self.cases, self.notes = customers, vectors, cases, notes

    def customer_for_case(self, case_id: str) -> GoldenCustomer:
        return self.customers[case_id]

    def get_customer(self, golden_customer_id: str) -> GoldenCustomer:
        raise NotImplementedError("scoring reads customers by case")

    def resolve(self, key: SourceKey) -> str | None:
        raise NotImplementedError("scoring reads customers by case")

    def get_online(self, case_id: str) -> FeatureVector:
        return self.vectors[case_id]

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("scoring reads the latest features")

    def case_row(self, case_id: str) -> CaseRow:
        return self.cases[case_id]

    def for_case(self, case_id: str) -> Sequence[TextExtraction]:
        return self.notes.get(case_id, [])

    def get(self, source_id: str) -> TextExtraction | None:
        raise NotImplementedError("read only")

    def put(self, extraction: TextExtraction) -> None:
        raise NotImplementedError("read only")


def _key(values: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(None if v is None or (isinstance(v, float) and v != v) else v for v in values)


class _Precomputed:
    """The uplift model's answers for every case in one batch (vectorised LightGBM), looked up by
    the row of model inputs the engine passes for each card. A row it hasn't seen goes to the
    model, so the cards are the same either way (test_score checks)."""

    def __init__(self, model: TLearnerUplift, vectors: Sequence[FeatureVector]) -> None:
        self.model_version = model.model_version
        self._model = model
        names = model_inputs()
        self._frame = pd.DataFrame([{n: d.get(n) for n in names} for d in (v.model_dump() for v in vectors)])
        self._row = {_key(r): i for i, r in enumerate(self._frame.itertuples(index=False))}
        self._proba = model.predict_proba(self._frame).reset_index(drop=True)
        self._contrib: dict[Action, Any] = {}

    def _find(self, features: pd.DataFrame) -> int | None:
        return (
            self._row.get(_key(features[self._frame.columns].iloc[0].tolist()))
            if len(features) == 1
            else None
        )

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        i = self._find(features)
        if i is None:
            return self._model.predict_proba(features)
        return self._proba.iloc[[i]].set_index(features.index)

    def contributions(
        self, row: pd.DataFrame, action: Action, *, baseline: Action = Action.WAIT
    ) -> dict[str, float]:
        i = self._find(row)
        if i is None or baseline is not Action.WAIT:
            return self._model.contributions(row, action, baseline=baseline)
        if action not in self._contrib:
            self._contrib[action] = self._model.contributions_many(self._frame, action)
        columns = self._model._columns  # what the model was trained on, in its order
        return {c: float(v) for c, v in zip(columns, self._contrib[action][i], strict=True)}


class _NoStore(dict):  # type: ignore[type-arg]
    """The proposal store for a batch run: cards go to nba.cards, so nothing is kept here and
    the engine's per-card cancel_pending scan stays O(1) instead of growing with every card."""

    def __setitem__(self, key: object, value: object) -> None:
        pass


class _Buffer:
    """AuditLog that keeps events in memory until the run writes them in one go."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    def read(
        self, *, kind: AuditKind | None = None, subject_id: str | None = None, since: datetime | None = None
    ) -> Sequence[AuditEvent]:
        return [
            e
            for e in self.events
            if (kind is None or e.kind is kind) and (subject_id is None or e.subject_id == subject_id)
        ]

    def latest(
        self, *, kind: AuditKind | None = None, case_id: str | None = None, limit: int = 200
    ) -> Sequence[AuditEvent]:
        hits = [
            e
            for e in self.read(kind=kind)
            if case_id is None or case_id in (e.subject_id, e.payload.get("case_id"))
        ]
        return hits[::-1][:limit]


def load(conn: duckdb.DuckDBPyConnection) -> _Bulk:
    """Every case in the latest features.case_features (the cases open at the nightly as_of)."""
    cur = conn.execute(
        "select * from features.case_features where as_of = (select max(as_of) from features.case_features)"
    )
    names = [d[0] for d in cur.description]
    vectors = {}
    for r in cur.fetchall():
        row = dict(zip(names, r, strict=True))
        as_of = row.pop("as_of").replace(tzinfo=UTC)  # naive UTC in the table
        vectors[row["case_id"]] = FeatureVector(
            as_of=as_of, **{k: v for k, v in row.items() if k in FeatureVector.model_fields}
        )
    cur = conn.execute(
        "select c.case_id, g.* from silver.collections_cases c "
        "join gold.identity_crosswalk x on x.source_system = 'collections' "
        "and x.source_key = c.coll_customer_ref and x.valid_to is null "
        "join gold.c360_customer g using (golden_customer_id) "
        "join features.case_features f on f.case_id = c.case_id "
        "and f.as_of = (select max(as_of) from features.case_features)"
    )
    names = [d[0] for d in cur.description]
    customers = {}
    for r in cur.fetchall():
        row = dict(zip(names, r, strict=True))
        case_id = str(row.pop("case_id"))
        customers[case_id] = _to_customer(row)
    cases = {
        cid: CaseRow(
            case_id=cid,
            total_overdue=Decimal(str(overdue or 0)).quantize(CENT),
            contact_cap_7d=cap,
            nba_recommendation_last=legacy,
            cease_contact_flag=bool(cease),
            insolvency_hold_flag=bool(insolvency),
            deceased_hold_flag=bool(deceased),
            hardship_plan_start=plan_start,
            hardship_plan_end=plan_end,
        )
        for cid, overdue, cap, legacy, cease, insolvency, deceased, plan_start, plan_end in conn.execute(
            "select case_id, total_overdue, contact_cap_7d, nba_recommendation_last, cease_contact_flag,"
            " insolvency_hold_flag, deceased_hold_flag, hardship_plan_start, hardship_plan_end"
            " from silver.collections_cases c"
            " semi join features.case_features f on f.case_id = c.case_id"
        ).fetchall()
        if cid in vectors
    }
    # only what the context builder can use: confirmed notes, and live notes since the features
    notes: dict[str, list[TextExtraction]] = defaultdict(list)
    has_store = conn.execute(
        "select count(*) from duckdb_tables() where schema_name = 'text' and table_name = 'extractions'"
    ).fetchone()
    if has_store and has_store[0]:
        for r in conn.execute(
            "select * from text.extractions where (confirmed_by_agent_id is not null "
            "or extractor not like 'setfit:%') order by extracted_at desc"
        ).fetchall():
            x = from_row(r)
            if x.case_id in vectors:
                notes[x.case_id].append(x)
    return _Bulk(customers, vectors, cases, dict(notes))


def score(
    warehouse: Path | str, *, model: Path, holdout_salt: str, now: datetime, audit_log: DuckDBAuditLog
) -> pd.DataFrame:
    """Score every open case and write nba.cards. Returns the cards table."""
    with duckdb.connect(str(warehouse), read_only=True) as conn:
        bulk = load(conn)
    buffer = _Buffer()
    context = KeptContextBuilder(
        c360=bulk, features=bulk, cases=bulk.case_row, holdout_salt=holdout_salt, extractions=bulk
    )
    engine = KeptEngine(
        context=context,
        features=bulk,
        scorer=_Precomputed(
            pickle.loads(model.read_bytes()), list(bulk.vectors.values())
        ),  # kept train's file
        audit_log=buffer,
        proposals=_NoStore(),
        drift_alarm=load_alarm(EXPORT_DIR / "features"),
        promise_model=load_model(EXPORT_DIR / "models" / "promise.pkl"),
    )
    rows = [
        _row(engine.recommend(case_id, now), bulk.customers[case_id], now)
        for case_id in sorted(bulk.customers)
    ]
    cards = pd.DataFrame(rows)
    with connect(warehouse) as c:  # one write at the end (K5)
        c.execute(_CARDS_DDL)
        c.register("cards", cards)
        c.execute("insert into nba.cards select * from cards")
    audit_log.append_many(buffer.events)
    return cards


def _row(card: NBACard, customer: GoldenCustomer, now: datetime) -> dict[str, Any]:
    p = card.proposal
    probs = {a.action: a.p_paid_14d for a in card.probabilities}
    wait = probs.get(Action.WAIT)
    best = probs.get(p.action) if p else None
    lift = (best - wait) if p and best is not None and wait is not None else 0.0
    return {
        "case_id": card.case_id,
        "golden_customer_id": card.golden_customer_id,
        "assigned_agent_id": customer.assigned_agent_id,
        "display_name": customer.display_name,
        "total_overdue": customer.total_overdue,
        "max_dpd": customer.max_dpd,
        "current_bucket": customer.current_bucket.value,
        "scored_at": now,
        "features_as_of": card.features_as_of,
        "model_version": card.model_version,
        "action": p.action.value if p else None,
        "tier": p.tier.value if p else None,
        "proposal_id": p.proposal_id if p else None,
        "headline": card.headline,
        "no_action_reason": card.no_action_reason,
        "p_paid_14d": best,
        "p_wait": wait,
        "expected_value": (Decimal(str(max(lift, 0.0))) * customer.total_overdue).quantize(CENT),
        "hardship": card.hardship_banner is not None,
        "hard_stop": bool(card.hard_stop and card.hard_stop.blocked),
        "is_legacy_strategy": bool(p and p.is_legacy_strategy),
        "card": card.model_dump_json(),
    }
