"""QA automation: score a collections call against the release's QA checklist (qa_checklist.csv, QA-2026.2).

The LLM reads the redacted transcript and marks each item pass / fail / not_applicable with the agent's words
as evidence; code checks the evidence is really in the call and computes the score the way the release's
labels do: 100 minus the weight of every failed item. Coaching is flagged when a critical item fails.

Item 6 (fees and balance stated accurately) needs the account's real balance, which the transcript doesn't
have: it is left to the account check (not_checked), never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kept.common.llm import Purpose
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import LLMGateway

PROMPT_VERSION = "qa-v1"

# item_code -> (weight, critical, what passes), from qa_checklist.csv
ITEMS: dict[str, tuple[int, bool, str]] = {
    "identity_verified_before_disclosure": (
        12,
        True,
        "the agent verifies identity (e.g. date of birth) BEFORE mentioning the debt or balance",
    ),
    "recording_notice_given": (6, False, "the recording notice is read at the start of the call"),
    "agent_identified_self_and_purpose": (6, False, "the agent gives their name, Maple Bank and the purpose"),
    "no_threatening_language": (14, True, "no threats of legal action, garnishment or arrest"),
    "no_misleading_statements": (12, True, "no false or misleading statements about consequences"),
    "fees_and_balance_stated_accurately": (8, False, "past-due amount and fees match the account"),
    "hardship_handled_per_policy": (
        18,
        True,
        "when the customer states a hardship, the agent acknowledges it and offers at least one hardship "
        "option BEFORE asking for payment (not_applicable when no hardship is stated)",
    ),
    "options_offered_before_escalation": (
        8,
        False,
        "payment options are offered before transferring or escalating (not_applicable without a transfer)",
    ),
    "ptp_details_confirmed_back": (
        8,
        False,
        "the agent reads back the promised amount and date (not_applicable when no promise is taken)",
    ),
    "respectful_close_and_next_steps": (8, False, "the agent thanks the customer and confirms next steps"),
}
NEEDS_ACCOUNT = "fees_and_balance_stated_accurately"
_ASKED = [code for code in ITEMS if code != NEEDS_ACCOUNT]

SYSTEM_PROMPT = (
    "You are a collections quality reviewer. Read one call transcript (personal details are already replaced "
    "by tags like <PERSON>) and judge the AGENT on each checklist item: pass, fail or not_applicable. Judge "
    "only what the transcript shows. For each item give the agent's exact words that decide it, copied "
    "verbatim, or null.\n\nChecklist:\n"
    + "\n".join(f"- {code}: {ITEMS[code][2]}" for code in _ASKED)
    + "\n\nReply with your judgement, not a schema: one key per item, for example\n"
    + '{"identity_verified_before_disclosure": {"status": "pass", "evidence": "can you please confirm your '
    + 'date of birth?"}, "recording_notice_given": {"status": "fail", "evidence": null}, ...}'
)

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        code: {
            "type": "object",
            "properties": {
                "status": {"enum": ["pass", "fail", "not_applicable"]},
                "evidence": {"type": ["string", "null"]},
            },
            "required": ["status", "evidence"],
        }
        for code in _ASKED
    },
    "required": _ASKED,
}


@dataclass(frozen=True)
class QaResult:
    items: dict[str, str]  # item_code -> pass / fail / not_applicable / not_checked
    evidence: dict[str, str]  # item_code -> the agent's words, only when they are really in the call
    score: int  # 100 minus the weights of failed items
    coaching_required: bool  # a critical item failed


def score(items: dict[str, str]) -> tuple[int, bool]:
    """(score, coaching_required) the way the release's labels compute them."""
    failed = [code for code, status in items.items() if status == "fail"]
    return 100 - sum(ITEMS[c][0] for c in failed), any(ITEMS[c][1] for c in failed)


def score_call(transcript: RedactedText, *, llm: LLMGateway, actor_id: str = "system:qa") -> QaResult:
    """One LLM call per transcript. Evidence that isn't in the transcript is dropped (never shown)."""
    for temperature in (0.0, 0.3):  # one retry when the reply doesn't match the schema
        try:
            reply = llm.complete(
                system=SYSTEM_PROMPT,
                user=transcript,
                purpose=Purpose.TEXT_EXTRACT,
                actor_id=actor_id,
                json_schema=JSON_SCHEMA,
                temperature=temperature,
            )
            break
        except ValueError:
            if temperature:
                raise
    assert reply.parsed is not None  # the gateway validates against JSON_SCHEMA
    items = {code: reply.parsed[code]["status"] for code in _ASKED} | {NEEDS_ACCOUNT: "not_checked"}
    evidence = {
        code: quote
        for code in _ASKED
        if (quote := (reply.parsed[code].get("evidence") or "").strip()) and quote in transcript.text
    }
    total, coaching = score(items)
    return QaResult(items=items, evidence=evidence, score=total, coaching_required=coaching)
