"""Combine hardship signals into hardship_status / hardship_source on the golden record."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from kept.contracts.enums import HardshipSignal, HardshipSource, HardshipStatus
from kept.contracts.features import TextExtraction


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
    observations = list(observations)
    cleared_at = max((o.observed_at for o in observations if o.cleared_by), default=None)
    best: tuple[int, datetime, int] | None = None
    best_source: HardshipSource | None = None
    for o in observations:
        if o.signal is HardshipSignal.NONE or (cleared_at is not None and o.observed_at <= cleared_at):
            continue
        rank = 2 if _confirms(o) else 1
        key = (rank, o.observed_at, -_ORDER.index(o.source))
        if best is None or key > best:
            best, best_source = key, o.source
    if best is None:
        return HardshipStatus.NONE, None
    return (HardshipStatus.CONFIRMED if best[0] == 2 else HardshipStatus.POSSIBLE), best_source


_ORDER = list(HardshipSource)
_CONFIRMING_SOURCES = (HardshipSource.AGENT, HardshipSource.ACCOUNT_PROGRAMME)


def _confirms(o: HardshipObservation) -> bool:
    return o.confirmed_by is not None or (
        o.source in _CONFIRMING_SOURCES and o.signal is HardshipSignal.CLEAR
    )


def observations_from_extractions(extractions: Iterable[TextExtraction]) -> list[HardshipObservation]:
    """Track C's text extractions as combine() input: the same rule as gold's SQL (A,
    int_hardship_observations, 'llm' branch). NONE signals add nothing; an agent's confirmation
    (confirmed_by_agent_id) confirms. For the live path: combine(observations_from_extractions(
    store.for_case(case_id))) flips a case on a fresh note before the nightly gold rebuild."""
    return [
        HardshipObservation(
            source=HardshipSource.LLM,
            signal=x.hardship_signal.value,
            observed_at=x.extracted_at,
            confirmed_by=x.confirmed_by_agent_id,
        )
        for x in extractions
        if x.hardship_signal.value is not HardshipSignal.NONE
    ]
