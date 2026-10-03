"""Splink scoring on the pairs exact rules didn't link: name, DOB, phone, postal code."""

from __future__ import annotations

import pandas as pd

MATCH_COLUMNS = ("name_key", "dob", "phone_e164", "postal_code")

# Where each match column comes from, per source system (data dictionary names).
# silver cleans them into MATCH_COLUMNS with kept.data.clean.
IDENTITY_COLUMNS: dict[str, dict[str, str]] = {
    "crm": {
        "name": "full_name_raw",
        "dob": "dob_raw",
        "phone": "primary_phone_raw",
        "postal": "postal_code_raw",
    },
    "card": {
        "name": "cardholder_name_raw",
        "dob": "cardholder_dob_raw",
        "phone": "cardholder_phone_raw",
        "postal": "cardholder_postal_raw",
    },
    "loan": {
        "name": "borrower_name_raw",
        "dob": "borrower_dob_raw",
        "phone": "borrower_phone_raw",
        "postal": "borrower_postal_raw",
    },
    "deposit": {
        "name": "holder_name_raw",
        "dob": "holder_dob_raw",
        "phone": "holder_phone_raw",
        "postal": "holder_postal_raw",
    },
    "bureau": {
        "name": "subject_name_reported",
        "dob": "subject_dob_reported",
        "postal": "subject_address_reported",
    },
}


def build_settings() -> dict[str, object]:
    """Splink settings: blocking rules and comparisons on MATCH_COLUMNS.
    Must not block or compare on any protected attribute."""
    raise NotImplementedError("Track A")


def score_pairs(records: pd.DataFrame, *, exclude_pairs: pd.DataFrame | None = None) -> pd.DataFrame:
    """Splink match probabilities for candidate pairs.

    Output columns: left_system, left_key, right_system, right_key, rule ("splink"),
    score in [0, 1]. Pairs already in exclude_pairs (exact links) are not rescored.
    """
    raise NotImplementedError("Track A")
