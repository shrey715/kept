import csv
from pathlib import Path

import pytest

from kept.contracts.features import RedactedText
from kept.text.qa import ITEMS, NEEDS_ACCOUNT, score, score_call
from tests.fakes import ScriptedLLM

LABELS = Path("data/labels/call_transcripts_labels_public_500.csv")
CALL = RedactedText(
    text="agent: This call may be recorded.\nagent: Can you confirm your date of birth?\n"
    "agent: We will garnish your wages tomorrow.",
    redactor_version="presidio-v7",
)


def _reply(**over: dict[str, object]) -> dict[str, dict[str, object]]:
    base = {c: {"status": "pass", "evidence": None} for c in ITEMS if c != NEEDS_ACCOUNT}
    return base | over


def test_a_critical_fail_needs_coaching_and_bad_evidence_is_dropped() -> None:
    llm = ScriptedLLM(
        [
            _reply(
                no_threatening_language={
                    "status": "fail",
                    "evidence": "We will garnish your wages tomorrow.",
                },
                recording_notice_given={"status": "pass", "evidence": "words that were never said"},
            )
        ]
    )
    got = score_call(CALL, llm=llm)
    assert got.items["no_threatening_language"] == "fail" and got.items[NEEDS_ACCOUNT] == "not_checked"
    assert got.score == 86 and got.coaching_required  # 100 - 14; a critical item failed
    assert got.evidence == {"no_threatening_language": "We will garnish your wages tomorrow."}


def test_one_retry_on_a_bad_reply() -> None:
    assert score_call(CALL, llm=ScriptedLLM([ValueError("schema"), _reply()])).score == 100
    with pytest.raises(ValueError):
        score_call(CALL, llm=ScriptedLLM([ValueError("a"), ValueError("b")]))


@pytest.mark.skipif(not LABELS.exists(), reason="needs the release's labels (data/ is not in git)")
def test_score_matches_every_public_label() -> None:
    codes = list(ITEMS)
    for r in csv.DictReader(LABELS.open()):
        items = {c: r[f"qa{i + 1:02d}_{c}"] for i, c in enumerate(codes)}
        assert score(items) == (int(r["qa_total_score"]), r["qa_coaching_required"] == "true"), r[
            "transcript_id"
        ]
