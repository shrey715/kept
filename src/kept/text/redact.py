"""Presidio redaction. The only place a RedactedText is constructed.

Inputs: agent_notes.note_text (redaction_status none / auto_redacted / needs_review),
call_transcripts turns[].text (pii_redaction_applied only covers DOB and national ID, so we
redact everything again), and contact_history.sms_reply_text. All three are Direct PII in
the data dictionary.
"""

from __future__ import annotations

from kept.contracts.features import RedactedText

# Entities we always remove. Canadian SIN and bank/card numbers need custom recognizers.
ENTITIES = (
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "CREDIT_CARD",
    "CA_SIN",
    "IBAN_CODE",
    "BANK_ACCOUNT",
    "LOCATION",
    "DATE_OF_BIRTH",
    "CA_POSTAL_CODE",
    "IP_ADDRESS",
    "URL",
)


class PresidioRedactor:
    """Implements kept.contracts.interfaces.Redactor.

    Replaces each entity with a typed placeholder: <PERSON>, <PHONE_NUMBER> ...
    Must be idempotent: redact(redact(x).text).text == redact(x).text.
    Money amounts and ordinary dates (e.g. "3 Oct", "$140") are kept: extraction needs them.
    """

    version: str = "presidio-v0"

    def __init__(self, *, language: str = "en") -> None:
        raise NotImplementedError("Track C")

    def redact(self, text: str) -> RedactedText:
        raise NotImplementedError("Track C")
