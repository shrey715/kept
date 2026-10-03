"""Combine hardship signals into hardship_status / hardship_source on the golden record."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from kept.contracts.enums import HardshipSignal, HardshipSource, HardshipStatus


@dataclass(frozen=True, slots=True)
class HardshipObservation:
    source: HardshipSource
    signal: HardshipSignal
    observed_at: datetime
    confirmed_by: str | None = None  # person who confirmed (agent/specialist)
    cleared_by: str | None = None  # person who cleared it; only a person can clear


def combine(observations: Iterable[HardshipObservation]) -> tuple[HardshipStatus, HardshipSource | None]:
    """Rules (design §5, §9):
      * any non-NONE signal from any source -> at least POSSIBLE (restricts straight away);
      * CONFIRMED needs a person or a programme: an AGENT or ACCOUNT_PROGRAMME observation
        with signal CLEAR, or any non-NONE observation with confirmed_by set. CUSTOMER_FORM,
        MODEL, LLM and CASH_FLOW observations stay POSSIBLE until a person confirms;
      * an LLM CLEAR without confirmation is POSSIBLE, not CONFIRMED;
      * a NONE signal never lowers the status; only an observation with cleared_by
        set clears, and only observations at or before it;
      * source = source of the observation that set the final status (latest wins ties;
        HardshipSource declaration order breaks same-time ties); None when NONE.

    Vulnerability (customers.vulnerability_flag, contact_history.vulnerability_disclosed_flag)
    arrives as an AGENT observation with signal POSSIBLE: it protects exactly like hardship.
    """
    raise NotImplementedError("Track C")
