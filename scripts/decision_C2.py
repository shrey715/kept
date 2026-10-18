# ruff: noqa: E501
"""C2: hardship by rule or by model (docs/reports/decisions.md).

    KEPT_DATA=/path/to/data uv run python scripts/decision_C2.py          # numbers + chart
    uv run python scripts/decision_C2.py demo

Target: agent-confirmed hardship (gold hardship_status 'confirmed', hardship_source 'agent'); negatives are
every other customer with a current payroll account, so a customer the rule flags but nobody confirmed (gold
'possible') counts against precision: precision is the share of flags an agent confirmed, a lower bound on how many
flags were right. Programme-confirmed customers are left out: a programme, not an agent, confirmed them. Inputs per customer (current payroll deposit accounts at the as-of date): worst payroll
delay, worst pay change, and EI (new deposit, days since first deposit). The rule is kept.hardship.cashflow_rule
unchanged. The model is LightGBM on the same inputs. Split: golden ids by hash, 60% fit / 15% validation / 25% test;
validation picks the early-stopping round and the thresholds, the test split is only scored.
Fairness: kept.governance.fairness.recommendation_rates over gold.c360_restricted attributes (flag rate; and
recall among the confirmed).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
DATA = Path(os.environ.get("KEPT_DATA", REPO / "data"))
OUT = DATA / "exports" / "reports" / "decision_C2.json"
AS_OF = date(2026, 9, 28)
SEED = 214

SQL = f"""
select x.golden_customer_id as gid,
       max(d.payroll_delay_days) as delay, min(cast(d.payroll_amount_change_pct as double)) as change,
       bool_or(d.ei_deposit_flag) as ei_flag, min(d.ei_first_deposit_date) as ei_first
