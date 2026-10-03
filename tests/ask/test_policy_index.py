"""Policy search cites only documents current on the asked date (integration: LanceDB)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from kept.ask.policy import PolicyChunk, PolicyIndex, build_policy_index

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


def test_policy_outranks_a_faq_that_matches_just_as_well(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    idx = PolicyIndex(tmp_path / "lance")
    idx.add(
        [
            PolicyChunk(
                "FAQ", "Q1", "The reduced payment programme lasts 6 months.", date(2026, 4, 1), None, "faq"
            ),
            PolicyChunk(
                "POL",
                "4.2",
                "The reduced payment programme lasts 3 months.",
                date(2026, 3, 1),
                None,
                "policy",
            ),
        ]
    )
    hits = idx.search("how long does the reduced payment programme last?", as_of=date(2026, 9, 28), k=2)
    assert [h.document_id for h in hits] == ["POL", "FAQ"]


def test_build_policy_index_follows_superseded_by(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "p1.md").write_text("# P\n\n## 1 Calls\nUp to 5 calls a week.")
    (tmp_path / "policy" / "p2.md").write_text("# P\n\n## 1 Calls\nUp to 3 calls a week.")
    docs = [
        {
            "doc_id": "P-V1",
            "doc_type": "policy",
            "effective_date": "2025-01-01",
            "superseded_by": "P",
            "file_path": "docs/policy/p1.md",
        },
        {
            "doc_id": "P",
            "doc_type": "policy",
            "effective_date": "2026-03-01",
            "superseded_by": "",
            "file_path": "docs/policy/p2.md",
        },
    ]
    idx = PolicyIndex(tmp_path / "lance")
    assert build_policy_index(idx, docs, tmp_path) == 2
    assert [h.document_id for h in idx.search("calls a week", as_of=date(2026, 9, 28))] == ["P"]
    assert [h.document_id for h in idx.search("calls a week", as_of=date(2025, 6, 1))] == ["P-V1"]


def test_an_ops_event_answers_why_a_number_changed(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    from kept.ask.policy import ops_event_chunks

    idx = PolicyIndex(tmp_path / "lance")
    policy = PolicyChunk(
        "POL-COLL-001",
        "§5.2 Contact frequency",
        "A maximum of 3 outbound call attempts in any rolling 7 days.",
        date(2026, 1, 1),
        None,
        "policy",
    )
    outage = {
        "event_id": "INC-0923",
        "event_type": "dialer_outage",
        "system": "Predictive dialer",
        "start_ts": "2026-09-23 08:00:00",
        "end_ts": "2026-09-24 21:00:00",
        "severity": "sev2",
        "description": "Outbound dialer degraded; call capacity down about 60%",
        "affected_customers_est": "35000",
        "reference_doc_id": "IR-2026-0923",
    }
    idx.add([policy, *ops_event_chunks([outage])])
    hits = idx.search(
        "Why did outbound call volume drop on 23-24 September 2026?", as_of=date(2026, 9, 28), k=2
    )
    assert hits[0].document_id == "IR-2026-0923" and "60%" in hits[0].snippet
    assert (
        idx.search("why did outbound call volume drop", as_of=date(2026, 9, 1), k=2)[0].document_id
        == "POL-COLL-001"
    )  # before the event
