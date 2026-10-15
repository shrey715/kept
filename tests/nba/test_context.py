"""CaseContextBuilder (S3) over the C360 reader, online features and the case row."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
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
                     true as insolvency_hold_flag, null::boolean as deceased_hold_flag,
                     date '2026-09-01' as hardship_plan_start, date '2026-12-01' as hardship_plan_end""")
    row = duckdb_case_reader(db)("CS-1")
    assert row == CaseRow(
        "CS-1",
        Decimal("1617.64"),
        2,
        "sms_payment_link",
        False,
        True,
        False,
        date(2026, 9, 1),
        date(2026, 12, 1),
    )
    with pytest.raises(KeyError):
        duckdb_case_reader(db)("CS-2")


# ----------------------------------------------------------------- fresh notes and gold hard stops
def _extraction(
    source_id: str,
    at: datetime,
    *,
    signal: str = "none",
    cease: bool = False,
    confirmed: str | None = None,
    extractor: str = "llm:test",
):  # type: ignore[no-untyped-def]
    from kept.contracts.features import TextExtraction

    def v(value, conf=0.9):  # type: ignore[no-untyped-def]
        return {"value": value, "evidence": None, "confidence": conf}

    return TextExtraction.model_validate(
        {
            "source_id": source_id,
            "case_id": CASE,
            "hardship_signal": v(signal),
            "stated_reason": v("none"),
            "promise_intent": v(False),
            "promised_date": v(None),
            "promised_amount": v(None),
            "dispute": v(False),
            "cease_request": v(cease),
            "third_party_present": v(False),
            "extractor": extractor,
            "extracted_at": at,
            "confirmed_by_agent_id": confirmed,
        }
    )


def _with_store(make_customer, now_utc, rows, **customer):  # type: ignore[no-untyped-def]
    from tests.fakes import InMemoryExtractionStore

    store = InMemoryExtractionStore()
    for r in rows:
        store.put(r)
    c = make_customer(**customer)
    vec = FeatureVector(
        case_id=CASE,
        golden_customer_id=c.golden_customer_id,
        as_of=now_utc - timedelta(hours=16),
        feature_set_version="fs-0.1",
        contacts_last_7d=1,
    )
    builder = KeptContextBuilder(
        c360=DictC360Reader(customers={c.golden_customer_id: c}),
        features=StaticFeatureProvider(vectors={CASE: vec}),
        cases=lambda cid: CaseRow(case_id=cid, total_overdue=Decimal("420.00")),
        holdout_salt="t",
        extractions=store,
    )
    return builder.build(CASE, now_utc)


def test_a_fresh_note_flips_hardship_before_the_nightly_build(make_customer, now_utc) -> None:  # type: ignore[no-untyped-def]
    ctx = _with_store(
        make_customer, now_utc, [_extraction("N-1", now_utc - timedelta(minutes=5), signal="possible")]
    )
    assert ctx.hardship_status is HardshipStatus.POSSIBLE


def test_an_agent_confirmed_note_makes_hardship_confirmed(make_customer, now_utc) -> None:  # type: ignore[no-untyped-def]
    ctx = _with_store(
        make_customer,
        now_utc,
        [_extraction("N-1", now_utc - timedelta(minutes=5), signal="clear", confirmed="agent-7")],
    )
    assert ctx.hardship_status is HardshipStatus.CONFIRMED


def test_notes_never_lower_gold_and_future_notes_are_ignored(make_customer, now_utc) -> None:  # type: ignore[no-untyped-def]
    ctx = _with_store(
        make_customer,
        now_utc,
        [_extraction("N-1", now_utc - timedelta(minutes=5))],
        hardship_status=HardshipStatus.CONFIRMED,
    )
    assert ctx.hardship_status is HardshipStatus.CONFIRMED
    later = _with_store(
        make_customer, now_utc, [_extraction("N-2", now_utc + timedelta(minutes=5), signal="clear")]
    )
    assert later.hardship_status is HardshipStatus.NONE


def test_text_cease_needs_agent_confirmation(make_customer, now_utc) -> None:  # type: ignore[no-untyped-def]
    at = now_utc - timedelta(minutes=5)
    assert (
        HardStop.CEASE
        not in _with_store(make_customer, now_utc, [_extraction("N-1", at, cease=True)]).hard_stop_flags
    )
    assert (
        HardStop.CEASE
        in _with_store(
            make_customer, now_utc, [_extraction("N-1", at, cease=True, confirmed="agent-7")]
        ).hard_stop_flags
    )


def test_gold_hard_stop_flags_are_used(make_customer, now_utc) -> None:  # type: ignore[no-untyped-def]
    ctx = _with_store(
        make_customer, now_utc, [], collections_hold=True, hard_stop_flags=frozenset({HardStop.BANKRUPTCY})
    )
    assert ctx.hard_stop_flags == {HardStop.BANKRUPTCY}  # named by gold: no INSOLVENCY guess


def test_only_new_live_notes_count_unless_a_person_confirmed(make_customer, now_utc) -> None:  # type: ignore[no-untyped-def]
    """History comes through the features (30/90 rule): an unconfirmed note from before the features
    were built, or from the SetFit backfill, doesn't raise hardship here; a confirmed one always does."""
    before_features = now_utc - timedelta(hours=20)  # features are 16 hours old
    old = _extraction("N-1", before_features, signal="possible")
    backfill = _extraction(
        "N-2", now_utc - timedelta(hours=1), signal="possible", extractor="setfit:setfit-v1"
    )
    assert _with_store(make_customer, now_utc, [old, backfill]).hardship_status is HardshipStatus.NONE
    confirmed = _extraction(
        "N-3", before_features, signal="clear", confirmed="agent-7", extractor="setfit:setfit-v1"
    )
    assert _with_store(make_customer, now_utc, [old, confirmed]).hardship_status is HardshipStatus.CONFIRMED
    cease = _extraction("N-4", before_features, cease=True, confirmed="agent-7")
    assert HardStop.CEASE in _with_store(make_customer, now_utc, [cease]).hard_stop_flags
