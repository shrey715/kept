"""Identity resolution: exact links, thresholds, cluster safety, permanent golden IDs."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.config import GOLDEN_ID_PATTERN
from kept.contracts import CandidatePair, MatchRoute, SourceKey, SourceSystem
from kept.data.identity.clustering import (
    Cluster,
    GoldenIdRegistry,
    cluster_review_reasons,
    connected_components,
    decide,
    route_score,
)
from kept.data.identity.exact import EXACT_RULES, exact_link_pairs
from kept.data.identity.steward import StewardQueue, StewardVerdict, precision

AT = datetime(2026, 10, 3, 2, 0, tzinfo=UTC)


def K(system: str, key: str) -> SourceKey:
    return SourceKey(system=SourceSystem(system), key=key)


# ----------------------------------------------------------------- exact links
def _row(system: str, key: str, **kw: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = {
        "source_system": system,
        "source_key": key,
        "crm_ref": None,
        "payment_source_account": None,
        "deposit_account_id": None,
        "national_id_hash": None,
        "duplicate_of_crm_id": None,
    }
    base.update(kw)
    return base


def _records() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # collections_cases.coll_customer_ref copied from CRM
            _row("collections", "RYM-1142", crm_ref="RYM-1142"),
            _row("crm", "RYM-1142", crm_ref="RYM-1142", national_id_hash="h1"),
            # card autopays from our deposit account D-9 (deposit key owns D-9 and D-10)
            _row("card", "CARD-1", payment_source_account="D-9"),
            _row("deposit", "DEP-1", deposit_account_id="D-9"),
            _row("deposit", "DEP-1", deposit_account_id="D-10"),
            # loan PADs from another FI: links nothing
            _row("loan", "LOAN-2", payment_source_account="OTHER-FI-77"),
            # duplicate CRM record with the same national ID (only customers carries national_id_hash)
            _row("crm", "RYM-3000", national_id_hash="h1"),
            # CRM's own duplicate pointer
            _row("crm", "RYM-2001", duplicate_of_crm_id="RYM-1142"),
            # nulls everywhere: must not link to anything
            _row("loan", "LOAN-1"),
            _row("bureau", "B-1"),
        ]
    )


def test_exact_links_found() -> None:
    out = exact_link_pairs(_records())
    pairs = {
        frozenset({(r.left_system, r.left_key), (r.right_system, r.right_key)}): r.rule
        for r in out.itertuples()
    }
    assert pairs[frozenset({("collections", "RYM-1142"), ("crm", "RYM-1142")})] == "exact:case_crm_ref"
    assert pairs[frozenset({("card", "CARD-1"), ("deposit", "DEP-1")})] == "exact:payment_source_account"
    assert pairs[frozenset({("crm", "RYM-1142"), ("crm", "RYM-3000")})] == "exact:national_id_hash"
    assert pairs[frozenset({("crm", "RYM-2001"), ("crm", "RYM-1142")})] == "exact:crm_duplicate_pointer"


def test_exact_links_shape_and_invariants() -> None:
    out = exact_link_pairs(_records())
    assert list(out.columns) == ["left_system", "left_key", "right_system", "right_key", "rule", "score"]
    assert set(out["rule"]) <= set(EXACT_RULES)
    assert (out["score"] == 1.0).all()
    left = list(zip(out.left_system, out.left_key, strict=True))
    right = list(zip(out.right_system, out.right_key, strict=True))
    assert all(lt < rt for lt, rt in zip(left, right, strict=True))  # ordered, no self pairs
    assert len(set(zip(left, right, strict=True))) == len(out)  # no duplicates


def test_nulls_never_match_nulls() -> None:
    out = exact_link_pairs(_records())
    keys = set(out.left_key) | set(out.right_key)
    assert "LOAN-1" not in keys and "B-1" not in keys
    assert "LOAN-2" not in keys  # payment account at another FI


# ----------------------------------------------------------------- thresholds
@pytest.mark.parametrize(
    "score,route",
    [
        (1.0, MatchRoute.AUTO_LINK),
        (0.95, MatchRoute.AUTO_LINK),
        (0.9499999, MatchRoute.STEWARD_REVIEW),
        (0.80, MatchRoute.STEWARD_REVIEW),
        (0.7999999, MatchRoute.PROVISIONAL),
        (0.0, MatchRoute.PROVISIONAL),
    ],
)
def test_route_score_boundaries(score: float, route: MatchRoute) -> None:
    assert route_score(score) is route


@pytest.mark.parametrize("score", [-0.01, 1.01, float("nan")])
def test_route_score_rejects_out_of_range(score: float) -> None:
    with pytest.raises(ValueError):
        route_score(score)


@given(st.floats(min_value=0, max_value=1), st.floats(min_value=0, max_value=1))
def test_route_is_monotone_in_score(a: float, b: float) -> None:
    rank = {MatchRoute.PROVISIONAL: 0, MatchRoute.STEWARD_REVIEW: 1, MatchRoute.AUTO_LINK: 2}
    lo, hi = sorted((a, b))
    assert rank[route_score(lo)] <= rank[route_score(hi)]


def test_exact_rules_always_auto_link() -> None:
    pair = CandidatePair(
        left=K("card", "1"), right=K("deposit", "2"), score=1.0, rule="exact:payment_source_account"
    )
    assert decide(pair).route is MatchRoute.AUTO_LINK


def test_decide_uses_thresholds_for_splink() -> None:
    pair = CandidatePair(left=K("crm", "1"), right=K("loan", "2"), score=0.9, rule="splink")
    d = decide(pair)
    assert d.route is MatchRoute.STEWARD_REVIEW and d.pair == pair


# ----------------------------------------------------------------- cluster safety
def test_two_national_ids_go_to_review() -> None:
    c = Cluster(keys=frozenset({K("crm", "1"), K("loan", "2")}), national_id_hashes=frozenset({"h1", "h2"}))
    assert "two_national_ids" in cluster_review_reasons(c)


def test_more_than_twelve_keys_go_to_review() -> None:
    twelve = Cluster(keys=frozenset(K("card", str(i)) for i in range(12)))
    thirteen = Cluster(keys=frozenset(K("card", str(i)) for i in range(13)))
    assert cluster_review_reasons(twelve) == ()
    assert cluster_review_reasons(thirteen) == ("too_many_keys",)


def test_safe_cluster_has_no_reasons() -> None:
    c = Cluster(keys=frozenset({K("crm", "1"), K("loan", "2")}), national_id_hashes=frozenset({"h1"}))
    assert cluster_review_reasons(c) == ()


def test_connected_components_partition_keys() -> None:
    keys = [K("crm", "1"), K("card", "1"), K("deposit", "1"), K("loan", "9")]
    links = [
        CandidatePair(left=keys[0], right=keys[1], score=0.99, rule="splink"),
        CandidatePair(left=keys[1], right=keys[2], score=1.0, rule="exact:payment_source_account"),
        CandidatePair(left=keys[0], right=keys[3], score=0.85, rule="splink"),  # not auto: no link
    ]
    clusters = connected_components(keys, links)
    seen = [k for c in clusters for k in c.keys]
    assert sorted(seen, key=str) == sorted(keys, key=str)  # every key exactly once
    sizes = sorted(len(c.keys) for c in clusters)
    assert sizes == [1, 3]


def test_connected_components_min_score_is_weakest_link() -> None:
    a, b, c = K("crm", "1"), K("card", "1"), K("loan", "1")
    clusters = connected_components(
        [a, b, c],
        [
            CandidatePair(left=a, right=b, score=0.99, rule="splink"),
            CandidatePair(left=b, right=c, score=0.96, rule="splink"),
        ],
    )
    assert len(clusters) == 1 and clusters[0].min_score == pytest.approx(0.96)


# ----------------------------------------------------------------- golden IDs
def _c(*keys: SourceKey) -> Cluster:
    return Cluster(keys=frozenset(keys))


def test_golden_ids_match_pattern_and_are_unique() -> None:
    reg = GoldenIdRegistry()
    m = reg.assign([_c(K("crm", "1")), _c(K("crm", "2")), _c(K("crm", "3"))], actor_id="system", at=AT)
    assert all(re.fullmatch(GOLDEN_ID_PATTERN, g) for g in m.values())
    assert len(set(m.values())) == 3


def test_golden_ids_are_stable_across_reruns() -> None:
    reg = GoldenIdRegistry()
    clusters = [_c(K("crm", "1"), K("card", "1")), _c(K("crm", "2"))]
    first = reg.assign(clusters, actor_id="system", at=AT)
    second = reg.assign(list(reversed(clusters)), actor_id="system", at=AT)
    assert first == second
    assert reg.events() == [] or all(e.kind != "merge" for e in reg.events())


def test_merge_keeps_oldest_id_and_logs() -> None:
    reg = GoldenIdRegistry()
    m1 = reg.assign([_c(K("crm", "1")), _c(K("card", "1"))], actor_id="system", at=AT)
    old = sorted(m1.values())
    m2 = reg.assign([_c(K("crm", "1"), K("card", "1"))], actor_id="system", at=AT)
    assert set(m2.values()) == {old[0]}
    merges = [e for e in reg.events() if e.kind == "merge"]
    assert len(merges) == 1 and set(merges[0].golden_ids_before) == set(old)


def test_split_keeps_id_on_largest_part_and_never_reuses_ids() -> None:
    reg = GoldenIdRegistry()
    big = [K("crm", "1"), K("card", "1"), K("loan", "1")]
    gid = reg.assign([_c(*big)], actor_id="system", at=AT)[big[0]]
    m = reg.assign([_c(big[0], big[1]), _c(big[2])], actor_id="system", at=AT)
    assert m[big[0]] == m[big[1]] == gid
    assert m[big[2]] != gid
    assert any(e.kind == "split" for e in reg.events())
    # a retired ID never comes back for someone else
    reg.assign([_c(K("crm", "99"))], actor_id="system", at=AT)
    all_ids = [g for g in (reg.golden_id(k) for k in [*big, K("crm", "99")]) if g]
    assert len(all_ids) == len(set(all_ids)) + 1  # only big[0], big[1] share


def test_undo_restores_previous_mapping() -> None:
    reg = GoldenIdRegistry()
    a, b = K("crm", "1"), K("card", "1")
    before = reg.assign([_c(a), _c(b)], actor_id="system", at=AT)
    reg.assign([_c(a, b)], actor_id="system", at=AT)
    merge = next(e for e in reg.events() if e.kind == "merge")
    undo = reg.undo(merge.event_id, actor_id="steward-1", reason="different people", at=AT)
    assert undo.kind == "undo" and undo.undoes_event_id == merge.event_id
    assert {k: reg.golden_id(k) for k in (a, b)} == before


def test_undo_unknown_event_raises() -> None:
    reg = GoldenIdRegistry()
    with pytest.raises(KeyError):
        reg.undo("nope", actor_id="s", reason="r", at=AT)


# ----------------------------------------------------------------- steward
def _decision(score: float = 0.9):
    return decide(CandidatePair(left=K("crm", "1"), right=K("loan", "2"), score=score, rule="splink"))


def test_steward_queue_is_idempotent_per_pair_and_oldest_first() -> None:
    q = StewardQueue()
    i1 = q.enqueue(_decision(), reasons=("score_0.80_0.95",), at=AT)
    i2 = q.enqueue(_decision(), reasons=("score_0.80_0.95",), at=AT)
    assert i1.item_id == i2.item_id
    assert [i.item_id for i in q.pending()] == [i1.item_id]


def test_steward_resolve_rules() -> None:
    q = StewardQueue()
    item = q.enqueue(_decision(), reasons=(), at=AT)
    q.resolve(item.item_id, StewardVerdict.UNSURE, steward_id="s1", at=AT)
    assert [i.item_id for i in q.pending()] == [item.item_id]
    q.resolve(item.item_id, StewardVerdict.SAME_PERSON, steward_id="s1", at=AT)
    assert q.pending() == []
    with pytest.raises(ValueError):
        q.resolve(item.item_id, StewardVerdict.DIFFERENT_PEOPLE, steward_id="s1", at=AT)
    with pytest.raises(KeyError):
        q.resolve("missing", StewardVerdict.SAME_PERSON, steward_id="s1", at=AT)


def test_precision() -> None:
    assert precision([True, True, True, False], [True, True, False, True]) == pytest.approx(2 / 3)
    with pytest.raises(ValueError):
        precision([True], [True, False])
    with pytest.raises(ValueError):
        precision([False, False], [True, True])
