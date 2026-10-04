"""Citations name what the answer relies on, and every policy citation can be verified against its source."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("sqlglot")  # the `ask` extra; the contract-test job runs without it

from kept.ask.policy import PolicyChunk, PolicyIndex
from kept.ask.service import tag_citations
from kept.contracts.ask import Citation


def _c(doc: str, section: str) -> Citation:
    return Citation(document_id=doc, section=section, effective_from=date(2026, 1, 1), snippet="x")


def test_only_named_sections_are_used_and_they_come_first() -> None:
    found = [
        _c("DFI-0812", "DFI-0812: data feed issue"),
        _c("POL-COLL-001", "§7.3 Insolvency"),
        _c("POL-COLL-001", "§5.2 Contact frequency"),
    ]
    out = tag_citations(found, "All contact stops and the case moves to insolvency_hold (POL-COLL-001 §7.3).")
    assert [(c.ref, c.section, c.used) for c in out] == [
        (1, "§7.3 Insolvency", True),
        (2, "DFI-0812: data feed issue", False),
        (3, "§5.2 Contact frequency", False),
    ]
    assert out[0].mention == "POL-COLL-001 §7.3"


def test_a_document_without_section_numbers_is_named_by_its_id() -> None:
    out = tag_citations(
        [_c("IR-2026-0923", "Incident Report IR-2026-0923")], "The dialer failed (IR-2026-0923)."
    )
    assert out[0].used and out[0].mention == "IR-2026-0923"
    assert not tag_citations([_c("IR-2026-0923", "x")], "The excerpts don't say.")[0].used


@pytest.mark.integration
def test_source_locates_the_cited_snippet_in_the_current_version(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    idx = PolicyIndex(tmp_path / "lance")
    idx.add(
        [
            PolicyChunk("POL", "§1 Scope", "Applies to all products.", date(2026, 1, 1), None),
            PolicyChunk("POL", "§2 Calls", "Up to 3 calls in 7 days.", date(2026, 1, 1), None),
            PolicyChunk("POL", "§2 Calls", "Up to 5 calls in 7 days.", date(2025, 1, 1), date(2026, 1, 1)),
        ]
    )
    hit = idx.search("how many calls", as_of=date(2026, 10, 1), k=1)[0]
    src = idx.source(hit.document_id, hit.section, hit.effective_from, hit.snippet)
    assert src is not None and src.effective_to is None and "5 calls" not in src.text
    assert src.highlight_start is not None and src.highlight_end is not None
    assert src.text[src.highlight_start : src.highlight_end] == "Up to 3 calls in 7 days."
    gone = idx.source("POL", "§2 Calls", date(2026, 1, 1), "Up to 9 calls")  # not in the source: no highlight
    assert gone is not None and gone.highlight_start is None


def test_before_a_date_searches_the_documents_in_force_then() -> None:
    from kept.ask.service import policy_as_of

    today = date(2026, 9, 28)
    assert policy_as_of("Before the March 2026 policy change, how long was the programme?", today) == date(
        2026, 2, 28
    )
    assert policy_as_of("How long is the reduced-payment programme?", today) == today
    assert (
        policy_as_of("What changed in March 2026?", today) == today
    )  # naming a month isn't asking for before it


def test_metrics_can_be_narrowed_to_outbound_calls_and_open_cases() -> None:
    from kept.ask.certified import CERTIFIED_QUERIES

    for m in ("ptp_rate", "rpc_rate", "cost_per_rpc", "cost_per_contact"):
        assert {"direction", "channel"} <= CERTIFIED_QUERIES[m].allowed_filters, m
        assert "direction" not in CERTIFIED_QUERIES[m].allowed_group_by
    for m in ("hardship_rate", "average_dpd"):
        assert "is_open" in CERTIFIED_QUERIES[m].allowed_filters, m


def test_a_filter_the_metric_already_applies_is_dropped_not_refused() -> None:
    from kept.ask.metrics import compile_metric
    from kept.ask.templates import TEMPLATES
    from kept.contracts.ask import Intent, IntentKind

    defs = {k: d for k, (d, _) in TEMPLATES.items()}
    queries = {k: q for k, (_, q) in TEMPLATES.items()}

    def compile_with(**filters: object) -> str:
        intent = Intent(kind=IntentKind.METRIC, metric_id="out_of_hours_rate", filters=filters, confidence=1)
        return compile_metric(intent, defs, queries)[0]

    assert compile_with(direction="outbound", channel="call") == compile_with()  # already outbound calls only
    with pytest.raises(ValueError, match="direction"):
        compile_with(direction="inbound")  # contradicts the metric: still refused, not silently ignored
