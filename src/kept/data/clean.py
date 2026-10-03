"""Silver: cleaning rules for names, mixed date-of-birth formats, phones and postal codes.

Each function returns None for input it can't parse; the caller sends that row
to quarantine with the reason. Functions must be pure and idempotent so they can
be registered as DuckDB UDFs in dbt or ported to SQL macros.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
_NAME_PART = re.compile(r"[^-'\u2019]+")
_DOB = (
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), "ymd"),  # ISO (customers, external)
    (re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"), "ymd"),  # loan_accounts
    (re.compile(r"(\d{4})(\d{2})(\d{2})"), "ymd"),  # deposit_accounts
    (re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})"), "dmy_mon"),  # 03-Apr-1990
    (re.compile(r"([A-Za-z]{3}) (\d{1,2}),? (\d{4})"), "mon_dy"),  # May 04 1948 (customers.dob_raw)
    (re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})"), "num"),  # customers 25/07/1986, cards 14-03-1988
)
_POSTAL = re.compile(r"[ABCEGHJKLMNPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\d[ABCEGHJ-NPRSTV-Z]\d")
_EXTENSION = re.compile(r"\s*(?:ext\.?|x|#)\s*\d+\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    table: str
    row_id: str
    column: str
    raw_value: str | None
    reason: str


def _title_once(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw)
    # capitalize() (not upper()[0] + lower()) keeps "ß"-style expansions stable on a second pass
    return unicodedata.normalize(
        "NFKC", " ".join(_NAME_PART.sub(lambda m: m.group().capitalize(), w) for w in text.split())
    )


def normalize_name(raw: str | None) -> str | None:
    """Unicode NFKC, collapse whitespace, strip, title-case word parts (incl. hyphen
    and apostrophe parts: "o'neil-smith" -> "O'Neil-Smith"). Keep accents. Empty -> None."""
    if raw is None:
        return None
    out = _title_once(raw)
    for _ in range(3):  # a few exotic code points change again when re-cased: settle to a fixed point
        nxt = _title_once(out)
        if nxt == out:
            break
        out = nxt
    return out or None


def name_match_key(raw: str | None) -> str | None:
    """Matching key for Splink: normalised, accents removed, lower case, letters and
    single spaces only. "  José  O'Neil " -> "jose oneil"."""
    name = normalize_name(raw)
    if name is None:
        return None
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    letters = "".join(c if c.isalpha() else " " if c in "- " else "" for c in stripped.lower())
    return " ".join(letters.split()) or None


def _dob_parts(text: str, day_first: bool | None) -> tuple[int, int, int] | None:
    """(year, month, day) for the first matching format, or None."""
    for pattern, kind in _DOB:
        if not (m := pattern.fullmatch(text)):
            continue
        a, b, c = m.groups()
        if kind == "ymd":
            return int(a), int(b), int(c)
        if kind == "dmy_mon":
            return (int(c), _MONTHS[b.lower()], int(a)) if b.lower() in _MONTHS else None
        if kind == "mon_dy":
            return (int(c), _MONTHS[a.lower()], int(b)) if a.lower() in _MONTHS else None
        x, y = int(a), int(b)  # "num": two numbers then the year
        if x > 12 or (day_first is True and y <= 12):
            return int(c), y, x  # day first
        if y > 12 or x == y or day_first is False:
            return int(c), x, y  # month first
        return None  # both <= 12 and different: ambiguous, never guess
    return None


def parse_dob(raw: str | None, *, today: date, day_first: bool | None = None) -> date | None:
    """Parse the mixed date-of-birth formats. Accept ISO (YYYY-MM-DD), YYYY/MM/DD, YYYYMMDD,
    DD-Mon-YYYY, Mon DD YYYY, and numeric A/B/YYYY or A-B-YYYY only when unambiguous (one part
    > 12, or both equal). `day_first` is for a source whose format the data dictionary fixes
    (cards: DD-MM-YYYY): it settles the ambiguous case; the default None never guesses.
    Ambiguous (03/04/1990), impossible (1990-02-30), future, or older than 120
    years -> None (quarantine)."""
    if raw is None or (parts := _dob_parts(raw.strip(), day_first)) is None:
        return None
    try:
        born = date(*parts)
    except ValueError:
        return None
    try:
        oldest = today.replace(year=today.year - 120)
    except ValueError:  # today is 29 Feb
        oldest = today.replace(year=today.year - 120, day=28)
    return born if oldest <= born <= today else None


def normalize_phone_e164(raw: str | None, *, default_region: str = "CA") -> str | None:
    """Canadian/NANP numbers to E.164 (+14165550123). Strip extensions. Invalid -> None."""
    # ponytail: NANP only (CA/US share +1); other regions need the phonenumbers library
    if raw is None or default_region not in ("CA", "US"):
        return None
    text = _EXTENSION.sub("", raw.strip())
    if not re.fullmatch(r"\+?[\d\s().-]+", text):
        return None  # letters, or masked digits like 519555xxx42
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    elif text.startswith("+") and len(digits) != 11:
        return None
    # NANP: area code and exchange start with 2-9
    return (
        f"+1{digits}" if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789" else None
    )


def normalize_postal_code(raw: str | None) -> str | None:
    """Canadian postal code to 'A1A 1A1'. Letters D, F, I, O, Q, U never valid;
    W and Z not valid as the first letter. Invalid -> None."""
    if raw is None:
        return None
    code = re.sub(r"[\s-]", "", raw).upper()
    if len(code) != 6:
        return None
    # keyed-in typo seen in the data: letter O where a digit belongs
    code = "".join(c.replace("O", "0") if i % 2 else c for i, c in enumerate(code))
    return f"{code[:3]} {code[3:]}" if _POSTAL.fullmatch(code) else None
