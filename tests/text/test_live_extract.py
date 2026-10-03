"""kept extract: silver notes or a typed note -> text.extractions, skip-on-error."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from kept import cli
from kept.common.llm import Purpose
from kept.contracts.enums import HardshipSignal
from kept.text import live
from kept.text.live import extract_into, read_sources, typed_note
from kept.text.store import DuckDBExtractionStore

from ..fakes import PassThroughRedactor, PurposeLLM
from .test_extract_and_eval import _reply

NOTE = (
    "<PERSON> says shifts cut at the plant since Aug. Will pay $140 on 3 Oct after payday. Wife on the line."
)


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "w.duckdb"
    with duckdb.connect(str(path)) as c:
        c.execute("create schema silver")
        c.execute(
            "create table silver.agent_notes (note_id varchar, case_id varchar, note_ts timestamp, "
            "note_ts_utc timestamp, note_text varchar)"
        )
        c.executemany(
            "insert into silver.agent_notes values (?, ?, ?, ?, ?)",
            [
                ("N-1", "C-1", datetime(2026, 9, 30, 10), datetime(2026, 9, 30, 14), NOTE),
                ("N-2", "C-1", datetime(2026, 10, 1, 10), datetime(2026, 10, 1, 14), NOTE),
                (
                    "N-3",
                    "C-2",
                    datetime(2026, 10, 2, 10),
                    datetime(2026, 10, 2, 14),
                    "spoke w/ cust. CB scheduled",
                ),
            ],
        )
        c.execute(
            "create table silver.call_transcripts (transcript_id varchar, case_id varchar, "
            "call_start_ts timestamp, file_path varchar)"
        )
        c.execute(
            "insert into silver.call_transcripts values ('T-1', 'C-2', '2026-10-01 09:00', 't/T-1.json')"
        )
    return path


def _llm() -> PurposeLLM:
    return PurposeLLM({Purpose.TEXT_EXTRACT: [_reply()]})


def test_extracts_a_given_note(warehouse: Path) -> None:
    sources = read_sources(warehouse, note_ids=["N-2"])
    assert [(s.source_id, s.written_at) for s in sources] == [("N-2", datetime(2026, 10, 1, 10))]
    [r] = list(extract_into(warehouse, sources, redactor=PassThroughRedactor(), llm=_llm()))
    assert r.error is None
    got = DuckDBExtractionStore(warehouse).get("N-2")
    assert got is not None and got.case_id == "C-1"
    assert got.hardship_signal.value is HardshipSignal.POSSIBLE
    assert got.promised_date.value == date(2026, 10, 3)


def test_transcript_is_read_from_its_json(warehouse: Path, tmp_path: Path) -> None:
    (tmp_path / "files/t").mkdir(parents=True)
    turns = [
        {"turn_index": 1, "speaker": "customer", "text": "ok"},
        {"turn_index": 0, "speaker": "agent", "text": "hi"},
    ]
    (tmp_path / "files/t/T-1.json").write_text(json.dumps({"turns": turns}))
    [s] = read_sources(warehouse, transcript_ids=["T-1"], raw_dir=tmp_path)
    assert (s.source_id, s.case_id, s.text) == ("T-1", "C-2", "agent: hi\ncustomer: ok")


def test_new_skips_extracted_notes(warehouse: Path) -> None:
    list(
        extract_into(
            warehouse, read_sources(warehouse, note_ids=["N-1"]), redactor=PassThroughRedactor(), llm=_llm()
        )
    )
    assert [s.source_id for s in read_sources(warehouse, new=True)] == ["N-3", "N-2"]  # newest first
    assert [s.source_id for s in read_sources(warehouse, new=True, limit=1)] == ["N-3"]


def test_typed_note(warehouse: Path) -> None:
    s = typed_note(NOTE, case_id="C-9")
    assert s.source_id.startswith("N-LIVE-") and s.written_at is not None
    list(extract_into(warehouse, [s], redactor=PassThroughRedactor(), llm=_llm()))
    assert [x.source_id for x in DuckDBExtractionStore(warehouse).for_case("C-9")] == [s.source_id]


def test_bad_note_does_not_stop_the_batch(warehouse: Path) -> None:
    llm = PurposeLLM({Purpose.TEXT_EXTRACT: ["not json", "not json", _reply()]})  # N-3 fails both tries
    results = list(
        extract_into(
            warehouse, read_sources(warehouse, new=True), redactor=PassThroughRedactor(), llm=llm, batch=1
        )
    )
    assert [(r.source_id, r.error is None) for r in results] == [("N-3", False), ("N-2", True), ("N-1", True)]
    assert read_sources(warehouse, new=True)[0].source_id == "N-3"  # retried next run


def test_cli(warehouse: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("KEPT_WAREHOUSE_PATH", str(warehouse))
    real = live.extract_into
    monkeypatch.setattr(
        live,
        "extract_into",
        lambda path, sources: real(path, sources, redactor=PassThroughRedactor(), llm=_llm()),
    )
    assert cli.main(["extract", "--note-id", "N-1", "--note-id", "N-404"]) == 0
    assert cli.main(["extract", "--text", NOTE, "--case-id", "C-9", "--source-id", "N-LIVE-x"]) == 0
    out = capsys.readouterr().out
    assert "N-404  not found in silver" in out
    assert "N-1  hardship=possible  promise=yes 140.00 2026-10-03  cease-suggested=no" in out
    assert DuckDBExtractionStore(warehouse).get("N-LIVE-x") is not None
    assert cli.main(["extract", "--text", NOTE]) == 2  # --text needs --case-id
