"""CaseContextBuilder (S3): everything the rule stages need about one case, read fresh.

Golden record (A) for consent, calling window, do-not-contact, hardship and payroll;
online features (D) for contact counts and text signals; the case row
(silver.collections_cases) for the per-case cap, case-level hard stops and the
incumbent recommendation. Unknowns fail closed: no time zone fails the calling-hours
check, an unknown contact count uses up the cap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from kept.config import CENT, CONTACT_CAP_7D, HOLDOUT_SHARE
from kept.contracts.enums import HardshipSignal, HardshipStatus, HardStop
from kept.contracts.interfaces import C360Reader, FeatureProvider
from kept.contracts.nba import CaseContext
from kept.nba.legacy import legacy_to_action
from kept.nba.release import in_holdout


@dataclass(frozen=True, slots=True)
class CaseRow:
    """The silver.collections_cases columns the context needs (data dictionary names)."""

    case_id: str
    total_overdue: Decimal
    contact_cap_7d: int | None = None
    nba_recommendation_last: str | None = None
    cease_contact_flag: bool = False
    insolvency_hold_flag: bool = False
    deceased_hold_flag: bool = False


def duckdb_case_reader(path: Path | str) -> Callable[[str], CaseRow]:
    """Reads one case from silver.collections_cases, opening the warehouse per call (K5).
    Unknown case -> KeyError."""

    def read(case_id: str) -> CaseRow:
        with duckdb.connect(str(path), read_only=True) as c:
            row = c.execute(
                "select case_id, total_overdue, contact_cap_7d, nba_recommendation_last, cease_contact_flag,"
                " insolvency_hold_flag, deceased_hold_flag from silver.collections_cases where case_id = ?",
                [case_id],
            ).fetchone()
        if row is None:
            raise KeyError(case_id)
        cid, overdue, cap, legacy, cease, insolvency, deceased = row
        return CaseRow(
            case_id=cid,
            total_overdue=Decimal(str(overdue or 0)).quantize(CENT),
            contact_cap_7d=cap,
            nba_recommendation_last=legacy,
            cease_contact_flag=bool(cease),
            insolvency_hold_flag=bool(insolvency),
            deceased_hold_flag=bool(deceased),
        )

    return read


class KeptContextBuilder:
    """Implements kept.contracts.interfaces.CaseContextBuilder."""

    def __init__(
        self,
        *,
        c360: C360Reader,
        features: FeatureProvider,
        cases: Callable[[str], CaseRow],
        holdout_salt: str,
    ) -> None:
        self._c360 = c360
        self._features = features
        self._cases = cases
        self._salt = holdout_salt

    def build(self, case_id: str, now: datetime) -> CaseContext:
        """Unknown case -> KeyError (from the case reader or C360)."""
        case = self._cases(case_id)
        customer = self._c360.customer_for_case(case_id)
        fv = self._features.get_online(case_id)

        stops: set[HardStop] = set()
        if case.cease_contact_flag or fv.cease_request_flag:
            stops.add(HardStop.CEASE)
        if case.insolvency_hold_flag:
            stops.add(HardStop.INSOLVENCY)
        if case.deceased_hold_flag:
            stops.add(HardStop.DECEASED)
        if customer.collections_hold and not stops & {
            HardStop.INSOLVENCY,
            HardStop.BANKRUPTCY,
            HardStop.DECEASED,
        }:
            # ponytail: gold only says "some hold"; INSOLVENCY until GoldenCustomer carries hard_stop_flags (G0)
            stops.add(HardStop.INSOLVENCY)

        hardship = customer.hardship_status
        if hardship is HardshipStatus.NONE and fv.hardship_signal in (
            HardshipSignal.POSSIBLE,
            HardshipSignal.CLEAR,
        ):
            hardship = HardshipStatus.POSSIBLE  # a fresh note protects before the nightly gold rebuild

        cap = case.contact_cap_7d if case.contact_cap_7d is not None else CONTACT_CAP_7D
        window = {}
        if customer.permitted_call_start_local and customer.permitted_call_end_local:
            window = {
                "permitted_call_start_local": customer.permitted_call_start_local,
                "permitted_call_end_local": customer.permitted_call_end_local,
            }
        return CaseContext(
            case_id=case_id,
            golden_customer_id=customer.golden_customer_id,
            assigned_agent_id=customer.assigned_agent_id,
            now=now,
            time_zone=customer.time_zone or "",
            hard_stop_flags=frozenset(stops),
            contact_permissions=customer.contact_permissions,
            sunday_contact_permitted=customer.sunday_contact_permitted,
            do_not_contact=customer.do_not_contact,
            contacts_last_7d=fv.contacts_last_7d if fv.contacts_last_7d is not None else cap,
            contact_cap_7d=cap,
            hardship_status=hardship,
            vulnerable=customer.vulnerability_flag,
            balance_at_risk=case.total_overdue,
            expected_next_payroll_date=customer.expected_next_payroll_date,
            payroll_frequency=customer.payroll_frequency_detected,
            estimated_monthly_spare_cash=fv.estimated_monthly_spare_cash,
            in_holdout=in_holdout(customer.golden_customer_id, salt=self._salt, share=HOLDOUT_SHARE),
            legacy_action=legacy_to_action(case.nba_recommendation_last),
            features_as_of=fv.as_of,
            **window,
        )
