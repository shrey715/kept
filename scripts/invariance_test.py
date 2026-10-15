"""Counterfactual invariance test: do protected attributes change any decision?

The brief: protected attributes "are included only to test fairness and must not be used in decisions". So we
scramble them and check nothing moves. On two copies of the warehouse (btrfs reflinks, so instant):

  1. perturbed copy: every protected attribute, and every proxy with no operational use, is shuffled across
     rows (each column independently) in every silver table that holds it;
  2. both copies: rebuild gold (c360, hardship, payroll ...) and the features with dbt from those tables;
  3. both copies: score every open case with the same model, clock and hold-out salt;
  4. compare every card field by field. Pass = zero differences.

Proxies left alone, because the bank needs them to contact the customer correctly (and that use is in the data
contract): language (contact in the customer's language), address and postal code (time zone, so calling
hours), date of birth (identity matching, already done before gold). The report lists them.

    uv run python scripts/invariance_test.py protected  # the brief's list only: must change nothing
    uv run python scripts/invariance_test.py all        # plus the proxies: only documented protective effects
(works on copies, so `kept serve` can keep running)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

from kept.config import EXPORT_DIR, WAREHOUSE_PATH
from kept.contracts.data_contract import load_data_contract

WORK = WAREHOUSE_PATH.parent / "invariance"
OUT = EXPORT_DIR / "reports" / "invariance_{}.json"  # one file per scenario
DBT_THREADS = "4"
OPERATIONAL = {  # proxies the bank must use to contact a customer correctly; not scrambled
    "preferred_language": "contact in the customer's language",
    "correspondence_language": "letters in the customer's language",
    "language_of_service": "which site and language serve the case",
    "language_used": "language of a past contact",
    "message_language": "language of a past message",
    "note_language": "language of an agent note",
    "postal_code": "address, time zone, so calling hours",
    "postal_code_raw": "address as captured",
    "fsa": "address, time zone",
    "city": "address",
    "geo_lat": "address",
    "geo_lon": "address",
    "date_of_birth": "identity matching (done before gold)",
    "dob_raw": "identity matching (done before gold)",
}
# fields of a card that must not move; ids and timestamps are new on every run, so they're left out
FIELDS = ["action", "tier", "headline", "no_action_reason", "p_paid_14d", "p_wait", "expected_value",
          "hardship", "hard_stop", "is_legacy_strategy"]  # fmt: skip
CARD_VOLATILE = {"proposal_id", "card_id", "scored_at", "created_at", "expires_at", "event_id"}


def copy(name: str) -> Path:
    dst = WORK / f"{name}.duckdb"
    dst.unlink(missing_ok=True)
    Path(f"{dst}.wal").unlink(missing_ok=True)
    subprocess.run(["cp", "--reflink=auto", str(WAREHOUSE_PATH), str(dst)], check=True)
    wal = Path(f"{WAREHOUSE_PATH}.wal")
    if wal.exists():  # uncommitted writes from a running `kept serve`: replayed when the copy opens
        shutil.copy(wal, f"{dst}.wal")
    return dst


def scramble(path: Path, names: set[str]) -> dict[str, list[str]]:
    """Shuffle each named column independently across the rows of every silver table that has it."""
    con = duckdb.connect(str(path))
    con.execute("select setseed(0.42)")
    cols = con.execute(
        "select table_name, column_name from information_schema.columns c join information_schema.tables t "
        "using (table_schema, table_name) where table_schema = 'silver' and table_type = 'BASE TABLE'"
    ).fetchall()
    done: dict[str, list[str]] = {}
    for table in sorted({t for t, c in cols if c in names}):
        hit = [c for t, c in cols if t == table and c in names]
        joins = "".join(
            f" join (select {c} as s{i}, row_number() over (order by random()) as rn from silver.{table})"
            f" j{i} using (rn)"
            for i, c in enumerate(hit)
        )
        repl = ", ".join(f"j{i}.s{i} as {c}" for i, c in enumerate(hit))
        con.execute(
            f"create or replace table silver.{table} as select b.* exclude (rn) replace ({repl}) "
            f"from (select *, row_number() over () as rn from silver.{table}) b{joins}"
        )
        done[table] = hit
    con.close()
    return done


def snapshot(path: Path) -> tuple[str, datetime]:
    """Tonight's feature date (read from a copy: `kept serve` may hold the warehouse), and one clock for both
    runs (calling hours depend on it)."""
    with duckdb.connect(str(path), read_only=True) as con:
        as_of = con.execute("select max(as_of) from features.case_features").fetchone()[0]  # type: ignore[index]
    as_of = as_of.replace(tzinfo=UTC)
    return as_of.isoformat(), datetime.now(UTC)


def rebuild(path: Path, features_as_of: str) -> None:
    """gold from silver, then the features: the dbt runs of `kept build --gold-only` and `kept features`.
    A subprocess each, so no dbt connection keeps the copy open in this process."""
    from kept.data.gold import DBT_DIR, GOLD_MODELS

    dbt = str(Path(sys.executable).parent / "dbt")
    common = ["--threads", DBT_THREADS, "--profiles-dir", str(DBT_DIR), "--project-dir", str(DBT_DIR)]
    env = os.environ | {"KEPT_WAREHOUSE_PATH": str(path)}
    for select, extra in (
        (list(GOLD_MODELS), []),
        (
            ["text_signals", "path:models/features"],
            ["--vars", json.dumps({"features_as_of": features_as_of})],
        ),
    ):
        subprocess.run([dbt, "build", "--select", *select, *extra, *common], env=env, check=True)


def score(path: Path, now: datetime) -> pd.DataFrame:
    from kept.common.audit import DuckDBAuditLog
    from kept.nba.score import score as score_all

    load_dotenv()  # a worker process: the hold-out salt comes from .env
    return score_all(
        path,
        model=EXPORT_DIR / "models" / "uplift.pkl",
        holdout_salt=os.environ["KEPT_HOLDOUT_SALT"],
        now=now,
        audit_log=DuckDBAuditLog(":memory:"),
    )


def stable_card(card: object) -> str:
    """The card JSON without ids and timestamps, keys sorted, so two runs compare equal when decisions do."""

    def strip(x: object) -> object:
        if isinstance(x, dict):
            return {k: strip(v) for k, v in sorted(x.items()) if k not in CARD_VOLATILE}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    return json.dumps(strip(json.loads(card) if isinstance(card, str) else card), default=str)


def moved(base: Path, pert: Path, table: str, key: str, cols: list[str]) -> dict[str, float]:
    """Share of rows whose value changed between the copies: proof the scramble reached that table."""
    con = duckdb.connect(str(base), read_only=True)
    con.execute(f"attach '{pert}' as p (read_only)")
    out = {}
    for c in cols:
        out[c] = con.execute(
            f"select avg(case when a.{c} is distinct from b.{c} then 1.0 else 0.0 end) "
            f"from {table} a join p.{table} b using ({key})"
        ).fetchone()[0]  # type: ignore[index]
    con.close()
    return out


def main(scenario: str) -> bool:
    load_dotenv()
    WORK.mkdir(parents=True, exist_ok=True)
    contract = load_data_contract()
    protected = set(contract.protected_attributes)
    proxies = set(contract.proxy_attributes) - set(OPERATIONAL)
    t0 = time.perf_counter()
    base, pert = copy("base"), copy("perturbed")
    features_as_of, now = snapshot(base)
    scrambled = scramble(pert, protected if scenario == "protected" else protected | proxies)
    print(f"scrambled {sum(map(len, scrambled.values()))} columns in {len(scrambled)} tables")
    # the two copies are independent: rebuild them side by side, then score them side by side
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda p: rebuild(p, features_as_of), (base, pert)))
    print(f"rebuilt gold + features on both copies ({time.perf_counter() - t0:.0f}s)")
    shown = {"gender_code", "marital_status", "citizenship_status", "household_size", "vulnerability_type"}
    reach = moved(base, pert, "gold.c360_restricted", "golden_customer_id", sorted(protected & shown))
    with ProcessPoolExecutor(2) as procs:
        a, b = procs.map(score, (base, pert), (now, now))
    print(f"scored {len(a):,} + {len(b):,} cases ({time.perf_counter() - t0:.0f}s)")
    m = a.merge(b, on="case_id", suffixes=("_base", "_pert"), how="outer", indicator=True)
    diffs = {}
    for f in FIELDS:
        x, y = m[f"{f}_base"], m[f"{f}_pert"]
        same = (x == y) | (x.isna() & y.isna())
        if f in ("p_paid_14d", "p_wait", "expected_value"):  # float sums differ in the last bits run to run
            same |= (x.astype(float) - y.astype(float)).abs() < 1e-6
        diffs[f] = int((~same).sum())
    cards_differ = int((m["card_base"].map(stable_card) != m["card_pert"].map(stable_card)).sum())
    examples = m.loc[m["action_base"].ne(m["action_pert"]), ["case_id", "action_base", "action_pert"]].head(
        10
    )
    gained = int((m["hardship_pert"].eq(True) & m["hardship_base"].eq(False)).sum())
    lost = int((m["hardship_pert"].eq(False) & m["hardship_base"].eq(True)).sum())
    data = {
        "scenario": scenario,
        "hardship_gained": gained,
        "hardship_lost": lost,
        "written": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": len(m),
        "only_one_side": int((m["_merge"] != "both").sum()),
        "scrambled": scrambled,
        "scramble_reached_gold": reach,
        "left_alone": OPERATIONAL,
        "field_differences": diffs,
        "cards_differ": cards_differ,
        "action_examples": examples.to_dict("records"),
        "passed": cards_differ == 0 and not any(diffs.values()) and int((m["_merge"] != "both").sum()) == 0,
        "seconds": round(time.perf_counter() - t0),
    }
    out = Path(str(OUT).format(scenario))
    data["features_as_of"] = features_as_of
    out.write_text(json.dumps(data, indent=1, default=str))
    print(
        json.dumps({k: data[k] for k in ("cases", "field_differences", "cards_differ", "passed")}, indent=1)
    )
    print(f"-> {out}")
    return bool(data["passed"])


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else "protected") else 1)
