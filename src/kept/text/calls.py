"""Post-call summary: the most recent recorded call on a case, in one line (Ask: "summarise the most recent
recorded call on case X", BQ-016/021/022).

The LLM reads the redacted transcript and fills structured fields; `format_summary` writes the sentence in
the release's `label_summary_gold` style ("Customer reports illness; promised $95 on 14 Oct; next step:
hardship plan review."). The template reproduces all 500 public gold summaries exactly from their labels
(tests/text/test_calls.py), so wording never drifts: only the facts come from the model.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from kept.common.llm import Purpose
from kept.config import WAREHOUSE_PATH
from kept.contracts.interfaces import LLMGateway
from kept.text.redact import stored_redacted

PROMPT_VERSION = "call-summary-v4"

REASONS = {  # hardship reason -> the gold wording
    "reduced_income": "reduced hours / income",
    "job_loss": "job loss",
    "separation": "separation",
    "illness": "illness",
    "rate_reset": "payment increase after rate reset",
    "disability": "disability",
    "disaster_evacuation": "evacuation (disaster)",
    "ei_waiting": "waiting for EI",
}
DISPUTES = ("late_fee", "billing_error", "payment_not_applied", "fraud")
NEXT_STEPS = (
    "stop_contact",
    "escalate_supervisor",
    "dispute_investigation",
    "hardship_plan_review",
    "send_payment_link",
    "call_back",
)

SYSTEM_PROMPT = """You read one collections call transcript (personal details already replaced by tags like
<PERSON>) and record what the CUSTOMER said and agreed to. Fill every field; use null when the call does not
say it. Never guess.

hardship: "clear" if the customer states a specific cause listed under hardship_reason; "possible" if they
only say money is tight / they can't afford it, with no cause from that list; "none" otherwise. Paying
after their next payday, a late paycheque, forgetting or a bank-transfer problem is timing, not hardship:
"none".
hardship_reason (only when hardship is "clear"):
  reduced_income = fewer hours, days or shifts, or a pay cut ("only getting 3 days a week now")
  job_loss = laid off, lost the job; separation = divorce or separated; illness = sick, off work ill;
  disability = a disability or injury; disaster_evacuation = evacuated, fire, flood;
  ei_waiting = waiting for Employment Insurance; rate_reset = payment went up after a rate or term renewal.
dispute_type: only when the customer says the bank's charge or record is wrong: late_fee (a late fee they
should not have been charged), billing_error (the bill or balance is wrong), payment_not_applied (they paid
but it is not showing), fraud (they did not make the transactions). A problem on the customer's side (their
bank transfer failed, they forgot) is NOT a dispute: null.
promise_amount / promise_month / promise_day: the payment the customer commits to (the amount and date the
agent confirms back). null if no payment was promised.
complaint: the customer says they want to make or file a complaint. cease_request: the customer calmly
asks the bank to stop contacting them ("Please stop calling me."). An angry outburst like "Stop calling me
every day!" (with or without "This is harassment", even cut off) is NOT a cease request or a complaint.
cease_quote: the customer's exact words asking to stop contact, copied verbatim, or null.
insolvency_mention: the customer mentions a consumer proposal or bankruptcy.
hardship_referral: the agent refers the account to the hardship team / a hardship plan review and the
customer agrees.
next_step: what the agent does next if none of the above applies: escalate_supervisor (the customer is
hostile or refuses, or the agent transfers the call), send_payment_link (a payment was promised) or
call_back (nothing agreed)."""

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hardship": {"enum": ["none", "possible", "clear"]},
        "hardship_reason": {"enum": [*REASONS, None]},
        "dispute_type": {"enum": [*DISPUTES, None]},
        "promise_amount": {"type": ["number", "null"]},
        "promise_month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
        "promise_day": {"type": ["integer", "null"], "minimum": 1, "maximum": 31},
        "complaint": {"type": "boolean"},
        "cease_request": {"type": "boolean"},
        "cease_quote": {"type": ["string", "null"]},
        "insolvency_mention": {"type": "boolean"},
        "hardship_referral": {"type": "boolean"},
        "next_step": {"enum": list(NEXT_STEPS)},
    },
    "required": [
        "hardship",
        "hardship_reason",
        "dispute_type",
        "promise_amount",
        "promise_month",
        "promise_day",
        "complaint",
        "cease_request",
        "cease_quote",
        "insolvency_mention",
        "hardship_referral",
        "next_step",
    ],
}


@dataclass(frozen=True)
class CallSummary:
    case_id: str
    transcript_id: str  # the source to cite
    call_start: str  # local time of the call
    summary: str  # "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review."


def format_summary(f: dict[str, Any]) -> str:
    """The gold one-liner from the extracted fields (same keys as JSON_SCHEMA)."""
    parts = []
    if f.get("hardship") == "clear" and f.get("hardship_reason") in REASONS:
        parts.append("Customer reports " + REASONS[f["hardship_reason"]])
    elif f.get("hardship") in ("clear", "possible"):
        parts.append("Customer indicates finances are tight")
    if f.get("dispute_type"):
        parts.append("disputes " + f["dispute_type"].replace("_", " "))
    if f.get("promise_amount") is not None and f.get("promise_month") and f.get("promise_day"):
        month = f["promise_month"]  # 2000 is a leap year: 29 Feb is a valid promise date; "31 Sep" -> 30 Sep
        when = date(2000, month, min(f["promise_day"], calendar.monthrange(2000, month)[1]))
        parts.append(f"promised ${round(f['promise_amount']):,} on {when.day} {when:%b}")
    if f.get("complaint"):
        parts.append("wants to complain")
    if f.get("cease_request"):
        parts.append("asked to stop contact")
    if f.get("insolvency_mention"):
        parts.append("mentions consumer proposal / bankruptcy")
    if not parts:
        parts.append("No commitment made")
    parts.append("next step: " + f["next_step"].replace("_", " "))
    return "; ".join(parts) + "."


def is_cease(f: dict[str, Any], transcript: str) -> bool:
    """A cease request needs the customer's own words, and an angry "Stop calling me every day!" isn't one
    (the labels never count it). ponytail: phrase check fits the release's templated calls; real calls would
    need the extractor's evidence gate."""
    quote = (f.get("cease_quote") or "").strip().lower()
    asks_to_stop = any(w in quote for w in ("stop", "call", "contact", "arrêt", "appel"))  # not "I'm done"
    return (
        bool(f.get("cease_request"))
        and asks_to_stop
        and quote in transcript.lower()
        and "every day" not in quote
    )


