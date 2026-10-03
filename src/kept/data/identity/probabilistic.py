"""Splink scoring on the pairs exact rules didn't link: name, DOB, phone, postal code."""

from __future__ import annotations

from typing import Any

import pandas as pd

from kept.config import STEWARD_REVIEW_THRESHOLD

MATCH_COLUMNS = ("name_key", "dob", "phone_e164", "postal_code")
# optional extra: the full first name where the system holds one (twins share surname and initial)
OPTIONAL_COLUMNS = ("first_name_key",)

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
    return {
        "link_type": "dedupe_only",
        "unique_id_column_name": "unique_id",
        # every rule is a pair of agreeing identifiers: blocking on one weak column (postal code)
        # alone would put every pair in a postal area on the candidate list
        "blocking_rules": [
            "l.phone_e164 = r.phone_e164",
            "l.dob = r.dob and l.postal_code = r.postal_code",
            "l.dob = r.dob and substr(l.name_key, 1, 3) = substr(r.name_key, 1, 3)",
            "l.name_key = r.name_key and l.postal_code = r.postal_code",
        ],
        "comparisons": [
            # name_key = "<surname> <initial>", compared as two parts: a different initial counts against
            {"column": "surname", "kind": "jaro_winkler", "thresholds": [0.92, 0.80]},
            {"column": "first_initial", "kind": "exact"},
            {"column": "first_name_key", "kind": "jaro_winkler", "thresholds": [0.92, 0.80]},
            {"column": "dob", "kind": "damerau_levenshtein", "thresholds": [1, 2]},  # typos, swapped digits
            {"column": "phone_e164", "kind": "exact"},
            {"column": "postal_code", "kind": "exact"},
        ],
        # EM trains the parameters on the data itself: pairs agreeing on these also agree on the rest
        "training_blocks": [["dob"], ["name_key"], ["phone_e164"]],
        "deterministic_rule": ["name_key", "dob"],  # for the prior: "two random records match"
        "recall_of_deterministic_rule": 0.7,
    }


def _comparison(spec: dict[str, object]) -> Any:
    from splink import comparison_library as cl

    column, kind = str(spec["column"]), spec["kind"]
    if kind == "jaro_winkler":
        return cl.JaroWinklerAtThresholds(column, spec["thresholds"])  # type: ignore[arg-type]
    if kind == "damerau_levenshtein":
        return cl.DamerauLevenshteinAtThresholds(column, spec["thresholds"])  # type: ignore[arg-type]
    return cl.ExactMatch(column)


def score_pairs(records: pd.DataFrame, *, exclude_pairs: pd.DataFrame | None = None) -> pd.DataFrame:
    """Splink match probabilities for candidate pairs.

    Input: one row per source key with source_system, source_key and MATCH_COLUMNS.
    Output columns: left_system, left_key, right_system, right_key, rule ("splink"),
    score in [0, 1]. Pairs already in exclude_pairs (exact links) are not rescored.
    Only pairs at or above the steward-review threshold are returned: below it a pair is not a link.
    """
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    spec = build_settings()
    people = records.assign(unique_id=records["source_system"] + ":" + records["source_key"])
    for col in OPTIONAL_COLUMNS:
        if col not in people:
            people[col] = None
        people[col] = people[col].astype(
            "string"
        )  # an all-null column would otherwise reach DuckDB as INTEGER
    parts = people["name_key"].str.split(" ", n=1, expand=True)
    people["surname"], people["first_initial"] = parts[0], (parts[1] if parts.shape[1] > 1 else None)
    people = people[
        [
            "unique_id",
            "source_system",
            "source_key",
            *MATCH_COLUMNS,
            *OPTIONAL_COLUMNS,
            "surname",
            "first_initial",
        ]
    ]
    settings = SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name=str(spec["unique_id_column_name"]),
        comparisons=[_comparison(c) for c in spec["comparisons"]],  # type: ignore[attr-defined,misc]
        blocking_rules_to_generate_predictions=list(spec["blocking_rules"]),  # type: ignore[call-overload]
        additional_columns_to_retain=["source_system", "source_key"],
    )
    db = DuckDBAPI()
    linker = Linker(db.register(people), settings)
    linker.training.estimate_probability_two_random_records_match(
        [block_on(*spec["deterministic_rule"])],  # type: ignore[misc]
        recall=float(spec["recall_of_deterministic_rule"]),  # type: ignore[arg-type]
    )
    linker.training.estimate_u_using_random_sampling(max_pairs=2_000_000, seed=1)
    for block in spec["training_blocks"]:  # type: ignore[attr-defined]
        linker.training.estimate_parameters_using_expectation_maximisation(block_on(*block))
    scored = linker.inference.predict(
        threshold_match_probability=STEWARD_REVIEW_THRESHOLD
    ).as_pandas_dataframe()  # type: ignore[no-untyped-call]

    out = pd.DataFrame(
        {
            "left_system": scored["source_system_l"],
            "left_key": scored["source_key_l"],
            "right_system": scored["source_system_r"],
            "right_key": scored["source_key_r"],
            "rule": "splink",
            "score": scored["match_probability"].clip(0, 1),
        }
    )
    swap = (out.left_system > out.right_system) | (
        (out.left_system == out.right_system) & (out.left_key > out.right_key)
    )
    out.loc[swap, ["left_system", "left_key", "right_system", "right_key"]] = out.loc[
        swap, ["right_system", "right_key", "left_system", "left_key"]
    ].to_numpy()
    if exclude_pairs is not None and len(exclude_pairs):
        pair = ["left_system", "left_key", "right_system", "right_key"]
        ex = exclude_pairs[pair].copy()
        flipped = ex.rename(
            columns={
                "left_system": "right_system",
                "left_key": "right_key",
                "right_system": "left_system",
                "right_key": "left_key",
            }
        )
        gone = pd.concat([ex, flipped]).drop_duplicates()
        out = out.merge(gone.assign(_x=1), on=pair, how="left")
        out = out[out["_x"].isna()].drop(columns="_x")
    return out.sort_values(["left_system", "left_key", "right_system", "right_key"]).reset_index(drop=True)
