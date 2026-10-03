"""LLM extraction of hardship, promise intent, dispute, cease and third party from
notes and call transcripts. Every value comes with a supporting quote."""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from kept.common.llm import Purpose
from kept.config import CENT
from kept.contracts.enums import HardshipSignal
from kept.contracts.features import Evidence, ExtractedValue, RedactedText, StatedReason, TextExtraction
from kept.contracts.interfaces import LLMGateway

PROMPT_VERSION = "extract-v1"

SYSTEM_PROMPT = """You read one collections agent note or call transcript (English or French; personal \
details are already replaced by placeholders like <PERSON>) and extract eight fields.

For every field return {"value": ..., "quote": ..., "confidence": 0..1}.
"quote" must be copied character for character from the text (the shortest span that supports the value),
or null when nothing in the text supports a positive value. Never paraphrase or translate a quote.

Fields:
- hardship_signal: "clear" when the customer states a specific hardship (job loss, layoff, reduced hours or
  income, illness, disability, separation or divorce, bereavement, disaster or evacuation, mortgage rate reset
  they can't afford, waiting for EI); "possible" when there are hints without a stated cause (budget
  very tight, struggling, asks to reduce payments, crying); else "none".
- stated_reason: the hardship cause: "job_loss" (incl. waiting for EI), "reduced_income" (fewer hours/shifts,
  pay cut), "medical" (illness, disability), "bereavement", "other" (separation, rate reset, disaster, other),
  or "none" when no hardship cause is stated. Forgetting the due date or payroll timing is "none".
- promise_intent: true when the customer commits to pay (a promise to pay, PTP), else false.
- promised_date: when the promised payment will be made, as "YYYY-MM-DD" if the year is clear,
  "MM-DD" if only month and day are given, "day:N" for "the Nth", "weekday:<monday..sunday>" for a weekday,
  else null.
- promised_amount: the promised amount as a plain number string like "140.00", else null.
- dispute: true when the customer disputes the debt, a charge, a fee or the amount owed.
- cease_request: true when the customer asks the bank to stop calling or contacting them.
- third_party_present: true when someone other than the customer takes part (spouse, family member,
  representative, "3rd party on line"), else false.

Reply with JSON only."""

_FIELD = {
    "type": "object",
    "properties": {
        "value": {},
        "quote": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["value", "quote", "confidence"],
}
FIELDS = (
    "hardship_signal",
    "stated_reason",
    "promise_intent",
    "promised_date",
    "promised_amount",
    "dispute",
    "cease_request",
    "third_party_present",
)
JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {f: _FIELD for f in FIELDS},
    "required": list(FIELDS),
}

_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}


def resolve_day_of_month(day: int, *, written_at: date) -> date:
    """Notes say "can pay 800 on the 2nd": the next date on or after written_at whose day of
    month is `day`. If a month has no such day (31st in a 30-day month), skip to the next
    month that does. day outside 1..31 -> ValueError."""
    if not 1 <= day <= 31:
        raise ValueError(f"day of month must be 1..31, got {day}")
    year, month = written_at.year, written_at.month
    while True:
        if day <= calendar.monthrange(year, month)[1] and (d := date(year, month, day)) >= written_at:
            return d
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def locate_quote(text: str, quote: str, *, source_id: str) -> Evidence | None:
    """Evidence with char offsets if `quote` occurs in `text` (exact match after
    whitespace normalisation), else None. Never fuzzy: a quote that isn't in the
    text is a hallucination."""
    words = quote.split()
    if not words:
        return None
    # Case-insensitive: models re-case quotes. The Evidence keeps the text's own slice.
    m = re.search(r"\s+".join(map(re.escape, words)), text, flags=re.IGNORECASE)
    if m is None:
        return None
    return Evidence(quote=m.group(0), source_id=source_id, char_start=m.start(), char_end=m.end())


