"""CaseContextBuilder (S3) over the C360 reader, online features and the case row."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest

from kept.contracts import Action, FeatureVector, GoldenCustomer, HardshipSignal, HardshipStatus, HardStop
from kept.contracts.interfaces import CaseContextBuilder
from kept.nba.context import CaseRow, KeptContextBuilder, duckdb_case_reader
from tests.fakes import DictC360Reader, StaticFeatureProvider

pytestmark = pytest.mark.track_d
CASE = "C-118204"


@pytest.fixture
def build(make_customer: Callable[..., GoldenCustomer], now_utc: datetime) -> Callable[..., Any]:
    def _build(customer: dict[str, Any] | None = None, case: dict[str, Any] | None = None, **fv: Any):  # type: ignore[no-untyped-def]
        c = make_customer(**(customer or {}))
        vec = FeatureVector(
            case_id=CASE,
            golden_customer_id=c.golden_customer_id,
            as_of=now_utc - timedelta(hours=16),
            feature_set_version="fs-0.1",
            **{"contacts_last_7d": 1, **fv},
        )
        rows = {CASE: CaseRow(case_id=CASE, total_overdue=Decimal("420.00"), **(case or {}))}
        builder = KeptContextBuilder(
            c360=DictC360Reader(customers={c.golden_customer_id: c}),
            features=StaticFeatureProvider(vectors={CASE: vec}),
            cases=lambda cid: rows[cid],
            holdout_salt="test",
        )
        return builder.build(CASE, now_utc)

    return _build


def test_is_a_context_builder() -> None:
    b = KeptContextBuilder(
        c360=DictC360Reader(),
        features=StaticFeatureProvider(),
        cases=lambda c: (_ for _ in ()).throw(KeyError(c)),
        holdout_salt="s",
    )
    assert isinstance(b, CaseContextBuilder)
    with pytest.raises(KeyError):
        b.build("nope", datetime.now().astimezone())


def test_plain_case(build: Callable[..., Any], now_utc: datetime) -> None:
    ctx = build()
    assert ctx.case_id == CASE and ctx.golden_customer_id == "G-004817" and ctx.assigned_agent_id == "agent-7"
    assert ctx.time_zone == "America/Toronto" and ctx.contacts_last_7d == 1 and ctx.contact_cap_7d == 3
    assert ctx.hard_stop_flags == frozenset() and ctx.hardship_status is HardshipStatus.NONE
    assert ctx.balance_at_risk == Decimal("420.00") and ctx.now == now_utc
    assert ctx.features_as_of == now_utc - timedelta(hours=16)


@pytest.mark.parametrize(
    "case,fv,stops",
    [
        ({"cease_contact_flag": True}, {}, {HardStop.CEASE}),
        ({}, {"cease_request_flag": True}, {HardStop.CEASE}),  # text extraction from a fresh note
        ({"insolvency_hold_flag": True}, {}, {HardStop.INSOLVENCY}),
        ({"deceased_hold_flag": True}, {}, {HardStop.DECEASED}),
    ],
)
def test_hard_stops(
    build: Callable[..., Any], case: dict[str, Any], fv: dict[str, Any], stops: set[HardStop]
) -> None:
    assert build(case=case, **fv).hard_stop_flags == stops


def test_gold_hold_without_detail_still_blocks(build: Callable[..., Any]) -> None:
    assert build(customer={"collections_hold": True}).hard_stop_flags == {HardStop.INSOLVENCY}
    ctx = build(customer={"collections_hold": True}, case={"deceased_hold_flag": True})
    assert ctx.hard_stop_flags == {HardStop.DECEASED}


@pytest.mark.parametrize("signal", [HardshipSignal.POSSIBLE, HardshipSignal.CLEAR])
def test_fresh_text_signal_protects_before_gold_catches_up(
    build: Callable[..., Any], signal: HardshipSignal
) -> None:
    assert build(hardship_signal=signal).hardship_status is HardshipStatus.POSSIBLE


def test_text_never_lowers_gold_hardship(build: Callable[..., Any]) -> None:
    ctx = build(customer={"hardship_status": HardshipStatus.CONFIRMED}, hardship_signal=HardshipSignal.NONE)
    assert ctx.hardship_status is HardshipStatus.CONFIRMED


def test_unknowns_fail_closed(build: Callable[..., Any]) -> None:
    ctx = build(customer={"time_zone": None}, case={"contact_cap_7d": 2}, contacts_last_7d=None)
    assert ctx.time_zone == "" and ctx.contacts_last_7d == ctx.contact_cap_7d == 2


def test_customer_window_vulnerability_and_legacy(build: Callable[..., Any]) -> None:
    ctx = build(
        customer={
            "permitted_call_start_local": time(9),
            "permitted_call_end_local": time(17),
            "vulnerability_flag": True,
        },
        case={"nba_recommendation_last": "call_evening"},
    )
    assert (ctx.permitted_call_start_local, ctx.permitted_call_end_local) == (time(9), time(17))
    assert ctx.vulnerable and ctx.legacy_action is Action.CALL


def test_duckdb_case_reader(tmp_path: Path) -> None:
    db = tmp_path / "kept.duckdb"
    with duckdb.connect(str(db)) as c:
        c.execute("create schema silver")
        c.execute("""create table silver.collections_cases as select 'CS-1' as case_id, 1617.643 as total_overdue,
                     2 as contact_cap_7d, 'sms_payment_link' as nba_recommendation_last, false as cease_contact_flag,
                     true as insolvency_hold_flag, null::boolean as deceased_hold_flag""")
    row = duckdb_case_reader(db)("CS-1")
    assert row == CaseRow("CS-1", Decimal("1617.64"), 2, "sms_payment_link", False, True, False)
    with pytest.raises(KeyError):
        duckdb_case_reader(db)("CS-2")
