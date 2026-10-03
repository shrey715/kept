"""text.extractions round-trips every TextExtraction field."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from kept.common.llm import Purpose
from kept.contracts import RedactedText
from kept.contracts.interfaces import ExtractionStore
from kept.text.extract import LLMExtractor, confirm
from kept.text.store import DuckDBExtractionStore

from ..fakes import PurposeLLM
from .test_extract_and_eval import _reply

NOTE = RedactedText(
    text="<PERSON> says shifts cut at the plant since Aug. Will pay $140 on 3 Oct after payday. Wife on the line.",
    redactor_version="test",
)


def _x(source_id: str, case_id: str = "C-1"):  # type: ignore[no-untyped-def]
    return LLMExtractor(PurposeLLM({Purpose.TEXT_EXTRACT: [_reply()]})).extract(
        NOTE, source_id=source_id, case_id=case_id
    )


def test_round_trip(tmp_path: Path) -> None:
    store = DuckDBExtractionStore(tmp_path / "w.duckdb")
    assert isinstance(store, ExtractionStore)
    x = _x("N-1")
    store.put(x)
    assert store.get("N-1") == x
    assert store.get("N-2") is None
    got = store.get("N-1")
    assert got is not None and got.promised_amount.value == Decimal("140.00")
    assert got.promised_date.value == date(2026, 10, 3)


def test_replace_and_for_case(tmp_path: Path) -> None:
    store = DuckDBExtractionStore(tmp_path / "w.duckdb")
    old, new = (
        _x("N-1"),
        _x("N-2").model_copy(update={"extracted_at": datetime.now(UTC) + timedelta(hours=1)}),
    )
    store.put_many([old, new, _x("N-3", case_id="C-2")])
    store.put(
        confirm(old, agent_id="agent-7", at=datetime.now(UTC), edits={"promised_amount": Decimal("120")})
    )
    assert [x.source_id for x in store.for_case("C-1")] == ["N-2", "N-1"]
    edited = store.get("N-1")
    assert edited is not None and edited.confirmed_by_agent_id == "agent-7"
    assert edited.promised_amount.value == Decimal("120.00") and edited.promised_amount.evidence is None
