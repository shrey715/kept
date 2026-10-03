"""Build the policy search index (LanceDB) from data/policy/ and try a few questions.
Usage: uv run python scripts/build_policy_index.py   (index: $KEPT_LANCEDB_DIR, default data/policy/lancedb)
"""

from __future__ import annotations

import csv
import os
import shutil
from datetime import date
from pathlib import Path

from kept.ask.policy import PolicyIndex, build_policy_index

DOCS = Path("data/policy")
INDEX = Path(os.environ.get("KEPT_LANCEDB_DIR", "data/policy/lancedb"))
QUESTIONS = [
    "How many call attempts can we make on a mid-stage account in a week?",
    "Does the National Do Not Call List stop collection calls?",
    "A customer says their hours were cut at work. What must the agent do before asking for payment?",
    "How long does the 3-month reduced payment programme last, and what share of the payment is reduced?",
    "What is the grace period before a promise to pay is considered broken?",
    "Why did outbound call volume drop on 23-24 September 2026?",
    "Can we sue a customer who missed two payments?",
]


def main() -> None:
    with open("data/raw/reference_documents.csv", encoding="utf-8", newline="") as f:
        docs = list(csv.DictReader(f))
    ops = Path("data/raw/ops_events.csv")
    events = list(csv.DictReader(ops.open(encoding="utf-8", newline=""))) if ops.exists() else []
    shutil.rmtree(INDEX, ignore_errors=True)  # rebuild from scratch: the documents are the source of truth
    index = PolicyIndex(INDEX)
    print(f"{build_policy_index(index, docs, DOCS, events)} chunks from {len(docs)} documents -> {INDEX}")
    for q in QUESTIONS:
        print(f"\n{q}")
        for c in index.search(q, as_of=date(2026, 9, 28), k=3):
            print(f"  {c.document_id} {c.section}: {c.snippet[:110]!r}")


if __name__ == "__main__":
    main()
