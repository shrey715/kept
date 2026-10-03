"""The match step: exact links + Splink on silver -> clusters -> golden IDs -> crosswalk.

    uv run kept match                    # everything in the warehouse
    uv run kept match --sample-mod 10    # the 10% DOB-hash sample used to tune Splink

Reads silver.int_identity_evidence and silver.int_identity_records, writes parquet files
(identity_crosswalk, review_pairs, run_summary) and the Splink settings JSON.

At 3.5M records the clustering runs on integer arrays: building a pydantic CandidatePair and
SourceKey for each of ~5M pairs needed more than 16 GB. connected_components and GoldenIdRegistry
(kept.data.identity.clustering) are the tested reference for the same rules; the registry is used
here when a previous crosswalk must keep its golden IDs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from kept.config import AUTO_LINK_THRESHOLD, MAX_KEYS_PER_CLUSTER, STEWARD_REVIEW_THRESHOLD
from kept.contracts.enums import MatchReviewStatus
from kept.data.identity.exact import exact_link_pairs
from kept.data.identity.probabilistic import build_settings, score_pairs, train_model
from kept.data.identity.steward import read_verdicts

PAIR = ["left_system", "left_key", "right_system", "right_key"]
GOLDEN_ID_FORMAT = "G-{:06d}"


@dataclass(frozen=True)
class MatchRun:
    crosswalk: pd.DataFrame  # gold.identity_crosswalk columns
    review_pairs: pd.DataFrame  # Splink pairs in the steward band + pairs inside held clusters
    summary: dict[str, object]
    model: dict[str, object]  # the trained Splink model, saved next to the crosswalk


def _roots(n: int, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Union-find over n nodes: the root node of each node's connected component."""
    parent = np.arange(n)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving
            x = parent[x]
        return int(x)

    for a, b in zip(left.tolist(), right.tolist(), strict=True):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)  # the smaller key index stays the root
    return np.array([find(x) for x in range(n)])


def _assign_stable(
    keys: pd.MultiIndex, group: np.ndarray, previous: pd.DataFrame
) -> tuple[np.ndarray, int, int]:
    """Golden ID numbers that keep the IDs of `previous`, the rules of GoldenIdRegistry on arrays
    (tests/data/test_stable_ids.py checks the two agree): a cluster keeps the lowest ID among the old IDs
    that have their largest part in it (a merge keeps the oldest), an old ID whose keys are now apart stays
    with its largest part (a split gives the rest new IDs), and an ID is never reused: new IDs count up from
    the highest ever issued. Returns (number per key, merges, splits)."""
    n = len(keys)
    old = np.zeros(n, dtype=np.int64)  # the previous golden number of each key; 0 = a key we had not seen
    where = keys.get_indexer(pd.MultiIndex.from_frame(previous[["source_system", "source_key"]]))
    seen = where >= 0
    numbers = previous["golden_customer_id"].str.removeprefix("G-").astype(np.int64).to_numpy()
    old[where[seen]] = numbers[seen]

    held = pd.DataFrame({"old": old[old > 0], "group": group[old > 0]})
    parts = held.groupby(["old", "group"]).size().rename("keys").reset_index()
    # an old ID's home: the group holding most of its keys (ties: the group of the smallest key)
    home = parts.sort_values(["keys", "group"], ascending=[False, True]).drop_duplicates("old")
    survivor = home.groupby("group")["old"].min()  # the oldest of the IDs homed in a group keeps it
    merges = int((home.groupby("group").size() > 1).sum())
    splits = int((parts.groupby("old").size() > 1).sum())

    groups = np.unique(group)
    fresh = groups[~np.isin(groups, survivor.index.to_numpy())]  # in order of each group's smallest key
    first_new = (int(numbers.max()) if len(numbers) else 0) + 1
    number_of_group = pd.Series(
        np.concatenate([survivor.to_numpy(), np.arange(first_new, first_new + len(fresh))]),
        index=np.concatenate([survivor.index.to_numpy(), fresh]),
    )
    return number_of_group.reindex(group).to_numpy(), merges, splits


