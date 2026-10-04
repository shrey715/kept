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
