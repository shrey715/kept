"""Policy search cites only documents current on the asked date (integration: LanceDB)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from kept.ask.policy import PolicyChunk, PolicyIndex

pytestmark = pytest.mark.integration


def test_search_returns_only_current_sections(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    idx = PolicyIndex(tmp_path / "lance")
    idx.add(
        [
            PolicyChunk(
                "HP-REDUCE",
                "4.2 Payment reductions (v1)",
                "Reductions up to 25% with team lead sign-off.",
                date(2025, 1, 1),
                date(2026, 6, 1),
            ),
            PolicyChunk(
                "HP-REDUCE",
                "4.2 Payment reductions (v2)",
                "Reductions need a hardship specialist and a second approver.",
                date(2026, 6, 1),
                None,
            ),
            PolicyChunk(
                "CONTACT",
                "2.1 Calling hours",
                "Calls only between 07:00 and 21:00 customer local time.",
                date(2024, 1, 1),
                None,
            ),
        ]
    )
    hits = idx.search("who approves a payment reduction?", as_of=date(2026, 10, 3), k=3)
    assert hits and hits[0].document_id == "HP-REDUCE" and "(v2)" in hits[0].section
    assert all("(v1)" not in h.section for h in hits)
    old = idx.search("who approves a payment reduction?", as_of=date(2026, 1, 1), k=3)
    assert old[0].section.endswith("(v1)")