def run_matching(
    conn: duckdb.DuckDBPyConnection,
    *,
    sample_mod: int | None = None,
    train_sample_mod: int | None = None,
    previous: pd.DataFrame | None = None,
    verdicts: pd.DataFrame | None = None,
    at: datetime | None = None,
) -> MatchRun:
    """sample_mod=N keeps the records whose hash(dob) % N == 0, so both sides of a true match
    (same DOB) land in the sample together. `previous` is an earlier crosswalk: its golden IDs are kept.
    `verdicts` are the stewards' resolved items (default: steward.verdicts in the warehouse): "same_person"
    links the pair (match_review_status steward_approved) and releases a member of a held cluster;
    "different_people" cuts the direct link, and holds the cluster if the two are still joined."""
    at = at or datetime.now(UTC)
    sample = f"where dob is not null and hash(dob) % {int(sample_mod)} = 0" if sample_mod else ""
    records = conn.execute(f"select * from silver.int_identity_records {sample}").df()
    evidence = conn.execute("select * from silver.int_identity_evidence").df()
    if sample_mod:  # keep the evidence rows that belong to the sample (collections follow their CRM key)
        have = pd.MultiIndex.from_frame(records[["source_system", "source_key"]])
        crm = set(records.loc[records.source_system == "crm", "source_key"])
        in_sample = have.get_indexer(pd.MultiIndex.from_frame(evidence[["source_system", "source_key"]])) >= 0
        in_sample |= (evidence.source_system == "collections") & evidence.source_key.isin(crm)
        evidence = evidence[in_sample]
    keys = pd.MultiIndex.from_frame(evidence[["source_system", "source_key"]].drop_duplicates()).sort_values()
    n = len(keys)

    def positions(frame: pd.DataFrame, system: str, key: str) -> np.ndarray:
        return keys.get_indexer(pd.MultiIndex.from_frame(frame[[system, key]]))

    exact = exact_link_pairs(evidence)
    del evidence  # millions of rows of strings; only the pairs are needed from here
    exact = exact[
        (positions(exact, "left_system", "left_key") >= 0)
        & (positions(exact, "right_system", "right_key") >= 0)
    ]

    hashed = records.dropna(subset=["national_id_hash"])[["source_system", "source_key", "national_id_hash"]]
    model = train_model(records, sample_mod=train_sample_mod)
    splink = score_pairs(records, exclude_pairs=exact, model=model)
    del records
    pairs = pd.concat([exact, splink], ignore_index=True)
    li, ri = positions(pairs, "left_system", "left_key"), positions(pairs, "right_system", "right_key")
    is_exact = pairs["rule"].str.startswith("exact:").to_numpy()
    rules = pairs["rule"].to_numpy(dtype=object)
    score = pairs["score"].to_numpy()
    auto = is_exact | (score >= AUTO_LINK_THRESHOLD)

    # the stewards' verdicts: a same-person pair is one more link, a different-people pair is cut
    verdicts = read_verdicts(conn) if verdicts is None else verdicts
    approved: set[tuple[int, int]] = set()
    cannot: set[tuple[int, int]] = set()
    if len(verdicts):
        vl, vr = (
            positions(verdicts, "left_system", "left_key"),
            positions(verdicts, "right_system", "right_key"),
        )
        known = (vl >= 0) & (vr >= 0)
        lo, hi = np.minimum(vl, vr), np.maximum(vl, vr)
        for verdict, target in (("same_person", approved), ("different_people", cannot)):
            pick = known & (verdicts["verdict"] == verdict).to_numpy()
            target.update(zip(lo[pick].tolist(), hi[pick].tolist(), strict=True))
    if cannot:
        edge = pd.MultiIndex.from_arrays([np.minimum(li, ri), np.maximum(li, ri)])
        auto &= ~edge.isin(list(cannot))
    if approved:
        a_left, a_right = (np.array(side) for side in zip(*sorted(approved), strict=True))
        li, ri = np.concatenate([li, a_left]), np.concatenate([ri, a_right])
        is_exact = np.concatenate([is_exact, np.zeros(len(a_left), dtype=bool)])
        score = np.concatenate([score, np.ones(len(a_left))])
        rules = np.concatenate([rules, np.full(len(a_left), "steward:same_person", dtype=object)])
        auto = np.concatenate([auto, np.ones(len(a_left), dtype=bool)])

    # clusters, and the ones that must not be auto-linked
    root = _roots(n, li[auto], ri[auto])
    size = np.bincount(root, minlength=n)
    nid_root = root[positions(hashed, "source_system", "source_key")]
    distinct_ids = pd.Series(hashed["national_id_hash"].to_numpy()).groupby(nid_root).nunique()
    two_ids = np.zeros(n, dtype=bool)
    two_ids[distinct_ids[distinct_ids > 1].index.to_numpy()] = True
    too_big = size > MAX_KEYS_PER_CLUSTER
    still_joined = np.zeros(
        n, dtype=bool
    )  # a steward said "different people" but other links keep them together
    still_joined[[root[a] for a, b in cannot if root[a] == root[b]]] = True
    held_root = two_ids | too_big | still_joined
    held = held_root[root]  # never auto-link: these keys stay apart until a steward looks
    # a "same person" verdict inside a held cluster brings that member back to the anchor, unless the
    # cluster holds two national IDs: Q3 forbids that whatever a steward says
    released = np.zeros(n, dtype=bool)
    for a, b in approved:
        if held[a] and root[a] == root[b] and not two_ids[root[a]]:
            released[[a, b]] = True
    group = np.where(held & ~released, np.arange(n), root)

    if previous is not None and len(previous):
        number, id_merges, id_splits = _assign_stable(keys, group, previous)
    else:  # a first run: IDs in order of each cluster's smallest key, as GoldenIdRegistry would issue them
        number, id_merges, id_splits = pd.factorize(group)[0] + 1, 0, 0
    golden = pd.Series(number).map(GOLDEN_ID_FORMAT.format).to_numpy()

    # per key: the strongest link that put it in a cluster (exact beats Splink), else a singleton
    ends = pd.DataFrame(
        {
            "pos": np.concatenate([li[auto], ri[auto]]),
            "exact": np.tile(is_exact[auto], 2),
            "score": np.tile(score[auto], 2),
            "rule": np.tile(rules[auto], 2),
        }
    )
    best = ends.sort_values(["exact", "score"], ascending=False).drop_duplicates("pos").set_index("pos")
    linked = np.zeros(n, dtype=bool)
    linked[best.index.to_numpy()] = True
    linked = (linked & ~held) | released
    rule = np.full(n, "singleton", dtype=object)
    match_score = np.full(n, np.nan)
    rule[best.index.to_numpy()] = best["rule"].to_numpy()
    match_score[best.index.to_numpy()] = np.where(best["exact"], np.nan, best["score"])
    rule[released] = "steward:same_person"
    rule[~linked] = "singleton"
    match_score[~linked] = np.nan
    steward_approved = linked & pd.Series(rule).str.startswith("steward:").to_numpy()
    crosswalk = pd.DataFrame(
        {
            "golden_customer_id": golden,
            "source_system": keys.get_level_values(0),
            "source_key": keys.get_level_values(1),
            "match_score": match_score,
            "match_rule": rule,
            "match_review_status": np.where(
                steward_approved,
                MatchReviewStatus.STEWARD_APPROVED.value,
                np.where(linked, MatchReviewStatus.AUTO.value, MatchReviewStatus.UNLINKED.value),
            ),
            "linked_at": at,
            "valid_to": pd.NaT,
        }
    )

    steward = pairs[(pairs.rule == "splink") & (pairs.score < AUTO_LINK_THRESHOLD)].assign(
        reason=f"score_{STEWARD_REVIEW_THRESHOLD:.2f}_{AUTO_LINK_THRESHOLD:.2f}"
    )
    weakest = pd.Series(score[auto]).groupby(root[li[auto]]).min()  # per cluster root: its weakest link
    held_rows = pd.DataFrame({"pos": np.flatnonzero(held & ~released)})
    held_rows["root"] = root[held_rows["pos"]]
    held_rows = held_rows[held_rows["pos"] != held_rows["root"]]  # the root key is the anchor
    reasons = np.where(two_ids, "two_national_ids", np.where(too_big, "too_many_keys", "steward_cannot_link"))
    held_pairs = pd.DataFrame(
        {
            "left_system": keys.get_level_values(0)[held_rows["pos"]],
            "left_key": keys.get_level_values(1)[held_rows["pos"]],
            "right_system": keys.get_level_values(0)[held_rows["root"]],
            "right_key": keys.get_level_values(1)[held_rows["root"]],
            "rule": "held_cluster",
            "score": weakest.reindex(held_rows["root"]).to_numpy(),
            "reason": reasons[held_rows["root"]],
        }
    )
    review = pd.concat([steward, held_pairs], ignore_index=True)

    sizes = crosswalk.groupby("golden_customer_id").size()
    summary: dict[str, object] = {
        "run_at": at.isoformat(),
        "sample_mod": sample_mod,
        "keys": n,
        "golden_ids": int(sizes.size),
        "multi_key_clusters": int((sizes > 1).sum()),
        "largest_cluster": int(sizes.max()),
        "exact_pairs": len(exact),
        "ids_merged": id_merges,
        "ids_split": id_splits,
        "steward_links": len(approved),
        "steward_cuts": len(cannot),
        "splink_pairs_auto": int((splink.score >= AUTO_LINK_THRESHOLD).sum()),
        "splink_pairs_review": int((splink.score < AUTO_LINK_THRESHOLD).sum()),
        "held_clusters": int(held_root[np.unique(root[held])].sum()) if held.any() else 0,
        "held_reasons": {
            "two_national_ids": int(two_ids[np.unique(root[held])].sum()) if held.any() else 0,
            "too_many_keys": int(too_big[np.unique(root[held])].sum()) if held.any() else 0,
            "steward_cannot_link": int(still_joined[np.unique(root[held])].sum()) if held.any() else 0,
        },
        "splink_settings": build_settings(),
    }
    return MatchRun(crosswalk=crosswalk, review_pairs=review, summary=summary, model=model)


