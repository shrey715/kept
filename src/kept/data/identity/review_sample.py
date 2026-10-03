"""The 300-pair sample a data steward reviews to check match precision (target 98%, config
MATCH_PRECISION_TARGET). Written to data/labels/match_pairs.csv with `is_true_match` blank: a person
fills it in, then `kept gate` reports the precision of the reviewed rows (check_review_precision).

A pair is a linked key and its cluster's anchor (the CRM key if the cluster has one, else the smallest
key), so the reviewer answers "is this the same person as that one?" for each. Sampled at random and in
proportion to how many keys each kind of link put in a cluster, so the plain share of "yes" answers is
an unbiased estimate of the overall precision. Collections keys are left out: they carry no attributes
to judge (the case row copies the CRM ID).
"""

from __future__ import annotations

import duckdb
import pandas as pd

SHOWN = ["name_key", "first_name_key", "dob", "phone_e164", "postal_code"]


def review_sample(
    conn: duckdb.DuckDBPyConnection, crosswalk: pd.DataFrame, *, n: int = 300, seed: int = 7
) -> pd.DataFrame:
    """n pairs (fewer if there are fewer linked keys), columns for the reviewer and a blank is_true_match."""
    active = crosswalk[
        crosswalk["valid_to"].isna() & crosswalk["match_review_status"].isin(["auto", "steward_approved"])
    ]
    sizes = active.groupby("golden_customer_id")["source_key"].transform("size")
    active = active[(sizes > 1) & (active["source_system"] != "collections")].copy()
    # the anchor of a cluster: its CRM key if any, else its smallest key
    active["_crm_first"] = (active["source_system"] != "crm").astype(int)
    anchor = (
        active.sort_values(["golden_customer_id", "_crm_first", "source_system", "source_key"])
        .drop_duplicates("golden_customer_id")
        .set_index("golden_customer_id")[["source_system", "source_key"]]
    )
    linked = active.join(anchor, on="golden_customer_id", rsuffix="_anchor")
    linked = linked[
        (linked["source_system"] != linked["source_system_anchor"])
        | (linked["source_key"] != linked["source_key_anchor"])
    ]
    linked["stratum"] = linked["match_rule"].map(lambda r: "splink" if r == "splink" else "exact")

    shares = linked["stratum"].value_counts(normalize=True)
    parts = []
    for stratum, share in shares.items():
        pool = linked[linked["stratum"] == stratum]
        parts.append(pool.sample(min(len(pool), round(n * share)), random_state=seed))
    picked = pd.concat(parts).sample(frac=1, random_state=seed).head(n).reset_index(drop=True)

    records = conn.execute(
        "select source_system, source_key, " + ", ".join(SHOWN) + " from silver.int_identity_records"
    ).df()
    side = records.set_index(["source_system", "source_key"])

    def attributes(system: str, key: str, prefix: str) -> pd.DataFrame:
        found = side.reindex(pd.MultiIndex.from_frame(picked[[system, key]])).reset_index(drop=True)
        return found.add_prefix(f"{prefix}_")

    out = pd.concat(
        [
            pd.DataFrame(
                {
                    "pair_id": [f"MP-{i + 1:03d}" for i in range(len(picked))],
                    "stratum": picked["stratum"],
                    "rule": picked["match_rule"],
                    "score": picked["match_score"],
                    "left_system": picked["source_system"],
                    "left_key": picked["source_key"],
                    "right_system": picked["source_system_anchor"],
                    "right_key": picked["source_key_anchor"],
                }
            ),
            attributes("source_system", "source_key", "left"),
            attributes("source_system_anchor", "source_key_anchor", "right"),
        ],
        axis=1,
    )
    out["predicted_link"] = True
    out["is_true_match"] = ""  # the reviewer fills in true / false
    return out
