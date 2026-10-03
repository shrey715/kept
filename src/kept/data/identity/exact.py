"""Exact links (design §3), with the data dictionary's keys:

  collections_cases.coll_customer_ref  = customers.crm_customer_id   (copied from CRM at case open)
  card_accounts.autopay_source_account = deposit_accounts.deposit_account_id
  loan_accounts.pad_source_account     = deposit_accounts.deposit_account_id
  customers.national_id_hash identical across CRM records
  customers.duplicate_of_crm_id        (CRM's own, incomplete duplicate pointer)
  deposit_accounts.src_customer_ref    = external.bank_subject_ref   (both are the core-banking CIF)

A payment source account that is not one of our deposit accounts (another FI) links nothing.
The CIF rule is not in the design: it comes from the release README ("Customer keys") and was
checked on the data: for the 495,420 keys in both tables, name, DOB and postal code agree 99.7-100%.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EXACT_RULES = (
    "exact:case_crm_ref",
    "exact:payment_source_account",
    "exact:national_id_hash",
    "exact:crm_duplicate_pointer",
    "exact:core_banking_cif",
)


_PAIR = ["left_system", "left_key", "right_system", "right_key"]


def _pairs(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    return frame[_PAIR].assign(rule=rule)


def _star(me: pd.DataFrame, column: str, rule: str) -> pd.DataFrame:
    """Pairs every key that shares a non-null `column` value with the smallest such key."""
    # ponytail: star to the smallest key, not every pair: the same clusters, linear pairs;
    # a value shared by hundreds of keys would otherwise make hundreds of thousands of pairs
    shared = me.loc[me[column].notna(), ["left_system", "left_key", column]].drop_duplicates()
    shared = shared.sort_values([column, "left_system", "left_key"])
    anchor = (
        shared.groupby(column)
        .first()
        .rename(columns={"left_system": "right_system", "left_key": "right_key"})
    )
    return _pairs(shared.merge(anchor, on=column), rule)


def exact_link_pairs(records: pd.DataFrame) -> pd.DataFrame:
    """Candidate pairs linked by an exact rule.

    Input: one row per piece of key evidence. Columns: source_system, source_key, crm_ref,
    payment_source_account, deposit_account_id, national_id_hash, duplicate_of_crm_id
    (any may be null), and optionally core_banking_cif. A source key may appear on several rows
    (e.g. one per account).
    Output columns: left_system, left_key, right_system, right_key, rule (one of
    EXACT_RULES), score (always 1.0).

    Nulls never match nulls. Each unordered pair appears once, with
    (left_system, left_key) < (right_system, right_key). A record never pairs with itself.
    """
    me = records.rename(columns={"source_system": "left_system", "source_key": "left_key"})
    found = []

    def to_crm(col: str, rule: str) -> None:  # the row's key links to a CRM record named in `col`
        rows = me[me[col].notna()]
        found.append(_pairs(rows.assign(right_system="crm", right_key=rows[col]), rule))

    to_crm("crm_ref", EXACT_RULES[0])

    # a payment source account that is none of our deposit accounts (another FI) matches nothing
    deposits = me.loc[me["deposit_account_id"].notna(), ["left_system", "left_key", "deposit_account_id"]]
    deposits = deposits.rename(columns={"left_system": "right_system", "left_key": "right_key"})
    payers = me[me["payment_source_account"].notna()]
    joined = payers.merge(deposits, left_on="payment_source_account", right_on="deposit_account_id")
    found.append(_pairs(joined.drop(columns="deposit_account_id_x"), EXACT_RULES[1]))

    found.append(_star(me, "national_id_hash", EXACT_RULES[2]))

    to_crm("duplicate_of_crm_id", EXACT_RULES[3])

    if "core_banking_cif" in me:  # same star as the national ID rule
        found.append(_star(me, "core_banking_cif", EXACT_RULES[4]))

    pairs = pd.concat(found, ignore_index=True)
    # order each pair, drop self pairs, keep one row per pair under the first rule that found it
    swap = (pairs.left_system > pairs.right_system) | (
        (pairs.left_system == pairs.right_system) & (pairs.left_key > pairs.right_key)
    )
    for a, b in (("left_system", "right_system"), ("left_key", "right_key")):
        pairs[a], pairs[b] = np.where(swap, pairs[b], pairs[a]), np.where(swap, pairs[a], pairs[b])
    pairs = pairs[(pairs.left_system != pairs.right_system) | (pairs.left_key != pairs.right_key)]
    pairs["_priority"] = pairs["rule"].map({r: i for i, r in enumerate(EXACT_RULES)})
    pairs = pairs.sort_values("_priority", kind="stable").drop_duplicates(_PAIR).drop(columns="_priority")
    return pairs.sort_values(_PAIR).assign(score=1.0).reset_index(drop=True)
