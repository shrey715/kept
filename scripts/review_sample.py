"""Write the 300-pair review sample (Track A, Phase 4):

    uv run python scripts/review_sample.py [--n 300] [--seed 7] [--force]

Reads the newest identity crosswalk in data/exports/identity_crosswalk and silver.int_identity_records,
writes data/labels/match_pairs.csv with `is_true_match` blank. Refuses to overwrite a file someone has
started reviewing unless --force.
"""

from __future__ import annotations

import argparse

import pandas as pd

from kept.common.db import connect
from kept.config import DATA_DIR, EXPORT_DIR
from kept.data.identity.pipeline import latest_crosswalk
from kept.data.identity.review_sample import review_sample

OUT = DATA_DIR / "labels" / "match_pairs.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if OUT.exists() and not args.force:
        reviewed = pd.read_csv(OUT)["is_true_match"].notna().sum()
        raise SystemExit(f"{OUT} exists ({reviewed} rows reviewed): use --force to overwrite it")
    crosswalk_file = latest_crosswalk(EXPORT_DIR / "identity_crosswalk")
    conn = connect(read_only=True)
    try:
        sample = review_sample(conn, pd.read_parquet(crosswalk_file), n=args.n, seed=args.seed)
    finally:
        conn.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(OUT, index=False)
    print(f"{len(sample)} pairs from {crosswalk_file.name} -> {OUT}")
    print(sample["stratum"].value_counts().to_dict())


if __name__ == "__main__":
    main()
