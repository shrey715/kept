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

PROMPT_VERSION = "extract-v4"

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
- promised_date: when the promised payment will be made, written exactly as the text gives it. Never
  add a year, month or day the text doesn't state; the system resolves relative dates itself.
  "Jan 3", "3 janv", "SEP 29" -> "01-03" / "09-29" (MM-DD); "the 2nd", "le 15", "23RD" -> "day:2" /
  "day:15" / "day:23" (no month written, so no month in the value);
  "Friday", "vendredi" -> "weekday:friday"; a full date with a year -> "YYYY-MM-DD";
  "next payday", "after payday", no date -> null.
- promised_amount: the promised amount as a plain number string like "140.00", else null.
- dispute: true only when the customer contests what the bank says they owe.
  true: "disputes the charge", "says pmt not applied", "says charges are fraud", "dispute opened",
  disputes a late fee, "billing error", "conteste les frais".
  false: "says bank issue w/ transfer", "refuses to pay", "wants to file a complaint", "veut porter
  plainte", "unhappy w/ # of calls", "says someone else uses card".
- cease_request: true only when the customer asks the bank to stop contacting them.
  true: "asked us to stop calling", "cease contact noted", "demande d'arrêter les appels".
  false: "unhappy w/ # of calls"; "cease contact noted" after the customer "filed bankruptcy" or a
  consumer proposal (that is a legal stay, not the customer's request).
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
        raw: dict[str, Any] | None = None
        for temperature in (0.0, 0.3):  # one retry: small local models sometimes break the schema
            try:
                reply = self.llm.complete(
                    system=SYSTEM_PROMPT,
                    user=text,
                    purpose=Purpose.TEXT_EXTRACT,
                    actor_id=self.actor_id,
                    json_schema=JSON_SCHEMA,
                    temperature=temperature,
                )
            except ValueError:
                continue
            if isinstance(reply.parsed, dict) and all(isinstance(reply.parsed.get(f), dict) for f in FIELDS):
                raw = reply.parsed
                break
        if raw is None:
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
            promised_date=field(
                "promised_date", lambda v: _date(v, anchor, raw["promised_date"].get("quote")), None
            ),
            promised_amount=field("promised_amount", _amount, None),
            dispute=field("dispute", _bool, False),
            cease_request=_cease(field("cease_request", _bool, False), text.text),
            third_party_present=field("third_party_present", _bool, False),
            extractor=f"llm:{PROMPT_VERSION}+cease-rule",
            extracted_at=datetime.now(UTC),
        )


# The local model reads anger about call frequency, and the stop that insolvency triggers, as a cease
# request; the labels (and the law) don't: a cease is the customer asking for no further contact.
_FREQUENCY_COMPLAINT = re.compile(r"every day|tous les jours|harass|done with this|plainte", re.IGNORECASE)
_INSOLVENCY = re.compile(r"bankrupt|consumer proposal|faillite|proposition de consommateur", re.IGNORECASE)
_ASKED_TO_STOP = re.compile(r"asked|stop calling|don't (call|contact)|arr[eê]t", re.IGNORECASE)


def _cease(v: ExtractedValue[bool], text: str) -> ExtractedValue[bool]:
    """A cease the model quoted from a frequency complaint, or from "cease contact noted" after an insolvency
    filing (a legal stay, held by its own flag), is not the customer's request. Agents confirm every cease."""
    quote = v.evidence.quote if v.evidence else ""
    if v.value and (
        _FREQUENCY_COMPLAINT.search(quote) or (_INSOLVENCY.search(text) and not _ASKED_TO_STOP.search(quote))
    ):
        return ExtractedValue(value=False, confidence=v.confidence)
    return v


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError(f"expected true/false, got {v!r}")
    return v


def _amount(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    s = re.sub(r"[\s$]", "", str(v))  # "$140", "17$", "1 635 $"
    s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{2}", s) else s.replace(",", "")  # "17,50" vs "1,635"
    try:
        return Decimal(s).quantize(CENT)
    except InvalidOperation as e:
        raise ValueError(f"bad amount {v!r}") from e


_MONTHS = re.compile(
    r"\b(jan|feb|f[ée]v|mar|apr|avr|may|mai|jun|juin|jul|juil|aug|ao[uû]|sep|oct|nov|dec|d[ée]c)|\d{1,2}[/-]\d",
    re.IGNORECASE,
)


def _date(v: Any, anchor: date | None, quote: str | None = None) -> date | None:
    """ISO date, or a relative form resolved against the note's date (None without one).
    A month-day value whose quote names no month ("the 10th") is read as a day of month:
    models fill in a month the text never gave."""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if quote and not _MONTHS.search(quote) and (m := re.fullmatch(r"(?:\d{4}-)?\d{2}-(\d{2})", s)):
        s = f"day:{int(m.group(1))}"
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


def transcript_text(turns: list[dict[str, Any]]) -> str:
    """One line per turn, "speaker: text", in turn order (call_transcripts JSON `turns`)."""
    return "\n".join(f"{t['speaker']}: {t['text']}" for t in sorted(turns, key=lambda t: t["turn_index"]))


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
