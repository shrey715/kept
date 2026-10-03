"""Silver: cleaning rules for names, mixed date-of-birth formats, phones and postal codes.

Each function returns None for input it can't parse; the caller sends that row
to quarantine with the reason. Functions must be pure and idempotent so they can
be registered as DuckDB UDFs in dbt or ported to SQL macros.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    table: str
    row_id: str
    column: str
    raw_value: str | None
    reason: str


def normalize_name(raw: str | None) -> str | None:
    """Unicode NFKC, collapse whitespace, strip, title-case word parts (incl. hyphen
    and apostrophe parts: "o'neil-smith" -> "O'Neil-Smith"). Keep accents. Empty -> None."""
    raise NotImplementedError("Track A")


def name_match_key(raw: str | None) -> str | None:
    """Matching key for Splink: normalised, accents removed, lower case, letters and
    single spaces only. "  José  O'Neil " -> "jose oneil"."""
    raise NotImplementedError("Track A")


def parse_dob(raw: str | None, *, today: date) -> date | None:
    """Parse the mixed date-of-birth formats. Accept ISO (YYYY-MM-DD), YYYYMMDD,
    DD-Mon-YYYY, and slash dates only when unambiguous (one part > 12).
    Ambiguous (03/04/1990), impossible (1990-02-30), future, or older than 120
    years -> None (quarantine)."""
    raise NotImplementedError("Track A")


def normalize_phone_e164(raw: str | None, *, default_region: str = "CA") -> str | None:
    """Canadian/NANP numbers to E.164 (+14165550123). Strip extensions. Invalid -> None."""
    raise NotImplementedError("Track A")


def normalize_postal_code(raw: str | None) -> str | None:
    """Canadian postal code to 'A1A 1A1'. Letters D, F, I, O, Q, U never valid;
    W and Z not valid as the first letter. Invalid -> None."""
    raise NotImplementedError("Track A")