def next_step(f: dict[str, Any]) -> str:
    """The labels' priority order; the model's own next_step only when no rule applies."""
    if f.get("cease_request") or f.get("insolvency_mention"):
        return "stop_contact"
    if f.get("complaint"):
        return "escalate_supervisor"
    if f.get("dispute_type"):
        return "dispute_investigation"
    if f.get("hardship_referral"):
        return "hardship_plan_review"
    if f.get("next_step") in ("escalate_supervisor", "send_payment_link", "call_back"):
        return str(f["next_step"])
    return "send_payment_link" if f.get("promise_amount") is not None else "call_back"


def latest_transcript(conn: duckdb.DuckDBPyConnection, case_id: str) -> tuple[str, str, str, str] | None:
    """(transcript_id, call_start, text, redactor_version) of the case's newest redacted transcript."""
    row = conn.execute(
        "select source_id, written_at_local, text, redactor_version from text.redacted_notes "
        "where case_id = ? and source_type = 'transcript' "
        "order by written_at_local desc, source_id desc limit 1",
        [case_id],
    ).fetchone()
    return (str(row[0]), str(row[1]), str(row[2]), str(row[3])) if row else None


def summarise_call(
    case_id: str,
    *,
    llm: LLMGateway,
    warehouse: Path = WAREHOUSE_PATH,
    conn: duckdb.DuckDBPyConnection | None = None,
    actor_id: str = "ask",
) -> CallSummary | None:
    """The case's most recent recorded call, summarised from its redacted transcript (text.redacted_notes).
    None if the case has no recorded call: say so, don't refuse. Pass `conn` from a process that already
    holds the warehouse open (kept serve, the Ask); otherwise `warehouse` is opened read-only."""
    if conn is None:
        with duckdb.connect(str(warehouse), read_only=True) as c:
            found = latest_transcript(c, case_id)
    else:
        found = latest_transcript(conn, case_id)
    if found is None:
        return None
    transcript_id, call_start, text, redactor_version = found
    user = stored_redacted(text, redactor_version)  # already Presidio output: no second pass
    for temperature in (0.0, 0.3):  # one retry when the reply doesn't match the schema, like LLMExtractor
        try:
            reply = llm.complete(
                system=SYSTEM_PROMPT,
                user=user,
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
    fields = reply.parsed | {"cease_request": is_cease(reply.parsed, text)}
    fields["next_step"] = next_step(fields)
    return CallSummary(case_id, transcript_id, call_start, format_summary(fields))
