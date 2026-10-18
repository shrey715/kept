"""#79: the promise model reads no protected attribute or proxy, and only explains a promise."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from kept.contracts.data_contract import load_data_contract
from kept.nba.promise_model import FEATURES, SOURCE_COLUMNS, PromiseModel, serving_row, train

pytestmark = pytest.mark.track_d


def test_no_protected_attribute_or_proxy() -> None:
    """The brief: no protected attributes in decisions. The contract lists 12 protected and 32 proxies."""
    c = load_data_contract()
    banned = c.protected_attributes | c.proxy_attributes
    columns = {s.split(".")[-1] for s in SOURCE_COLUMNS}
    assert not columns & banned and not set(FEATURES) & banned


def test_trains_on_a_time_split_and_scores_a_serving_row() -> None:
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(0)
    n = 4_000
    rows = pd.DataFrame(
        {
            "created": pd.date_range("2025-06-01", periods=n, freq="2h"),
            "days_to_due": rng.integers(1, 30, n),
            "dpd": rng.integers(1, 90, n),
            "prior_broken_90d": rng.integers(0, 3, n),
            "prior_kept_ratio": rng.choice([np.nan, 0.2, 0.8], n),
            "days_after_pay": rng.integers(0, 14, n),
            "days_before_next_pay": rng.integers(1, 14, n),
        }
    )
    rows["kept"] = (rng.uniform(0, 1, n) < 0.8 - 0.4 * (rows.days_after_pay > 7)).astype(int)
    model, m = train(rows, cutoff=rows.created.iloc[3_000].to_pydatetime())
    assert (m["rows_train"], m["rows_test"]) == (3_000, 1_000) and m["auc"] > 0.6
    row = serving_row(
        due=date(2026, 10, 10),
        today=date(2026, 10, 4),
        payday=date(2026, 10, 9),
        frequency="biweekly",
        dpd=12,
        prior_broken_90d=None,
        prior_kept_ratio=None,
    )
    assert row["days_after_pay"] == 1 and row["days_before_next_pay"] == 13
    (p,) = model.p_kept([row])
    assert 0 < p < 1


class _Fixed(PromiseModel):
    def __init__(self) -> None:
        pass

    def p_kept(self, rows):  # type: ignore[no-untyped-def,override]
        return np.array([0.61 if r["days_after_pay"] == 1 else 0.49 for r in rows])


def test_card_states_the_chance_and_ranking_is_unchanged(make_ctx) -> None:  # type: ignore[no-untyped-def]
    from kept.contracts import FeatureVector
    from kept.nba.engine import KeptEngine
    from tests.fakes import ConstantScorer, FixedContextBuilder, InMemoryAuditLog, StaticFeatureProvider
    from tests.nba.test_engine import NOW, PROBS

    def card(model):  # type: ignore[no-untyped-def]
        ctx = make_ctx()
        fv = FeatureVector(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            as_of=ctx.features_as_of,
            feature_set_version="fs-0",
        )
        eng = KeptEngine(
            context=FixedContextBuilder({ctx.case_id: ctx}),
            features=StaticFeatureProvider({ctx.case_id: fv}),
            scorer=ConstantScorer(PROBS),
            audit_log=InMemoryAuditLog(),
            promise_model=model,
        )
        return eng.recommend(ctx.case_id, NOW)

    plain, explained = card(None), card(_Fixed())
    assert plain.proposal is not None and explained.proposal is not None
    assert plain.proposal.action is explained.proposal.action  # the model never changes the choice

    from decimal import Decimal

    from kept.contracts.nba import PromiseSizing

    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    sizing = PromiseSizing(
        amount=Decimal("120.00"),
        due_date=date(2026, 10, 10),
        installments=1,
        spare_cash_estimate=Decimal("150.00"),
        payday=date(2026, 10, 9),
        rationale="$120 after payday.",
    )
    eng = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=InMemoryAuditLog(),
        promise_model=_Fixed(),
    )
    text = eng._sizing_text(ctx, fv, sizing)
    assert text == (
        "$120 after payday. If they agree, the model gives this promise a 61% chance of being kept "
        "(49% if it fell due the day before payday)."
    )
    no_model = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=InMemoryAuditLog(),
    )
    assert no_model._sizing_text(ctx, fv, sizing) == "$120 after payday."


def test_no_comparison_when_the_date_makes_no_difference(make_ctx) -> None:  # type: ignore[no-untyped-def]
    from decimal import Decimal

    from kept.contracts import FeatureVector
    from kept.contracts.nba import PromiseSizing
    from kept.nba.engine import KeptEngine
    from tests.fakes import ConstantScorer, FixedContextBuilder, InMemoryAuditLog, StaticFeatureProvider
    from tests.nba.test_engine import PROBS

    class Flat(_Fixed):
        def p_kept(self, rows):  # type: ignore[no-untyped-def,override]
            return np.array([0.181, 0.183])

    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    sizing = PromiseSizing(
        amount=Decimal("120.00"),
        due_date=date(2026, 10, 10),
        installments=1,
        spare_cash_estimate=Decimal("150.00"),
        payday=date(2026, 10, 9),
        rationale="$120 after payday.",
    )
    eng = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=InMemoryAuditLog(),
        promise_model=Flat(),
    )
    assert eng._sizing_text(ctx, fv, sizing) == (
        "$120 after payday. If they agree, the model gives this promise a 18% chance of being kept."
    )


def test_calibration_follows_a_level_shift_in_the_kept_rate() -> None:
    """The kept rate falls (70% -> 35%) while the ranking stays: calibrated on the last 14 days, the model's mean
    prediction on what follows is close to the new rate; the old 60-day isotonic window is still far above it."""
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(1)
    n = 20_000
    created = pd.date_range("2025-01-01", periods=n, freq="1h")
    rows = pd.DataFrame(
        {
            "created": created,
            "days_to_due": rng.integers(1, 30, n),
            "dpd": rng.integers(1, 90, n),
            "prior_broken_90d": rng.integers(0, 3, n),
            "prior_kept_ratio": rng.choice([np.nan, 0.2, 0.8], n),
            "days_after_pay": rng.integers(0, 14, n),
            "days_before_next_pay": rng.integers(1, 14, n),
        }
    )
    rate = np.interp(np.arange(n), [0, 15_000, 16_000, n], [0.7, 0.7, 0.35, 0.35])  # a fall, then flat
    rows["kept"] = (rng.uniform(0, 1, n) < rate * (1.2 - 0.4 * (rows.days_after_pay > 7))).astype(int)
    cutoff = created[16_100].to_pydatetime()
    _, new = train(rows, cutoff=cutoff)
    _, old = train(rows, cutoff=cutoff, calibrate_days=60, method="isotonic")
    assert abs(new["calibration_mean_gap"]) < 0.03 < old["calibration_mean_gap"]
    assert abs(new["calibration_mean_gap"]) < abs(old["calibration_mean_gap"])
