"""The match step: exact links + Splink on silver -> clusters -> golden IDs -> crosswalk.

    uv run kept match                    # everything in the warehouse
    uv run kept match --sample-mod 10    # the 10% DOB-hash sample used to tune Splink

Reads silver.int_identity_evidence and silver.int_identity_records, writes parquet files
(identity_crosswalk, review_pairs, run_summary) and the Splink settings JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from kept.config import AUTO_LINK_THRESHOLD, STEWARD_REVIEW_THRESHOLD
from kept.contracts.enums import MatchReviewStatus, SourceSystem
from kept.contracts.identity import CandidatePair, SourceKey
from kept.data.identity.clustering import (
    Cluster,
    GoldenIdRegistry,
    cluster_review_reasons,
    connected_components,
)
from kept.data.identity.exact import exact_link_pairs
from kept.data.identity.probabilistic import build_settings, score_pairs

PAIR = ["left_system", "left_key", "right_system", "right_key"]


@dataclass(frozen=True)
class MatchRun:
    crosswalk: pd.DataFrame  # gold.identity_crosswalk columns
    review_pairs: pd.DataFrame  # Splink pairs in the steward band + pairs inside held clusters
    summary: dict[str, object]


def _key(system: str, key: str) -> SourceKey:
    return SourceKey(system=SourceSystem(system), key=key)


def _candidates(pairs: pd.DataFrame) -> list[CandidatePair]:
    return [
        CandidatePair(left=_key(a, b), right=_key(c, d), score=s, rule=r)
        for a, b, c, d, r, s in pairs[[*PAIR, "rule", "score"]].itertuples(index=False)
    ]


def run_matching(
    conn: duckdb.DuckDBPyConnection,
    *,
    sample_mod: int | None = None,
    train_sample_mod: int | None = None,
    previous: pd.DataFrame | None = None,
    at: datetime | None = None,
) -> MatchRun:
    """sample_mod=N keeps the records whose hash(dob) % N == 0, so both sides of a true match
    (same DOB) land in the sample together. `previous` is an earlier crosswalk: its golden IDs are kept."""
    at = at or datetime.now(UTC)
    sample = f"where dob is not null and hash(dob) % {int(sample_mod)} = 0" if sample_mod else ""
    records = conn.execute(f"select * from silver.int_identity_records {sample}").df()
    evidence = conn.execute("select * from silver.int_identity_evidence").df()
    if sample_mod:  # keep the evidence rows that belong to the sample (collections follow their CRM key)
        keep = set(zip(records.source_system, records.source_key, strict=True))
        crm = set(records.loc[records.source_system == "crm", "source_key"])
        in_sample = [
            (s, k) in keep or (s == "collections" and k in crm)
            for s, k in zip(evidence.source_system, evidence.source_key, strict=True)
        ]
        evidence = evidence[in_sample]
    all_keys = sorted(set(zip(evidence.source_system, evidence.source_key, strict=True)))

    exact = exact_link_pairs(evidence)
    in_keys = set(all_keys)
    exact = exact[
        [
            (a, b) in in_keys and (c, d) in in_keys
            for a, b, c, d in zip(
                exact.left_system, exact.left_key, exact.right_system, exact.right_key, strict=True
            )
        ]
    ]
    splink = score_pairs(records, exclude_pairs=exact, train_sample_mod=train_sample_mod)
    pairs = pd.concat([exact, splink], ignore_index=True)

    links = _candidates(pairs)
    clusters = connected_components([_key(s, k) for s, k in all_keys], links)
    national_ids = (
        records.dropna(subset=["national_id_hash"])
        .groupby(["source_system", "source_key"])["national_id_hash"]
        .agg(frozenset)
        .to_dict()
    )
    held: list[tuple[Cluster, tuple[str, ...]]] = []
    final: list[Cluster] = []
    for c in clusters:
        hashes = frozenset().union(*(national_ids.get((k.system.value, k.key), frozenset()) for k in c.keys))
        c = replace(c, national_id_hashes=hashes)
        if reasons := cluster_review_reasons(c):
            held.append((c, reasons))  # never auto-link: its keys stay apart until a steward looks
            final += [Cluster(keys=frozenset({k})) for k in c.keys]
        else:
            final.append(c)

    registry = GoldenIdRegistry()
    if previous is not None and len(previous):
        registry.seed(
            {
                _key(s, k): g
                for g, s, k in previous[["golden_customer_id", "source_system", "source_key"]].itertuples(
                    index=False
                )
            }
        )
    ids = registry.assign(final, actor_id="kept-match", at=at)

    # per key: the strongest link that put it in a cluster (exact beats Splink), else a singleton
    auto = pairs[(pairs.rule != "splink") | (pairs.score >= AUTO_LINK_THRESHOLD)]
    long = pd.concat(
        [
            auto.rename(columns={"left_system": "system", "left_key": "key"})[
                ["system", "key", "rule", "score"]
            ],
            auto.rename(columns={"right_system": "system", "right_key": "key"})[
                ["system", "key", "rule", "score"]
            ],
        ]
    )
    long["_exact"] = long["rule"].str.startswith("exact:")
    best = long.sort_values(["_exact", "score"], ascending=False).drop_duplicates(["system", "key"])
    link_of = {(sys, k): (rule, score, exact) for sys, k, rule, score, exact in best.itertuples(index=False)}
    held_keys = {k for c, _ in held for k in c.keys}
    rows = []
    for key, gid in ids.items():
        link = link_of.get((key.system.value, key.key))
        linked = link is not None and key not in held_keys
        rows.append(
            {
                "golden_customer_id": gid,
                "source_system": key.system.value,
                "source_key": key.key,
                "match_score": None if link is None or link[2] else float(link[1]),
                "match_rule": link[0] if link is not None and linked else "singleton",
                "match_review_status": (
                    MatchReviewStatus.AUTO if linked else MatchReviewStatus.UNLINKED
                ).value,
                "linked_at": at,
                "valid_to": pd.NaT,
            }
        )
    crosswalk = pd.DataFrame(rows).sort_values(["source_system", "source_key"]).reset_index(drop=True)

    steward = pairs[(pairs.rule == "splink") & (pairs.score < AUTO_LINK_THRESHOLD)].assign(
        reason=f"score_{STEWARD_REVIEW_THRESHOLD:.2f}_{AUTO_LINK_THRESHOLD:.2f}"
    )
    held_pairs = []
    for c, reasons in held:
        members = sorted((k.system.value, k.key) for k in c.keys)
        held_pairs += [
            {
                "left_system": s,
                "left_key": k,
                "right_system": members[0][0],
                "right_key": members[0][1],
                "rule": "held_cluster",
                "score": c.min_score,
                "reason": "+".join(reasons),
            }
            for s, k in members[1:]
        ]
    review = pd.concat([steward, pd.DataFrame(held_pairs)], ignore_index=True)

    sizes = crosswalk.groupby("golden_customer_id").size()
    summary: dict[str, object] = {
        "run_at": at.isoformat(),
        "sample_mod": sample_mod,
        "keys": len(crosswalk),
        "golden_ids": int(sizes.size),
        "multi_key_clusters": int((sizes > 1).sum()),
        "largest_cluster": int(sizes.max()),
        "exact_pairs": len(exact),
        "splink_pairs_auto": int((splink.score >= AUTO_LINK_THRESHOLD).sum()),
        "splink_pairs_review": int((splink.score < AUTO_LINK_THRESHOLD).sum()),
        "held_clusters": len(held),
        "held_reasons": pd.Series([r for _, rs in held for r in rs]).value_counts().to_dict(),
        "splink_settings": build_settings(),
    }
    return MatchRun(crosswalk=crosswalk, review_pairs=review, summary=summary)


def write_run(run: MatchRun, out_dir: Path, *, tag: str) -> list[Path]:
    """Parquet + JSON files whose names carry `tag` (code commit and settings), for the handover folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in (("identity_crosswalk", run.crosswalk), ("review_pairs", run.review_pairs)):
        path = out_dir / f"{name}_{tag}.parquet"
        frame.to_parquet(path, index=False)
        written.append(path)
    path = out_dir / f"run_summary_{tag}.json"
    path.write_text(json.dumps(run.summary, indent=2, default=str))
    return [*written, path]
