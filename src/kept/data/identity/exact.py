"""Exact links (design §3), with the data dictionary's keys:

  collections_cases.coll_customer_ref  = customers.crm_customer_id   (copied from CRM at case open)
  card_accounts.autopay_source_account = deposit_accounts.deposit_account_id
  loan_accounts.pad_source_account     = deposit_accounts.deposit_account_id
  customers.national_id_hash identical across CRM records
  customers.duplicate_of_crm_id        (CRM's own, incomplete duplicate pointer)

A payment source account that is not one of our deposit accounts (another FI) links nothing.
external.bank_subject_ref has no exact key: it goes to Splink.
"""

from __future__ import annotations

import pandas as pd

EXACT_RULES = (
    "exact:case_crm_ref",
    "exact:payment_source_account",
    "exact:national_id_hash",
    "exact:crm_duplicate_pointer",
)


def exact_link_pairs(records: pd.DataFrame) -> pd.DataFrame:
    """Candidate pairs linked by an exact rule.

    Input: one row per piece of key evidence. Columns: source_system, source_key, crm_ref,
    payment_source_account, deposit_account_id, national_id_hash, duplicate_of_crm_id
    (any may be null). A source key may appear on several rows (e.g. one per account).
    Output columns: left_system, left_key, right_system, right_key, rule (one of
    EXACT_RULES), score (always 1.0).

    Nulls never match nulls. Each unordered pair appears once, with
    (left_system, left_key) < (right_system, right_key). A record never pairs with itself.
    """
    raise NotImplementedError("Track A")