def write_run(run: MatchRun, out_dir: Path, *, tag: str) -> list[Path]:
    """Parquet + JSON files whose names carry `tag` (code commit and settings), for the handover folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in (("identity_crosswalk", run.crosswalk), ("review_pairs", run.review_pairs)):
        path = out_dir / f"{name}_{tag}.parquet"
        frame.to_parquet(path, index=False)
        written.append(path)
    model_path = out_dir / f"splink_model_{tag}.json"
    model_path.write_text(json.dumps(run.model, indent=2, default=str))
    written.append(model_path)
    path = out_dir / f"run_summary_{tag}.json"
    path.write_text(json.dumps(run.summary, indent=2, default=str))
    return [*written, path]


def latest_crosswalk(directory: Path) -> Path:
    """The newest crosswalk parquet in `directory`; a full run beats a sample run."""
    found = sorted(directory.glob("identity_crosswalk_*.parquet"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise FileNotFoundError(f"no identity_crosswalk_*.parquet in {directory}: run `kept match` first")
    full = [p for p in found if "-full" in p.stem]  # also "-full-train5" (kept match --train-sample-mod 5)
    return (full or found)[-1]


def load_crosswalk(conn: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Put a crosswalk parquet into silver.int_crosswalk, where the gold models read it."""
    conn.execute("create schema if not exists silver")
    conn.execute(
        "create or replace table silver.int_crosswalk as select * from read_parquet(?)", [str(parquet)]
    )
    row = conn.execute("select count(*) from silver.int_crosswalk").fetchone()
    assert row is not None
    return int(row[0])
