"""Feature drift: is tonight's population still the one the uplift model was trained on?

Population stability index (PSI) per feature, training rows (features_train.case_features) against the
features served tonight (data/exports/features/case_features.parquet). Numbers are cut at the training
deciles, categories by value; missing values are their own bin, so a feature that goes blank drifts too.
The usual reading: under 0.1 stable, 0.1 to 0.25 watch, 0.25 or more drift (retrain or investigate).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

WATCH, DRIFT = 0.1, 0.25
_EPS = 1e-4  # an empty bin on one side would make the log blow up


@dataclass(frozen=True, slots=True)
class FeatureDrift:
    feature: str
    psi: float
    missing_train: float  # share of training rows with no value
    missing_live: float

    @property
    def status(self) -> str:
        return "drift" if self.psi >= DRIFT else "watch" if self.psi >= WATCH else "stable"


def _shares(values: pd.Series, edges: np.ndarray | None, levels: list[object] | None) -> np.ndarray:
    known = values.dropna()
    if edges is not None:
        counts = np.bincount(
            np.searchsorted(edges, known.astype(float), side="right"), minlength=len(edges) + 1
        )
    else:
        counts = np.array([(known == level).sum() for level in levels or []])
    counts = np.append(counts, values.isna().sum())  # the missing bin
    return np.maximum(counts / max(len(values), 1), _EPS)


def psi(train: pd.Series, live: pd.Series) -> float:
    """PSI of `live` against `train`: numbers binned at the training deciles, anything else by value."""
    numeric = pd.api.types.is_numeric_dtype(train) and not pd.api.types.is_bool_dtype(train)
    edges = levels = None
    if numeric:
        known = train.dropna().astype(float)
        edges = np.unique(np.quantile(known, np.linspace(0.1, 0.9, 9))) if len(known) else np.array([])
    else:
        levels = sorted(set(train.dropna()) | set(live.dropna()), key=str)
    e, a = _shares(train, edges, levels), _shares(live, edges, levels)
    return float(np.sum((a - e) * np.log(a / e)))


def drift_report(train: pd.DataFrame, live: pd.DataFrame, features: list[str]) -> list[FeatureDrift]:
    """One FeatureDrift per feature present in both frames, worst first."""
    out = [
        FeatureDrift(f, psi(train[f], live[f]), float(train[f].isna().mean()), float(live[f].isna().mean()))
        for f in features
        if f in train and f in live
    ]
    return sorted(out, key=lambda d: -d.psi)


def to_markdown(rows: list[FeatureDrift], *, train_rows: int, live_rows: int, live_as_of: str) -> str:
    worst = rows[0].status if rows else "stable"
    counts = {s: sum(r.status == s for r in rows) for s in ("drift", "watch", "stable")}
    lines = [
        "# Feature drift report",
        "",
        f"Training rows (features_train.case_features): {train_rows:,} · served tonight: {live_rows:,} cases "
        f"(features as of {live_as_of}). Written by `kept drift`.",
        "",
        f"Overall: **{worst.upper()}** · {counts['drift']} drift · {counts['watch']} watch · "
        f"{counts['stable']} stable. PSI under {WATCH} is stable, {WATCH} to {DRIFT} watch, {DRIFT} or more "
        "drift (investigate, then retrain). Missing values are their own bin.",
        "",
        "Training rows are every past decision since 2016 and tonight is the open book, so part of any",
        "drift is that difference, not a change in customers.",
        *(
            [
                "",
                "**Never seen in training** (missing for every training row, so the model learned "
                "nothing from them): " + ", ".join(f"`{r.feature}`" for r in unseen) + ".",
            ]
            if (unseen := [r for r in rows if r.missing_train >= 0.99 and r.missing_live < 0.99])
            else []
        ),
        "",
        "| feature | PSI | status | missing (train) | missing (tonight) |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.feature} | {r.psi:.3f} | {r.status} | {r.missing_train:.0%} | {r.missing_live:.0%} |"
        for r in rows
    ]
    return "\n".join(lines) + "\n"


ALARM_FILE = "drift_alarm.json"  # next to the served features export
# features that move with the calendar every night by design: days_to_next_payroll counts down a
# day per night (PSI 0.25 night over night on real data, everything else about 0)
CALENDAR = frozenset({"days_to_next_payroll"})


def night_over_night(previous: pd.DataFrame, tonight: pd.DataFrame, features: list[str]) -> dict[str, object]:
    """Tonight's served features against last night's, model inputs only (#86). Training against
    serving drifts by construction (snapshot-only features are null in training, cohort rates move
    over the year), so the alarm compares serving with serving: a sudden shift means a feed broke or
    the book changed overnight, and a person should look before cards go out."""
    rows = drift_report(previous, tonight, [f for f in features if f not in CALENDAR])
    return {
        "previous_as_of": str(previous["as_of"].max()) if len(previous) else None,
        "as_of": str(tonight["as_of"].max()) if len(tonight) else None,
        "drifted": [r.feature for r in rows if r.status == "drift"],
        "psi": {r.feature: round(r.psi, 4) for r in rows},
    }


def load_alarm(directory: Path) -> list[str]:
    """The drifted model inputs from the last `kept features` run; none if there is no alarm file."""
    import json

    path = directory / ALARM_FILE
    return list(json.loads(path.read_text())["drifted"]) if path.exists() else []
