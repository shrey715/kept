"""Nightly offline/online parity test (owner: Track A). Blocks deploys if the two
differ by more than 0.1% (share of mismatched cells)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from kept.config import PARITY_MAX_MISMATCH_RATE
from kept.contracts.feature_registry import FEATURES
from kept.contracts.features import FeatureVector
from kept.contracts.interfaces import FeatureProvider


@dataclass(frozen=True, slots=True)
class ParityReport:
    n_cells: int
    n_mismatched: int
    mismatch_rate: float
    worst_features: tuple[tuple[str, int], ...]  # (feature, mismatches) descending
    missing_entities: tuple[str, ...]  # in one frame but not the other
    passed: bool


def parity_report(
    offline: pd.DataFrame,
    online: pd.DataFrame,
    *,
    key: str = "case_id",
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-9,
    max_mismatch_rate: float = PARITY_MAX_MISMATCH_RATE,
) -> ParityReport:
    """Compare the same entities' features cell by cell. Floats compare with
    math.isclose(rel_tol, abs_tol); None == None and NaN == NaN count as equal; None vs
    a value is a mismatch. Missing entities fail parity regardless of rate.
    Different column sets -> ValueError."""
    if set(offline.columns) != set(online.columns):
        raise ValueError(
            f"offline and online have different columns: {sorted(set(offline.columns) ^ set(online.columns))}"
        )
    if offline[key].duplicated().any() or online[key].duplicated().any():
        raise ValueError(f"{key} must be unique in both frames")
    off, on = offline.set_index(key), online.set_index(key)
    missing = tuple(sorted({str(k) for k in off.index.symmetric_difference(on.index)}))
    common = off.index.intersection(on.index).sort_values()
    off, on = off.loc[common], on.loc[common]

    mismatches: dict[str, int] = {}
    for column in off.columns:
        equal = _equal(off[column], on[column], rel_tol=rel_tol, abs_tol=abs_tol)
        if (bad := int((~equal).sum())) > 0:
            mismatches[column] = bad
    n_cells = len(common) * len(off.columns)
    n_mismatched = sum(mismatches.values())
    rate = n_mismatched / n_cells if n_cells else 0.0
    worst = tuple(sorted(mismatches.items(), key=lambda item: (-item[1], item[0])))
    # nothing compared is not a pass; and any entity missing on one side fails whatever the rate
    passed = n_cells > 0 and not missing and rate <= max_mismatch_rate
    return ParityReport(n_cells, n_mismatched, rate, worst, missing, passed)


def _equal(a: pd.Series, b: pd.Series, *, rel_tol: float, abs_tol: float) -> pd.Series:
    """Cell-wise equality of two aligned columns: both null, or both values that match."""
    null_a, null_b = a.isna(), b.isna()
    equal = null_a & null_b
    both = ~null_a & ~null_b
    if not both.any():
        return equal
    av, bv = a[both], b[both]
    if is_numeric_dtype(av) and is_numeric_dtype(bv):
        values = pd.Series(
            np.isclose(av.to_numpy(float), bv.to_numpy(float), rtol=rel_tol, atol=abs_tol), index=av.index
        )
    else:  # strings, dates, or an object column that mixes numbers and None
        values = pd.Series(
            [_same(x, y, rel_tol, abs_tol) for x, y in zip(av, bv, strict=True)], index=av.index
        )
    result = equal.to_numpy().copy()
    result[both.to_numpy()] = values.to_numpy()
    return pd.Series(result, index=a.index)


def _same(x: object, y: object, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(x, int | float | np.number) and isinstance(y, int | float | np.number):
        return math.isclose(float(x), float(y), rel_tol=rel_tol, abs_tol=abs_tol)
    return bool(x == y)


_COLUMNS = ("case_id", "golden_customer_id", "feature_set_version", *(f.name for f in FEATURES))


def _vector(row: dict[Any, Any]) -> FeatureVector:
    """An offline row as the contract model reads it: the same types the online path serves."""
    clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
    as_of = pd.Timestamp(str(clean["as_of"]))
    clean["as_of"] = (as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of).to_pydatetime()
    return FeatureVector(**clean)


def _cells(vector: FeatureVector) -> dict[str, Any]:
    cells = vector.model_dump(mode="json")
    del cells["as_of"]  # the time itself is not a feature value
    return cells


def run_parity(
    conn: duckdb.DuckDBPyConnection, provider: FeatureProvider, *, sample: int | None = 2000, seed: int = 7
) -> ParityReport:
    """Offline features (features.case_features in the warehouse) against the same cases read back
    from the online store through `provider`. Both sides are read through FeatureVector, so a value
    that serves differently from how it was built shows up. A case missing online is a missing entity.
    `sample` cases chosen at random (None = every case)."""
    columns = ", ".join(("as_of", *_COLUMNS))
    pick = f" using sample reservoir({int(sample)} rows) repeatable ({int(seed)})" if sample else ""
    rows = conn.execute(f"select {columns} from features.case_features{pick}").df().to_dict("records")
    offline = [_cells(_vector(row)) for row in rows]
    online = []
    for row in offline:
        try:
            online.append(_cells(provider.get_online(row["case_id"])))
        except KeyError:
            continue  # not in the online store: reported as a missing entity
    columns_out = [c for c in _COLUMNS]
    return parity_report(
        pd.DataFrame(offline, columns=columns_out), pd.DataFrame(online, columns=columns_out)
    )


def parity_markdown(report: ParityReport, *, cases: int, as_of: str, generated: str) -> str:
    """The parity report as Markdown (G3 exit check: "parity report produced")."""
    worst = (
        "\n".join(f"| {name} | {count:,} |" for name, count in report.worst_features[:10]) or "| none | 0 |"
    )
    return "\n".join(
        [
            "# Offline / online feature parity",
            "",
            f"Generated {generated}. Offline: `features.case_features` in the warehouse (as of {as_of}). "
            "Online: the Feast online store, read through `FeatureVector`.",
            "",
            f"Result: **{'PASS' if report.passed else 'FAIL'}**: {report.n_mismatched:,} of "
            f"{report.n_cells:,} cells differ ({report.mismatch_rate:.4%}; the limit is "
            f"{PARITY_MAX_MISMATCH_RATE:.1%}).",
            "",
            f"- Cases compared: {cases:,}; missing from one side: {len(report.missing_entities):,}",
            "- Floats compare to 1e-9; null equals null; null against a value is a mismatch",
            "",
            "| Feature with mismatches | Cells |",
            "|---|---|",
            worst,
            "",
        ]
    )
