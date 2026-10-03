"""DuckDBC360Reader: same protocol checks as DictC360Reader (tests/contracts/test_fakes_conform.py)
plus a round trip through a tiny warehouse."""

from __future__ import annotations

import inspect
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from kept.common.db import connect
from kept.contracts import (
    ContactPermissions,
    DpdBucket,
    HardshipStatus,
    HardStop,
    MatchReviewStatus,
    SourceKey,
    SourceSystem,
)
from kept.contracts import interfaces as I
from kept.data.c360_reader import DuckDBC360Reader

GOLD_ROW = """
create table gold.c360_customer as select
    'G-000042' as golden_customer_id,
    ['crm:RYM-1', 'card:CX-9'] as source_keys,
    0.97::double as match_confidence_min,
    'auto' as match_review_status,
    'Jane Doe' as display_name,
    '+14165550123' as primary_phone_e164,
    'jane@example.ca' as email,
    'ON' as province_code,
    'America/Toronto' as time_zone,
    'EN' as preferred_language,
    1234.50::decimal(18, 2) as total_overdue,
    45 as max_dpd,
    '31-60' as current_bucket,
    'CS-1' as open_case_id,
    'AG-7' as assigned_agent_id,
    {'call': true, 'sms': false, 'email': true, 'push': false} as contact_permissions,
    time '08:00' as permitted_call_start_local,
    time '21:00' as permitted_call_end_local,
    false as sunday_contact_permitted,
    false as do_not_contact,
    true as collections_hold,
    ['insolvency'] as hard_stop_flags,
    'possible' as hardship_status,
    'agent' as hardship_source,
    false as vulnerability_flag,
    date '2026-10-09' as expected_next_payroll_date,
    'biweekly' as payroll_frequency_detected,
    date '2026-09-28' as as_of_date,
    timestamptz '2026-10-03 04:00:00+00' as refreshed_at,
    'crm:RYM-1' as display_name_source,
    'crm:RYM-1' as primary_phone_e164_source,
    'crm:RYM-1' as email_source,
    'crm:RYM-1' as province_code_source,
    'crm:RYM-1' as time_zone_source,
    'crm:RYM-1' as preferred_language_source,
    'card, loan' as total_overdue_source,
    'crm:RYM-1' as contact_permissions_source,
    null::varchar as do_not_contact_source,
    'crm.consumer_proposal_flag' as collections_hold_source,
    'deposit:D-1' as expected_next_payroll_date_source
"""


@pytest.fixture
def reader(tmp_path: Path) -> DuckDBC360Reader:
    path = tmp_path / "w.duckdb"
    conn = connect(path)
    conn.execute(GOLD_ROW)
    conn.execute("""create table gold.identity_crosswalk as select * from (values
        ('G-000042', 'crm', 'RYM-1', null::double, 'exact:case_crm_ref', 'auto', null::timestamptz, null::timestamptz),
        ('G-000042', 'collections', 'RYM-1', null, 'exact:case_crm_ref', 'auto', null, null),
        ('G-000099', 'crm', 'OLD-1', null, 'splink', 'auto', null, timestamptz '2026-09-01 00:00:00+00')
    ) t(golden_customer_id, source_system, source_key, match_score, match_rule, match_review_status, linked_at, valid_to)""")
    conn.execute("""create table silver.collections_cases as select * from (values
        ('CS-1', 'RYM-1'), ('CS-2', 'RYM-1'), ('CS-3', 'NOBODY')) t(case_id, coll_customer_ref)""")
    conn.close()
    return DuckDBC360Reader(path)


def test_reader_satisfies_the_protocol_like_the_fake(reader: DuckDBC360Reader) -> None:
    assert isinstance(reader, I.C360Reader)
    for name, member in inspect.getmembers(I.C360Reader, inspect.isfunction):
        if not name.startswith("_"):
            expected = list(inspect.signature(member).parameters)
            assert ["self", *inspect.signature(getattr(reader, name)).parameters] == expected


def test_get_customer_round_trips_every_field(reader: DuckDBC360Reader) -> None:
    c = reader.get_customer("G-000042")
    assert c.source_keys == (
        SourceKey(system=SourceSystem.CRM, key="RYM-1"),
        SourceKey(system=SourceSystem.CARD, key="CX-9"),
    )
    assert c.match_review_status is MatchReviewStatus.AUTO and c.match_confidence_min == pytest.approx(0.97)
    assert c.total_overdue == Decimal("1234.50") and c.max_dpd == 45 and c.current_bucket is DpdBucket.B31_60
    assert c.contact_permissions == ContactPermissions(call=True, email=True)
    assert c.permitted_call_start_local == time(8, 0) and c.expected_next_payroll_date == date(2026, 10, 9)
    assert c.collections_hold and not c.do_not_contact and c.hard_stop_flags == {HardStop.INSOLVENCY}
    assert c.hardship_status is HardshipStatus.POSSIBLE and c.refreshed_at.tzinfo is not None


def test_get_customer_unknown_raises_key_error(reader: DuckDBC360Reader) -> None:
    with pytest.raises(KeyError):
        reader.get_customer("G-999999")


def test_resolve_uses_active_links_only(reader: DuckDBC360Reader) -> None:
    assert reader.resolve(SourceKey(system=SourceSystem.CRM, key="RYM-1")) == "G-000042"
    assert reader.resolve(SourceKey(system=SourceSystem.CRM, key="OLD-1")) is None  # retired link
    assert reader.resolve(SourceKey(system=SourceSystem.CRM, key="nobody")) is None


def test_customer_for_case_resolves_every_case_of_a_customer(reader: DuckDBC360Reader) -> None:
    assert reader.customer_for_case("CS-1").golden_customer_id == "G-000042"
    assert reader.customer_for_case("CS-2").golden_customer_id == "G-000042"  # not the one in open_case_id
    for unresolved in ("CS-3", "missing"):
        with pytest.raises(KeyError):
            reader.customer_for_case(unresolved)
