"""Silver cleaning rules: names, mixed DOB formats, phones, postal codes."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.data.clean import (
    name_match_key,
    normalize_name,
    normalize_phone_e164,
    normalize_postal_code,
    parse_dob,
)

TODAY = date(2026, 10, 3)


# ----------------------------------------------------------------- names
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("jane doe", "Jane Doe"),
        ("  JANE   DOE  ", "Jane Doe"),
        ("o'neil-smith", "O'Neil-Smith"),
        ("JOSÉ   ÁLVAREZ", "José Álvarez"),
        ("ｊａｎｅ", "Jane"),  # full-width -> NFKC
        ("jane\tdoe\n", "Jane Doe"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_normalize_name_empty_is_none(raw: str | None) -> None:
    assert normalize_name(raw) is None


@given(st.text(max_size=40))
def test_normalize_name_is_idempotent(raw: str) -> None:
    once = normalize_name(raw)
    assert normalize_name(once) == once


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  José  O'Neil ", "jose oneil"),
        ("ANNE-MARIE TREMBLAY", "anne marie tremblay"),
        ("Zoë", "zoe"),
    ],
)
def test_name_match_key(raw: str, expected: str) -> None:
    assert name_match_key(raw) == expected


def test_name_match_key_equal_for_cosmetic_variants() -> None:
    assert name_match_key("José O'Neil") == name_match_key("JOSE ONEIL") == name_match_key(" jose  o'neil ")


# ----------------------------------------------------------------- DOB
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1990-04-03", date(1990, 4, 3)),
        ("19900403", date(1990, 4, 3)),
        ("03-Apr-1990", date(1990, 4, 3)),
        ("3-APR-1990", date(1990, 4, 3)),
        ("25/12/1985", date(1985, 12, 25)),  # unambiguous: day > 12
        ("12/25/1985", date(1985, 12, 25)),  # unambiguous: day > 12
        (" 1990-04-03 ", date(1990, 4, 3)),
    ],
)
def test_parse_dob_accepts_known_formats(raw: str, expected: date) -> None:
    assert parse_dob(raw, today=TODAY) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "03/04/1990",  # ambiguous: quarantine, never guess
        "1990-02-30",  # impossible
        "2027-01-01",  # future
        "1899-01-01",  # older than 120 years
        "not a date",
        "",
        None,
        "1990-13-01",
    ],
)
def test_parse_dob_rejects_to_quarantine(raw: str | None) -> None:
    assert parse_dob(raw, today=TODAY) is None


def test_parse_dob_leap_day() -> None:
    assert parse_dob("2000-02-29", today=TODAY) == date(2000, 2, 29)
    assert parse_dob("1900-02-29", today=TODAY) is None


# ----------------------------------------------------------------- phones
@pytest.mark.parametrize(
    "raw",
    [
        "416-555-0123",
        "(416) 555-0123",
        "416.555.0123",
        "+1 416 555 0123",
        "1-416-555-0123",
        "4165550123",
        "416 555 0123 ext. 12",
        "+14165550123",
    ],
)
def test_phone_variants_normalise_to_one_e164(raw: str) -> None:
    assert normalize_phone_e164(raw) == "+14165550123"


@pytest.mark.parametrize("raw", [None, "", "555-0123", "123", "abcdefghij", "+1 000 555 0123"])
def test_invalid_phones_are_none(raw: str | None) -> None:
    assert normalize_phone_e164(raw) is None


@given(st.from_regex(r"\(?[2-9]\d{2}\)?[ .-]?[2-9]\d{2}[ .-]?\d{4}", fullmatch=True))
def test_phone_output_is_e164_or_none_and_idempotent(raw: str) -> None:
    out = normalize_phone_e164(raw)
    if out is not None:
        assert out.startswith("+1") and len(out) == 12 and out[1:].isdigit()
        assert normalize_phone_e164(out) == out


# ----------------------------------------------------------------- postal codes
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("m5v3l9", "M5V 3L9"),
        ("M5V 3L9", "M5V 3L9"),
        (" m5v-3l9 ", "M5V 3L9"),
        ("K1A0B1", "K1A 0B1"),
    ],
)
def test_postal_code_normalises(raw: str, expected: str) -> None:
    assert normalize_postal_code(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "12345",
        "M5V3L",
        "M5V3L99",
        "D5V3L9",  # D never valid
        "W5V3L9",  # W not valid first letter
        "Z5V3L9",  # Z not valid first letter
        "M5O3L9",  # O never valid
        "MMV3L9",
    ],
)
def test_invalid_postal_codes_are_none(raw: str | None) -> None:
    assert normalize_postal_code(raw) is None
