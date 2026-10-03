"""Group data/labels/match_pairs.csv so a person can review the clear pairs fast and the doubtful ones slowly.

Adds `tier` (1 clear, 2 check, 3 look closely) and `agree` (per-field = same, x differs, ? one side missing),
sorts by tier, and leaves `is_true_match` untouched. Refuses to run once any pair has been labelled.
"""

from pathlib import Path

import pandas as pd

PATH = Path("data/labels/match_pairs.csv")
FIELDS = {"name": "name_key", "first": "first_name_key", "dob": "dob", "phone": "phone_e164", "postal": "postal_code"}


def state(d: pd.DataFrame, col: str) -> pd.Series:
    left, right = d[f"left_{col}"], d[f"right_{col}"]
    return pd.Series("=", index=d.index).mask(left != right, "x").mask(left.isna() | right.isna(), "?")


def tier(s: dict[str, pd.Series]) -> pd.Series:
    differs = pd.concat(s.values(), axis=1).eq("x").any(axis=1)
    corroborated = s["phone"].eq("=") | s["postal"].eq("=")
    clear = s["name"].eq("=") & s["dob"].eq("=") & corroborated & ~differs
    return pd.Series(2, index=differs.index).mask(clear, 1).mask(differs, 3)


def main() -> None:
    d = pd.read_csv(PATH, dtype=str)
    if d["is_true_match"].notna().any():
        raise SystemExit("some pairs are already labelled; not reordering")
    d = d.drop(columns=[c for c in ("tier", "agree") if c in d])
    s = {k: state(d, c) for k, c in FIELDS.items()}
    d.insert(1, "tier", tier(s))
    d.insert(2, "agree", pd.concat([k + s[k] for k in s], axis=1).agg(" ".join, axis=1))
    d.sort_values(["tier", "stratum", "pair_id"]).to_csv(PATH, index=False)
    print(d["tier"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
