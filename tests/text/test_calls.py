import csv
from pathlib import Path

import duckdb
import pytest

from kept.common.llm import Purpose
from kept.text.calls import JSON_SCHEMA, CallSummary, format_summary, next_step, summarise_call
from tests.fakes import ScriptedLLM

LABELS = Path("data/labels/call_transcripts_labels_public_500.csv")

BQ_016 = {  # gold: "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review."
    "hardship": "clear",
    "hardship_reason": "illness",
    "dispute_type": None,
    "promise_amount": 95.0,
    "promise_month": 10,
    "promise_day": 14,
    "complaint": False,
    "cease_request": False,
    "insolvency_mention": False,
    "hardship_referral": True,
    "next_step": "send_payment_link",  # the agent also sends a link: the referral wins (gold)
}


def test_format_matches_gold_style() -> None:
    assert (
        format_summary(BQ_016 | {"next_step": "hardship_plan_review"})
        == "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review."
    )
    bq_022 = BQ_016 | {
        "hardship_reason": "reduced_income",
        "promise_amount": 595,
        "promise_day": 5,
        "cease_request": True,
        "next_step": "stop_contact",
    }
    assert format_summary(bq_022) == (
        "Customer reports reduced hours / income; promised $595 on 5 Oct; asked to stop contact; next step: stop contact."
    )
    nothing = {k: None for k in JSON_SCHEMA["required"]} | {"hardship": "none", "next_step": "call_back"}
    assert format_summary(nothing) == "No commitment made; next step: call back."


@pytest.mark.skipif(not LABELS.exists(), reason="needs the release's labels (data/ is not in git)")
def test_template_reproduces_every_public_gold_summary() -> None:
    for r in csv.DictReader(LABELS.open()):
        month, day = (
            (int(x) for x in r["label_ptp_date"][5:10].split("-")) if r["label_ptp_amount"] else (None, None)
        )
        fields = {
            "hardship": r["label_hardship"],
            "hardship_reason": r["label_hardship_reason"] or None,
            "dispute_type": r["label_dispute_type"] or None,
            "promise_amount": float(r["label_ptp_amount"]) if r["label_ptp_amount"] else None,
            "promise_month": month,
            "promise_day": day,
            "complaint": r["label_complaint"] == "true",
            "cease_request": r["label_cease_request"] == "true",
            "insolvency_mention": r["label_insolvency_mention"] == "true",
            "next_step": r["label_next_step"],
        }
        assert format_summary(fields) == r["label_summary_gold"], r["transcript_id"]


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("create schema text")
    c.execute(
        "create table text.redacted_notes (source_id varchar, source_type varchar, case_id varchar, "
        "written_at_local varchar, text varchar, entity_types_removed varchar, redactor_version varchar)"
    )
    c.execute(
        "insert into text.redacted_notes values "
        "('T-OLD', 'transcript', 'CS-1', '2026-08-01 10:00:00', 'customer: old call', '', 'presidio-v6'), "
        "('5010384', 'transcript', 'CS-1', '2026-09-27 16:59:55', 'customer: I can pay $95 Oct 14.', '', 'presidio-v6'), "
        "('N-1', 'note', 'CS-1', '2026-09-27 17:02:55', 'a later note', '', 'presidio-v6'), "
        "('N-2', 'note', 'CS-2', '2026-09-27 17:02:55', 'note only', '', 'presidio-v6')"
    )
    return c


def test_summarises_the_most_recent_transcript(conn: duckdb.DuckDBPyConnection) -> None:
    llm = ScriptedLLM([BQ_016])
    got = summarise_call("CS-1", llm=llm, conn=conn)
    assert got == CallSummary(
        "CS-1",
        "5010384",
        "2026-09-27 16:59:55",
        "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review.",
    )
    assert llm.calls[0]["user"].text == "customer: I can pay $95 Oct 14."  # newest call, not the later note
    assert llm.calls[0]["purpose"] == Purpose.TEXT_EXTRACT


def test_no_recorded_call_is_none_not_a_refusal(conn: duckdb.DuckDBPyConnection) -> None:
    assert summarise_call("CS-2", llm=ScriptedLLM(), conn=conn) is None
    assert summarise_call("CS-404", llm=ScriptedLLM(), conn=conn) is None


def test_one_retry_on_a_bad_reply(conn: duckdb.DuckDBPyConnection) -> None:
    llm = ScriptedLLM([ValueError("bad json"), BQ_016])
    assert summarise_call("CS-1", llm=llm, conn=conn) is not None
    with pytest.raises(ValueError):
        summarise_call("CS-1", llm=ScriptedLLM([ValueError("a"), ValueError("b")]), conn=conn)


def test_next_step_follows_the_label_priority() -> None:
    assert next_step(BQ_016) == "hardship_plan_review"
    assert next_step(BQ_016 | {"cease_request": True}) == "stop_contact"
    assert next_step(BQ_016 | {"complaint": True, "dispute_type": "late_fee"}) == "escalate_supervisor"
    assert next_step(BQ_016 | {"dispute_type": "fraud"}) == "dispute_investigation"
    assert next_step(BQ_016 | {"hardship_referral": False}) == "send_payment_link"
    assert next_step({"next_step": "hardship_plan_review"}) == "call_back"  # a step no rule backs: fall back
