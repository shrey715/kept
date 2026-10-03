"""Feast provider: export -> apply -> materialise -> online and point-in-time reads."""

from __future__ import annotations

import importlib.util
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from kept.contracts import HardshipSignal, PayrollFrequency
from kept.contracts.feature_registry import FEATURES, OUTCOME_DENY_LIST
from kept.contracts.features import FeatureVector

pytestmark = [pytest.mark.integration, pytest.mark.track_d]

REPO = Path(__file__).resolve().parents[2] / "feature_repo"
T1, T2 = datetime(2026, 9, 21, 6), datetime(2026, 9, 28, 6)  # naive UTC, as dbt writes them
SQLTYPE = {
    "int": "integer",
    "float": "double",
    "decimal": "decimal(14, 2)",
    "category": "varchar",
    "bool": "boolean",
    "date": "date",
}


@pytest.fixture(scope="module")
def provider(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    pytest.importorskip("feast")
    from kept.features.store import FeastFeatureProvider, export_features

    tmp = tmp_path_factory.mktemp("feast")
    cols = ", ".join(f"{f.name} {SQLTYPE[f.dtype]}" for f in FEATURES)
    with duckdb.connect() as c:
        c.execute("create schema features")
        c.execute(
            f"create table features.case_features (case_id varchar, golden_customer_id varchar, as_of timestamp, feature_set_version varchar, {cols})"
        )
        c.execute(
            """insert into features.case_features (case_id, golden_customer_id, as_of, feature_set_version,
                       contacts_last_7d, kept_promise_ratio, pay_frequency, promised_date, balance_at_risk, hardship_signal, dispute_flag)
                     values ('C-1', 'G-000001', ?, 'fs-0.1', 1, 0.5, 'monthly', null, 420.00, 'none', false),
                            ('C-1', 'G-000001', ?, 'fs-0.1', 2, 0.25, 'monthly', date '2026-10-02', 380.50, 'possible', null),
                            ('C-2', 'G-000002', ?, 'fs-0.1', 0, null, null, null, null, null, null)""",
            [T1, T2, T1],
        )
        parquet = tmp / "case_features.parquet"
        assert export_features(c, parquet) == 3

    repo = tmp / "repo"
    shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns("*.db", "data", "__pycache__"))
    mp = pytest.MonkeyPatch()
    mp.setenv("KEPT_FEATURES_PARQUET", str(parquet))
    spec = importlib.util.spec_from_file_location("kept_feature_repo", repo / "features.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    from feast import FeatureStore

    store = FeatureStore(repo_path=str(repo))
    store.apply([mod.case, mod.case_features])
    store.materialize(
        start_date=T1.replace(tzinfo=UTC) - timedelta(days=1),
        end_date=T2.replace(tzinfo=UTC) + timedelta(hours=1),
    )
    yield FeastFeatureProvider(repo)
    mp.undo()


def test_online_returns_latest_vector(provider) -> None:  # type: ignore[no-untyped-def]
    fv = provider.get_online("C-1")
    assert isinstance(fv, FeatureVector)
    assert fv.as_of == T2.replace(tzinfo=UTC) and fv.golden_customer_id == "G-000001"
    assert fv.contacts_last_7d == 2 and fv.kept_promise_ratio == 0.25
    assert fv.pay_frequency is PayrollFrequency.MONTHLY and fv.hardship_signal is HardshipSignal.POSSIBLE
    assert fv.promised_date and str(fv.promised_date) == "2026-10-02"
    assert fv.balance_at_risk == Decimal("380.50") and fv.dispute_flag is None


def test_online_missing_stays_missing(provider) -> None:  # type: ignore[no-untyped-def]
    fv = provider.get_online("C-2")
    assert fv.kept_promise_ratio is None and fv.pay_frequency is None and fv.contacts_last_7d == 0


def test_online_unknown_case(provider) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(KeyError):
        provider.get_online("C-404")


def test_historical_is_point_in_time_and_keeps_order(provider) -> None:  # type: ignore[no-untyped-def]
    rows = pd.DataFrame(
        {
            "case_id": ["C-1", "C-2", "C-1", "C-1"],
            "as_of": [
                T2 + timedelta(hours=1),
                T1 + timedelta(days=1),
                T1 + timedelta(days=3),
                T1 - timedelta(days=1),
            ],
        },
        index=[10, 11, 12, 13],
    ).assign(as_of=lambda d: d.as_of.dt.tz_localize("UTC"))
    out = provider.get_historical(rows)
    assert list(out.index) == [10, 11, 12, 13] and list(out.case_id) == ["C-1", "C-2", "C-1", "C-1"]
    assert list(out.contacts_last_7d.iloc[:3]) == [2, 0, 1]  # row 12 is between T1 and T2: sees T1
    assert pd.isna(out.contacts_last_7d.iloc[3])  # before any feature row: missing, never the future
    assert set(FeatureVector.feature_names()) <= set(out.columns)
    assert not set(out.columns) & OUTCOME_DENY_LIST
