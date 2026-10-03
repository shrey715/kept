"""Every number the system design commits to, in one place.

These are specification, not tuning knobs. Changing one changes the design:
update the design doc and tell the team. Values marked TBC are our placeholder
until the organisers or the data dictionary confirm them.
"""

from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- paths
REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DATA_DIR: Final = REPO_ROOT / "data"
RAW_DIR: Final = DATA_DIR / "raw"
WAREHOUSE_PATH: Final = DATA_DIR / "warehouse" / "kept.duckdb"
EXPORT_DIR: Final = DATA_DIR / "exports"
QUARANTINE_DIR: Final = DATA_DIR / "quarantine"
DATA_CONTRACT_PATH: Final = REPO_ROOT / "contracts" / "c360_customer.odcs.yaml"

# --------------------------------------------------------------- Layer 1: identity
AUTO_LINK_THRESHOLD: Final = 0.95  # score >= this links automatically
STEWARD_REVIEW_THRESHOLD: Final = 0.80  # [0.80, 0.95) goes to a data steward
MAX_KEYS_PER_CLUSTER: Final = 12  # clusters with more keys always go to review
MATCH_PRECISION_TARGET: Final = 0.98  # on the 300-pair reviewed sample
MATCH_REVIEW_SAMPLE_SIZE: Final = 300
GOLDEN_ID_PATTERN: Final = r"^G-\d{6,}$"  # e.g. G-004817

# --------------------------------------------------------- Layer 1: quality gate
LINKAGE_TARGET: Final = 0.98  # share of account keys that link
LINKAGE_BLOCK_BELOW: Final = 0.97
FRESHNESS_WARN: Final = timedelta(hours=26)
FRESHNESS_BLOCK: Final = timedelta(hours=48)
ROW_COUNT_TOLERANCE: Final = 0.10  # vs the last load
PUBLISH_DEADLINE_ET: Final = time(6, 0)  # nightly, America/Toronto
CONSENT_CHANGE_SLA: Final = timedelta(minutes=15)  # consent/cease/hold via online store

# ------------------------------------------------------------ Layer 2: Ask
SQL_CANDIDATES: Final = 3  # lookups: 3 LLM-written candidates, keep the majority
ASK_DEFAULT_ROW_LIMIT: Final = 1_000
ASK_SQL_TIMEOUT_S: Final = 10.0
ASK_LATENCY_BUDGET_S: Final = 5.0
ASK_ACCURACY_TARGET: Final = 0.80
ASK_REFUSAL_RECALL_TARGET: Final = 0.95
ANALYST_MIN_GROUP_SIZE: Final = 10  # analysts see aggregates of 10 or more
MAX_CLARIFYING_QUESTIONS: Final = 1  # one clarifying question, then refuse

# ---------------------------------------------------- Layer 3: features and text
PARITY_MAX_MISMATCH_RATE: Final = 0.001  # nightly offline/online parity, blocks deploys
COHORT_MIN_GROUP_SIZE: Final = 50  # cohort stats only for groups of 50+
TEXT_FEATURE_MIN_F1: Final = 0.80
HARDSHIP_MIN_RECALL: Final = 0.90
TEXT_EVAL_SAMPLE_SIZE: Final = 500  # public labels per source; gate on the 30% holdout (kept.text.labels)

# ------------------------------------------------- Layer 4: decisioning
PAID_WINDOW_DAYS: Final = 14  # outcome: paid within 14 days (paid_14d)
CALLING_HOURS_START: Final = time(7, 0)  # local, inclusive
CALLING_HOURS_END: Final = time(21, 0)  # local, exclusive
CONTACT_CAP_7D: Final = 3  # default only; each case carries collections_cases.contact_cap_7d
PROMISE_DAYS_AFTER_PAYDAY: Final = (1, 2)  # promises due 1-2 days after expected payday
TOP_REASONS: Final = 3  # TreeSHAP top 3
CLOSE_CALL_MARGIN: Final = 0.02  # top two scores within 2% of the top: "close" (D: 7% of real cases)
HOLDOUT_SHARE: Final = 0.05  # permanent hold-out on the old strategy
GREEN_BATCH_SAMPLE_SIZE: Final = 20  # team lead samples 20 cases before approving
PROPOSAL_TTL: Final = timedelta(hours=4)  # TBC: approvals expire
FEATURE_MAX_STALENESS: Final = timedelta(hours=26)  # stale data means "no action"
CARD_LATENCY_BUDGET_MS: Final = 300
ROLL_RATE_ENTRY_DPD: Final = (1, 30)  # north-star cohort: cases entering at 1-30 DPD

# Money is always Decimal, rounded to cents.
CENT: Final = Decimal("0.01")
