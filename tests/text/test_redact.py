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


def test_card_number_without_luhn_removed(redactor: PresidioRedactor) -> None:
    # Synthetic notes carry 16-digit cards that fail Luhn; the built-in recognizer misses them.
    out = redactor.redact("spoke w/ cust; card 4520 3572 3838 5812; CB scheduled").text
    assert "4520" not in out and "CB scheduled" in out


def test_french_note_keeps_content(redactor: PresidioRedactor) -> None:
    note = "client a appelé. a perdu son emploi en juin. demande si pmt peut être réduit. réf. équipe difficultés"
    assert redactor.redact(note).text == note


@pytest.mark.parametrize(
    "note",
    [
        "cust caleld in. PTP $40 Jun. 12. sent pmt lnik",
        "PARLÉ AU CLIENT. RAPPEL PRÉVU",
        "spoke w/ csut, can pay 55 on 3 juil",
    ],
)
def test_shorthand_typos_months_and_caps_kept(redactor: PresidioRedactor, note: str) -> None:
    assert redactor.redact(note).text == note


def test_titlecase_name_in_transcript_removed(redactor: PresidioRedactor) -> None:
    out = redactor.redact("agent: Puis-je parler à Daniel Morin?\ncustomer: C'est moi.").text
    assert "Daniel" not in out and "Morin" not in out


@pytest.mark.parametrize(
    "note,secret",
    [
        ("card 4520 766 9760 7290. CB scheduled", "766 9760"),  # a digit dropped
        ("crad 420 369 585 454", "369 585"),
        ("spoke w/ cust PTP 65 May 31 DOB 1987-01-13", "1987-01-13"),
        ("will try to pay 5 next payday; DOB 206-12-25; sent pmt link", "206-12-25"),
        ("RPC w/ cust - DOB 1987-0113 - CB scheduled", "1987-0113"),
    ],
)
def test_malformed_cards_and_dob_after_dates_removed(
    redactor: PresidioRedactor, note: str, secret: str
) -> None:
    assert secret not in redactor.redact(note).text


def test_phone_number_is_not_a_card(redactor: PresidioRedactor) -> None:
    assert "<PHONE_NUMBER>" in redactor.redact("call back at 416-555-0123").text


def test_dashed_numbers_without_dob_word_kept(redactor: PresidioRedactor) -> None:
    note = "PTP 10-12 the 5th, ref 2024-118"
    assert redactor.redact(note).text == note
