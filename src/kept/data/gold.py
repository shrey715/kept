"""Gold: build gold.c360_customer, gold.identity_crosswalk, gold.c360_restricted."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import duckdb

from kept.contracts.enums import HardStop
from kept.contracts.identity import ContactPermissions

# Source flags (data dictionary names) behind each derived field. A flag on ANY linked
# record counts. national_dncl_flag is deliberately absent: the National DNCL covers
# telemarketing, not collections (design §9).
DO_NOT_CONTACT_FLAGS = (
    "internal_do_not_call_flag",  # customers
    "cease_communication_flag",  # customers
    "cease_contact_flag",  # collections_cases
    "cease_request_flag",  # contact_history
)
HARD_STOP_FLAGS: dict[HardStop, tuple[str, ...]] = {
    HardStop.CEASE: ("cease_communication_flag", "cease_contact_flag", "cease_request_flag"),
    HardStop.INSOLVENCY: ("consumer_proposal_flag", "insolvency_hold_flag", "consumer_proposal_on_file_flag"),
    HardStop.BANKRUPTCY: ("bankruptcy_flag", "bankruptcy_on_file_flag"),
    HardStop.DECEASED: ("deceased_flag", "deceased_hold_flag", "deceased_indicator"),
}
COLLECTIONS_HOLD_STOPS = (HardStop.INSOLVENCY, HardStop.BANKRUPTCY, HardStop.DECEASED)

# customers consent column behind each channel. Calls need consent_call (primary phone).
CONSENT_COLUMNS = {
    "call": "consent_call",
    "sms": "consent_sms",
    "email": "consent_email",
    "push": "consent_push",
}


def merge_contact_permissions(records: Iterable[ContactPermissions | None]) -> ContactPermissions:
    """Most restrictive across duplicate CRM records (built from CONSENT_COLUMNS): a channel
    is allowed only if every record allows it. A None record (unknown consent) blocks every
    channel. No records -> all False."""
    raise NotImplementedError("Track A")


def derive_contact_flags(source_flags: Iterable[Mapping[str, bool | None]]) -> tuple[bool, bool]:
    """(do_not_contact, collections_hold) across all source records for one customer.

    do_not_contact: any DO_NOT_CONTACT_FLAGS column true on any record.
    collections_hold: any HARD_STOP_FLAGS column for COLLECTIONS_HOLD_STOPS true on any record.
    Null flags and missing keys are ignored (not treated as true). national_dncl_flag never counts.
    """
    raise NotImplementedError("Track A")


def hard_stop_flags(source_flags: Iterable[Mapping[str, bool | None]]) -> frozenset[HardStop]:
    """Which hard stops fired across all source records, using HARD_STOP_FLAGS."""
    raise NotImplementedError("Track A")


def build_gold(conn: duckdb.DuckDBPyConnection) -> None:
    """Materialise the three gold tables from silver + the current crosswalk.
    Normally run through dbt; this wraps `dbt build --select gold`."""
    raise NotImplementedError("Track A")


def export_parquet(conn: duckdb.DuckDBPyConnection, *, as_of_date: str) -> None:
    """Write gold.c360_customer to data/exports/c360_customer/as_of_date=<date>/."""
    raise NotImplementedError("Track A")
