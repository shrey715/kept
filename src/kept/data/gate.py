"""`kept gate`: evaluate Q1-Q5 on the warehouse, write the data quality report and the Soda checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from kept.config import DATA_CONTRACT_PATH, EXPORT_DIR, REPO_ROOT
from kept.contracts.data_contract import load_data_contract
from kept.data.gold import DO_NOT_CONTACT_FLAGS, HARD_STOP_FLAGS
from kept.data.quality import (
    QualityResult,
    check_contact_safety,
    check_freshness,
    check_linkage,
    check_match_safety,
    check_review_precision,
    check_row_count,
    check_unique_ids,
    generate_soda_checks,
)

SODA_CHECKS = REPO_ROOT / "soda" / "checks" / "c360_customer.yml"
STATE = EXPORT_DIR / "quality" / "state.json"  # last load's row count, for Q5
REVIEWED_PAIRS = REPO_ROOT / "data" / "labels" / "match_pairs.csv"  # Phase 4: the 300 reviewed pairs


def write_soda_checks(path: Path = SODA_CHECKS) -> Path:
    path.write_text(generate_soda_checks(load_data_contract(DATA_CONTRACT_PATH)))
    return path


def gather_results(
    conn: duckdb.DuckDBPyConnection, *, published_at: datetime | None = None
) -> list[QualityResult]:
    """Q1-Q5 on the current warehouse. Q3's weekly precision runs only once the reviewed sample exists."""
    c360 = conn.execute(
        "select golden_customer_id, do_not_contact, collections_hold from gold.c360_customer"
    ).df()
    crosswalk = conn.execute("select * from gold.identity_crosswalk").df()
    national_ids = conn.execute(
        "select x.golden_customer_id, r.national_id_hash from gold.identity_crosswalk x "
        "join silver.int_identity_records r on r.source_system = x.source_system "
        "and r.source_key = x.source_key "
        "where x.valid_to is null and r.national_id_hash is not null"
    ).df()

    # Q2. Every open case resolves; an account key "links" when its golden ID also holds a CRM record.
    cases = conn.execute(
        "select c.case_id, x.golden_customer_id is not null as resolved from silver.collections_cases c "
        "left join gold.identity_crosswalk x on x.source_system = 'collections' "
        "and x.source_key = c.coll_customer_ref and x.valid_to is null where c.outcome is null"
    ).df()
    keys = conn.execute(
        """
        with account_keys as (
            select 'card' as source_system, src_customer_ref as source_key from silver.card_accounts
            union select 'loan', src_customer_ref from silver.loan_accounts
            union select 'deposit', src_customer_ref from silver.deposit_accounts
        ), has_crm as (
            select golden_customer_id from gold.identity_crosswalk
            where source_system = 'crm' and valid_to is null
        )
        select count(*), count(h.golden_customer_id)
        from account_keys k
        left join gold.identity_crosswalk x on x.source_system = k.source_system
            and x.source_key = k.source_key and x.valid_to is null
        left join (select distinct golden_customer_id from has_crm) h
            on h.golden_customer_id = x.golden_customer_id
        """
    ).fetchone()
    assert keys is not None

    # Q4. The source flags behind each golden ID, one boolean column per flag.
    flag_names = sorted({*DO_NOT_CONTACT_FLAGS, *(f for flags in HARD_STOP_FLAGS.values() for f in flags)})
    events = conn.execute(
        "select x.golden_customer_id, e.flag from silver.int_flag_events e join gold.identity_crosswalk x "
        "on x.source_system = e.source_system and x.source_key = e.source_key and x.valid_to is null"
    ).df()
    source_flags = (
        events.assign(on=True)
        .pivot_table(index="golden_customer_id", columns="flag", values="on", aggfunc="any")
        .reindex(columns=flag_names)
        .fillna(False)
        .reset_index()
    )

    # Q5. Freshness: the source extract vs the gold build; row count vs the last load.
    extracted = conn.execute("select max(_extracted_at) from silver.customers").fetchone()
    refreshed = conn.execute("select max(refreshed_at) from gold.c360_customer").fetchone()
    assert extracted is not None and refreshed is not None
    previous = json.loads(STATE.read_text())["c360_rows"] if STATE.exists() else None

    results = [
        check_unique_ids(c360, crosswalk),
        check_linkage(
            set(cases["case_id"]), set(cases.loc[cases["resolved"], "case_id"]), int(keys[0]), int(keys[1])
        ),
        check_match_safety(crosswalk, national_ids),
        check_contact_safety(c360, source_flags),
        check_freshness(extracted[0], published_at or refreshed[0]),
        check_row_count(len(c360), previous),
    ]
    if REVIEWED_PAIRS.exists():
        results.append(check_review_precision(pd.read_csv(REVIEWED_PAIRS)))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"c360_rows": len(c360), "at": datetime.now(UTC).isoformat()}))
    return results
