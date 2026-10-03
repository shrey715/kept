"""Presidio redaction (integration: needs `uv sync --extra text` and a spaCy model)."""

from __future__ import annotations

import pytest

from kept.contracts import RedactedText
from kept.text.redact import PresidioRedactor

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redactor() -> PresidioRedactor:
    pytest.importorskip("presidio_analyzer")
    return PresidioRedactor()


NOTE = (
    "Spoke with Jane Doe, phone 416-555-0123, email jane.doe@example.com. "
    "SIN 046 454 286. Card 4111 1111 1111 1111. Lives at M5V 3L9. "
    "Says shifts cut at the plant since Aug. Can pay $140 on 3 Oct."
)
SECRETS = [
    "Jane",
    "Doe",
    "416-555-0123",
    "jane.doe@example.com",
    "046 454 286",
    "4111 1111 1111 1111",
    "M5V 3L9",
]


def test_returns_redacted_text_with_version(redactor: PresidioRedactor) -> None:
    r = redactor.redact(NOTE)
    assert isinstance(r, RedactedText) and r.redactor_version


@pytest.mark.parametrize("secret", SECRETS)
def test_personal_details_removed(redactor: PresidioRedactor, secret: str) -> None:
    assert secret not in redactor.redact(NOTE).text


def test_typed_placeholders(redactor: PresidioRedactor) -> None:
    text = redactor.redact(NOTE).text
    for placeholder in ("<PERSON>", "<PHONE_NUMBER>", "<EMAIL_ADDRESS>", "<CREDIT_CARD>"):
        assert placeholder in text
    assert {"PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS"} <= set(redactor.redact(NOTE).entity_types_removed)


def test_keeps_what_extraction_needs(redactor: PresidioRedactor) -> None:
    text = redactor.redact(NOTE).text
    assert "$140" in text and "3 Oct" in text and "shifts cut at the plant" in text


def test_idempotent(redactor: PresidioRedactor) -> None:
    once = redactor.redact(NOTE).text
    assert redactor.redact(once).text == once


@pytest.mark.parametrize("text", ["", "   ", "Customer will call back."])
def test_no_pii_passes_through(redactor: PresidioRedactor, text: str) -> None:
    assert redactor.redact(text).text == text
