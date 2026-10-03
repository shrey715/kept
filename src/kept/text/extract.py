"""LLM extraction of hardship, promise intent, dispute, cease and third party from
notes and call transcripts. Every value comes with a supporting quote."""

from __future__ import annotations

from datetime import date, datetime

from kept.contracts.features import Evidence, RedactedText, TextExtraction
from kept.contracts.interfaces import LLMGateway

PROMPT_VERSION = "extract-v0"


def resolve_day_of_month(day: int, *, written_at: date) -> date:
    """Notes say "can pay 800 on the 2nd": the next date on or after written_at whose day of
    month is `day`. If a month has no such day (31st in a 30-day month), skip to the next
    month that does. day outside 1..31 -> ValueError."""
    raise NotImplementedError("Track C")


def locate_quote(text: str, quote: str, *, source_id: str) -> Evidence | None:
    """Evidence with char offsets if `quote` occurs in `text` (exact match after
    whitespace normalisation), else None. Never fuzzy: a quote that isn't in the
    text is a hallucination."""
    raise NotImplementedError("Track C")


class LLMExtractor:
    """Implements kept.contracts.interfaces.TextExtractor.

    Rules:
      * any value whose quote can't be located is dropped to its "nothing found"
        value (NONE / False / None) with confidence 0;
      * hardship_signal CLEAR requires evidence; otherwise downgrade to POSSIBLE;
      * the LLM reply must validate against the JSON schema, else ValueError.
    """

    def __init__(self, llm: LLMGateway, *, actor_id: str = "system:text-extract") -> None:
        raise NotImplementedError("Track C")

    def extract(
        self, text: RedactedText, *, source_id: str, case_id: str, written_at: datetime | None = None
    ) -> TextExtraction:
        """written_at (note_ts / call_start_ts) anchors relative dates via resolve_day_of_month."""
        raise NotImplementedError("Track C")


def confirm(
    extraction: TextExtraction, *, agent_id: str, at: datetime, edits: dict[str, object] | None = None
) -> TextExtraction:
    """Agent confirms or edits extracted values at wrap-up. Returns a new extraction
    with confirmed_by_agent_id set; edited values carry the agent's value and confidence 1."""
    raise NotImplementedError("Track C")