class LLMExtractor:
    """Implements kept.contracts.interfaces.TextExtractor.

    Rules:
      * any value whose quote can't be located is dropped to its "nothing found"
        value (NONE / False / None) with confidence 0;
      * hardship_signal CLEAR requires evidence; otherwise downgrade to POSSIBLE;
      * the LLM reply must validate against the JSON schema, else ValueError.
    """

    def __init__(self, llm: LLMGateway, *, actor_id: str = "system:text-extract") -> None:
        self.llm, self.actor_id = llm, actor_id

    def extract(
        self, text: RedactedText, *, source_id: str, case_id: str, written_at: datetime | None = None
    ) -> TextExtraction:
        """written_at (note_ts / call_start_ts) anchors relative dates via resolve_day_of_month."""
        reply = self.llm.complete(
            system=SYSTEM_PROMPT,
            user=text,
            purpose=Purpose.TEXT_EXTRACT,
            actor_id=self.actor_id,
            json_schema=JSON_SCHEMA,
        )
        raw = reply.parsed
        if not isinstance(raw, dict) or not all(isinstance(raw.get(f), dict) for f in FIELDS):
            raise ValueError(f"extraction reply for {source_id} doesn't match the schema")

        def field(name: str, parse: Any, nothing: Any) -> ExtractedValue[Any]:
            item = raw[name]
            confidence = float(item.get("confidence", 0))
            value = parse(item.get("value"))
            if value == nothing:
                return ExtractedValue(value=nothing, confidence=confidence)
            evidence = locate_quote(text.text, item.get("quote") or "", source_id=source_id)
            if evidence is None:
                return ExtractedValue(value=nothing, confidence=0.0)
            return ExtractedValue(value=value, evidence=evidence, confidence=confidence)

        hardship = raw["hardship_signal"]
        signal = HardshipSignal(hardship.get("value"))
        hardship_ev = locate_quote(text.text, hardship.get("quote") or "", source_id=source_id)
        if signal is HardshipSignal.CLEAR and hardship_ev is None:
            signal = HardshipSignal.POSSIBLE  # an unquoted hardship still protects the customer
        anchor = written_at.date() if written_at else None
        return TextExtraction(
            source_id=source_id,
            case_id=case_id,
            hardship_signal=ExtractedValue(
                value=signal,
                evidence=hardship_ev if signal is not HardshipSignal.NONE else None,
                confidence=float(hardship.get("confidence", 0)),
            ),
            stated_reason=field("stated_reason", StatedReason, StatedReason.NONE),
            promise_intent=field("promise_intent", _bool, False),
            promised_date=field("promised_date", lambda v: _date(v, anchor), None),
            promised_amount=field("promised_amount", _amount, None),
            dispute=field("dispute", _bool, False),
            cease_request=field("cease_request", _bool, False),
            third_party_present=field("third_party_present", _bool, False),
            extractor=f"llm:{PROMPT_VERSION}",
            extracted_at=datetime.now(UTC),
        )


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError(f"expected true/false, got {v!r}")
    return v


def _amount(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").lstrip("$").strip()).quantize(CENT)
    except InvalidOperation as e:
        raise ValueError(f"bad amount {v!r}") from e


def _date(v: Any, anchor: date | None) -> date | None:
    """ISO date, or a relative form resolved against the note's date (None without one)."""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    if anchor is None:
        return None
    if m := re.fullmatch(r"day:(\d{1,2})", s):
        return resolve_day_of_month(int(m.group(1)), written_at=anchor)
    if m := re.fullmatch(r"weekday:([a-z]+)", s):
        if m.group(1) not in _WEEKDAYS:
            return None
        return anchor + timedelta(days=(_WEEKDAYS[m.group(1)] - anchor.weekday()) % 7)
    if m := re.fullmatch(r"(\d{2})-(\d{2})", s):
        month, day = int(m.group(1)), int(m.group(2))
        for year in (anchor.year, anchor.year + 1):
            try:
                if (d := date(year, month, day)) >= anchor:
                    return d
            except ValueError:
                return None
    return None


def confirm(
    extraction: TextExtraction, *, agent_id: str, at: datetime, edits: dict[str, object] | None = None
) -> TextExtraction:
    """Agent confirms or edits extracted values at wrap-up. Returns a new extraction
    with confirmed_by_agent_id set; edited values carry the agent's value and confidence 1."""
    data = extraction.model_dump()
    for name, value in (edits or {}).items():
        if name not in FIELDS:
            raise ValueError(f"not an extracted field: {name}")
        data[name] = {"value": value, "evidence": None, "confidence": 1.0}  # the agent is the evidence
    data["confirmed_by_agent_id"] = agent_id
    return TextExtraction.model_validate(data)