from silver.deposit_accounts d
join silver.int_crosswalk x on x.source_system = 'deposit' and x.source_key = d.src_customer_ref and x.valid_to is null
where d.snapshot_date between date '{AS_OF}' - interval 35 day and date '{AS_OF}' and d.payroll_deposit_flag
group by 1
"""


def load(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, pd.DataFrame]:
    from kept.hardship.cashflow_rule import cash_flow_hardship, new_ei_deposit

    df = con.execute(SQL).df()
    lab = con.execute("select golden_customer_id as gid, hardship_status as st, hardship_source as src from gold.c360_customer").df()
    df = df.merge(lab, on="gid")
    counts = {"payroll_customers": len(df), **{f"{s}/{r}": int(n) for (s, r), n in df.groupby(["st", "src"], dropna=False).size().items()}}
    df = df[~((df.st == "confirmed") & (df.src == "account_programme"))].copy()  # a programme, not an agent
    df["y"] = (df.st == "confirmed").astype(int)
    first = pd.to_datetime(df.ei_first).dt.date
    df["ei_days"] = [(AS_OF - f).days if f is not None and f == f else np.nan for f in first]
    df["new_ei"] = [
        new_ei_deposit(ei_deposit_flag=None if pd.isna(a) else bool(a), ei_first_deposit_date=(f if f == f else None), as_of=AS_OF)
        for a, f in zip(df.ei_flag, first, strict=True)
    ]
    df["delay"] = df["delay"].astype(float)
    nz = lambda v: None if pd.isna(v) else v  # noqa: E731
    for with_ei in (False, True):
        df[f"rule_{'ei' if with_ei else 'noei'}"] = [
            cash_flow_hardship(payroll_delay_days=None if pd.isna(d) else int(d), pay_change_vs_3m_avg=nz(c),
                               new_ei_deposit=(nz(n) if with_ei else None))
            for d, c, n in zip(df.delay, df.change, df.new_ei, strict=True)
        ]
    df["ei_new_f"] = df.new_ei.map({True: 1.0, False: 0.0}).astype(float)
    df["ei_flag_f"] = df.ei_flag.map({True: 1.0, False: 0.0}).astype(float)
    return df, pd.Series(counts)  # type: ignore[return-value]


def split(df: pd.DataFrame) -> pd.Series:
    h = pd.util.hash_pandas_object(df.gid.astype(str) + str(SEED), index=False) % 100
    return pd.Series(np.where(h < 60, "fit", np.where(h < 75, "val", "test")), index=df.index)


def rates(pred: np.ndarray, y: np.ndarray) -> dict[str, float]:
    tp = int((pred & (y == 1)).sum())
    return {
        "flag_rate": float(pred.mean()), "recall": tp / max(int(y.sum()), 1),
        "precision": tp / max(int(pred.sum()), 1), "tp": tp, "flagged": int(pred.sum()), "positives": int(y.sum()),
    }


def fairness(test: pd.DataFrame, flags: dict[str, np.ndarray], restricted: pd.DataFrame) -> dict[str, Any]:
    from kept.config import COHORT_MIN_GROUP_SIZE
    from kept.contracts.data_contract import load_data_contract
    from kept.governance.fairness import MIN_EVENTS, recommendation_rates

    c = load_data_contract()
    attrs = sorted((c.protected_attributes | c.proxy_attributes) & set(restricted.columns))
    j = test.assign(**{n: f for n, f in flags.items()}).merge(restricted, left_on="gid", right_on="golden_customer_id", how="left")
    out: dict[str, Any] = {}
    for a in attrs:
        if j[a].nunique(dropna=True) > 25:
            continue
        k = j[j[a].notna()]
        g = k[a].astype("string").tolist()
        out[a] = {}
        for name in flags:
            sel = recommendation_rates(k[name].tolist(), g, min_group_size=COHORT_MIN_GROUP_SIZE, min_events=MIN_EVENTS)
            pos = k[k.y == 1]
            rec = recommendation_rates(pos[name].tolist(), pos[a].astype("string").tolist(), min_group_size=COHORT_MIN_GROUP_SIZE, min_events=MIN_EVENTS)
            out[a][name] = {"flag_rate_ratio": sel.min_ratio, "flag_rate_flagged": sel.flagged,
                            "recall_ratio": rec.min_ratio, "recall_flagged": rec.flagged}
    return out


def main() -> None:
    import lightgbm as lgb
    from sklearn.metrics import average_precision_score, roc_auc_score

    con = duckdb.connect(str(DATA / "warehouse" / "eval_copy.duckdb"), read_only=True)
    con.execute("SET memory_limit='2GB'; SET threads=4")
    df, counts = load(con)
    restricted = con.execute("select * from gold.c360_restricted").df()
    con.close()
    df["part"] = split(df)
    ne = df[df.new_ei == True]  # noqa: E712
    counts["new_ei_customers"] = len(ne)
    counts["new_ei_customers_not_flagged_by_delay_or_pay_drop"] = int((~ne.rule_noei).sum())
    feats = {"no_ei": ["delay", "change"], "with_ei": ["delay", "change", "ei_new_f", "ei_days", "ei_flag_f"]}
    fit, val, test = (df[df.part == p] for p in ("fit", "val", "test"))
    res: dict[str, Any] = {
        "population": counts.to_dict(),
        "n": {p: int((df.part == p).sum()) for p in ("fit", "val", "test")},
        "positives": {p: int(df[df.part == p].y.sum()) for p in ("fit", "val", "test")},
        "systems": {},
    }
    flags: dict[str, np.ndarray] = {}
    y = test.y.to_numpy()
    for tag in ("noei", "ei"):
        flags[f"rule_{tag}"] = test[f"rule_{tag}"].to_numpy()
        res["systems"][f"rule_{tag}"] = {**rates(flags[f"rule_{tag}"], y), "on_val": rates(val[f"rule_{tag}"].to_numpy(), val.y.to_numpy())}
    for tag, cols in (("noei", feats["no_ei"]), ("ei", feats["with_ei"])):
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=50,
                               n_jobs=4, random_state=SEED, verbose=-1)
        m.fit(fit[cols], fit.y, eval_set=[(val[cols], val.y)], eval_metric="average_precision",
              callbacks=[lgb.early_stopping(30, verbose=False)])
        pv, pt = m.predict_proba(val[cols])[:, 1], m.predict_proba(test[cols])[:, 1]
        ths = np.unique(np.quantile(pv, np.linspace(0.01, 0.99, 197)))
        f1 = [(2 * (rates(pv >= t, val.y.to_numpy())["precision"] * rates(pv >= t, val.y.to_numpy())["recall"])
               / max(rates(pv >= t, val.y.to_numpy())["precision"] + rates(pv >= t, val.y.to_numpy())["recall"], 1e-9)) for t in ths]
        t_f1 = float(ths[int(np.argmax(f1))])
        rule_rate = float(val[f"rule_{tag}"].mean())
        t_match = float(np.quantile(pv, 1 - rule_rate))  # same share flagged as the rule, on validation
        for name, t in (("f1", t_f1), ("same_flag_rate", t_match)):
            key = f"lgbm_{tag}_{name}"
            flags[key] = pt >= t
            res["systems"][key] = {**rates(flags[key], y), "threshold": t}
        res["systems"][f"lgbm_{tag}_f1"].update(
            roc_auc=float(roc_auc_score(y, pt)), pr_auc=float(average_precision_score(y, pt)), best_iteration=int(m.best_iteration_ or 0))
        res["systems"][f"lgbm_{tag}_f1"]["importance_gain"] = dict(zip(cols, map(float, m.booster_.feature_importance("gain")), strict=True))
    res["base_rate_test"] = float(y.mean())
    for tag in ("noei", "ei"):  # AUC of the rule as a 0/1 score, for the same table
        res["systems"][f"rule_{tag}"]["roc_auc"] = float(roc_auc_score(y, flags[f"rule_{tag}"].astype(int)))
    fair = fairness(test, flags, restricted)
    res["fairness"] = fair
    res["fairness_summary"] = {
        name: {
            "attributes": len(fair),
            "flag_rate_below_four_fifths": [a for a in fair if fair[a][name]["flag_rate_flagged"]],
            "recall_below_four_fifths": [a for a in fair if fair[a][name]["recall_flagged"]],
            "lowest_flag_rate_ratio": min(fair[a][name]["flag_rate_ratio"] for a in fair),
            "lowest_recall_ratio": min(fair[a][name]["recall_ratio"] for a in fair),
        }
        for name in flags
    }
    OUT.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: res[k] for k in ("population", "n", "positives", "base_rate_test")}, indent=1))
    for k, v in res["systems"].items():
        print(k, {a: round(b, 4) for a, b in v.items() if isinstance(b, float)})
    for k, v in res["fairness_summary"].items():
        print(k, v)
    chart(res)


def chart(res: dict[str, Any]) -> None:
    from reportlib import BLUE, KEPT, MUTED, ORANGE, plt, save, style, tidy

    style()
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2))
    names = ["rule_noei", "lgbm_noei_same_flag_rate", "lgbm_noei_f1", "rule_ei", "lgbm_ei_same_flag_rate", "lgbm_ei_f1"]
    y = list(range(len(names)))[::-1]
    for k, m in enumerate(("recall", "precision")):
        bars = a.barh([v + (0.2 if k == 0 else -0.2) for v in y], [res["systems"][n][m] for n in names], 0.38,
                      color=[KEPT if n.startswith("rule") else BLUE for n in names], alpha=1 if k == 0 else 0.45, label=m)
        a.bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
    a.set_yticks(y, [n.replace("_", " ") for n in names], fontsize=8)
    a.set_xlabel("solid: recall, light: precision, vs agent-confirmed hardship (test split)")
    a.set_title("Rule vs LightGBM", loc="left", fontsize=11)
    tidy(a, "x")
    fs = res["fairness_summary"]
    names2 = ["rule_noei", "lgbm_noei_f1", "rule_ei", "lgbm_ei_f1"]
    xs = list(range(len(names2)))
    w1 = b.bar([i - 0.2 for i in xs], [fs[n]["lowest_flag_rate_ratio"] for n in names2], 0.38, color=ORANGE, label="lowest flag-rate ratio")
    w2 = b.bar([i + 0.2 for i in xs], [fs[n]["lowest_recall_ratio"] for n in names2], 0.38, color=MUTED, label="lowest recall ratio")
    b.bar_label(w1, fmt="%.2f", padding=2, fontsize=8)
    b.bar_label(w2, fmt="%.2f", padding=2, fontsize=8)
    b.axhline(0.8, color=KEPT, linestyle="--", linewidth=1)
    b.set_xticks(xs, [n.replace("_", " ") for n in names2], fontsize=8)
    b.set_title("Four-fifths screen: worst attribute", loc="left", fontsize=11)
    b.legend(frameon=False, fontsize=8)
    tidy(b, "y")
    print(save(fig, "dec_C2"))


def demo() -> None:
    assert (split(pd.DataFrame({"gid": [str(i) for i in range(1000)]})) == "test").mean() > 0.15
    assert rates(np.array([True, True, False]), np.array([1, 0, 1]))["recall"] == 0.5


if __name__ == "__main__":
    demo() if sys.argv[1:] == ["demo"] else main()
