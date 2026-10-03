"""The release's public gold labels (500 notes, 500 call transcripts) as TextExtraction-shaped
values, for the extraction F1 gate. Files: data/labels/{agent_notes,call_transcripts}_labels_public_500.csv.

Label column -> TextExtraction field (the rest are unused: see UNUSED):
  label_hardship            -> hardship_signal  (none / possible / clear, same values)
  label_hardship_evidence   -> hardship_signal quote
  label_hardship_reason     -> stated_reason    (via REASON_MAP; blank -> none)
  label_ptp_mentioned       -> promise_intent
  label_ptp_date            -> promised_date
  label_ptp_amount          -> promised_amount
  label_dispute             -> dispute
  label_cease_request       -> cease_request
  label_third_party_present -> third_party_present
"""

from __future__ import annotations

import csv
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from kept.contracts import HardshipSignal, StatedReason

# The release has finer hardship reasons than StatedReason; fold them in.
REASON_MAP: dict[str, StatedReason] = {
    "": StatedReason.NONE,
    "job_loss": StatedReason.JOB_LOSS,
    "ei_waiting": StatedReason.JOB_LOSS,  # waiting on Employment Insurance after losing work
    "reduced_income": StatedReason.REDUCED_INCOME,
    "illness": StatedReason.MEDICAL,
    "disability": StatedReason.MEDICAL,
    "bereavement": StatedReason.BEREAVEMENT,
    "rate_reset": StatedReason.OTHER,
    "separation": StatedReason.OTHER,
    "disaster_evacuation": StatedReason.OTHER,
    "other": StatedReason.OTHER,
}

# Label columns we don't extract. label_stated_delay_reason is why the payment is late in general
# (forgot, payroll_timing ...), not a hardship reason; StatedReason follows label_hardship_reason.
UNUSED = (
    "label_stated_delay_reason",
    "label_ptp_intent_strength",
    "label_dispute_type",
    "label_complaint",
    "label_vulnerability",
    "label_vulnerability_type",
    "label_insolvency_mention",
    "label_legal_threat_by_agent",
    "label_sentiment",
    "label_next_step",
    "label_income_amount_mentioned",
    "label_employer_mentioned",
    "label_protected_attribute_mentioned",
    "label_pii_in_text",
    "label_summary_gold",
    # transcripts only: QA checklist, timings, summaries
    "hardship_first_mention_sec",
    "ptp_agreed_sec",
    "objection_types",
    "qa*",
    "summary_gold_json",
    "policy_sections_relevant",
)

HOLDOUT_SHARE = 0.3  # held out from prompt tuning; the gate is checked on these only


def load_labels(path: Path | str) -> list[dict[str, Any]]:
    """One dict per labelled note/call: source_id, holdout, and each mapped field's gold value."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    id_col = "note_id" if "note_id" in rows[0] else "transcript_id"
    return [_row(r, r[id_col]) for r in rows]


def _row(r: dict[str, str], source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "holdout": is_holdout(source_id),
        "hardship_signal": HardshipSignal(r["label_hardship"]),
        "hardship_quote": r["label_hardship_evidence"] or None,
        "stated_reason": REASON_MAP[r["label_hardship_reason"]],
        "promise_intent": r["label_ptp_mentioned"] == "true",
        "promised_date": date.fromisoformat(r["label_ptp_date"]) if r["label_ptp_date"] else None,
        "promised_amount": Decimal(r["label_ptp_amount"]) if r["label_ptp_amount"] else None,
        "dispute": r["label_dispute"] == "true",
        "cease_request": r["label_cease_request"] == "true",
        "third_party_present": r["label_third_party_present"] == "true",
    }


def is_holdout(source_id: str) -> bool:
    """Stable split by id hash, so every run and every machine holds out the same labels."""
    return int(hashlib.sha256(source_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < HOLDOUT_SHARE
