"""kept demo-reset removes notes typed during demos, and nothing else."""

from __future__ import annotations

from pathlib import Path

import duckdb

from kept.cli import reset_demo_notes


def test_only_demo_notes_are_removed(tmp_path: Path) -> None:
    wh = tmp_path / "w.duckdb"
    with duckdb.connect(str(wh)) as c:
        c.execute("create schema text")
        c.execute("create table text.extractions (source_id varchar, case_id varchar)")
        c.execute(
            "insert into text.extractions values "
            "('N-LIVE-aa11', 'CS-1'), ('N-LIVE-bb22', 'CS-2'), ('N-778', 'CS-1'), ('5010384', 'CS-1')"
        )
    assert reset_demo_notes(wh, "CS-1") == 1  # one case only
    assert reset_demo_notes(wh) == 1  # the rest of the demo notes
    with duckdb.connect(str(wh)) as c:
        left = sorted(r[0] for r in c.execute("select source_id from text.extractions").fetchall())
    assert left == ["5010384", "N-778"]  # nightly notes and transcripts are untouched


def test_no_extractions_table_is_fine(tmp_path: Path) -> None:
    assert reset_demo_notes(tmp_path / "empty.duckdb") == 0
