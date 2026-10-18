# ruff: noqa: E501
"""C3: fairness with and without the stand-in features (docs/reports/decisions.md). Pulls numbers that
scripts/fairness_report.py and scripts/invariance_test.py (protected, all) already wrote; runs nothing heavy.

    uv run python scripts/decision_C3.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DATA = Path(os.environ.get("KEPT_DATA", Path(__file__).resolve().parents[1] / "data"))
R = DATA / "exports" / "reports"


def main() -> None:
    fair = json.loads((R / "fairness_data.json").read_text())
    inv = {s: json.loads((R / f"invariance_{s}.json").read_text()) for s in ("protected", "all")}
    attrs = fair["attributes"]
    out = {
        "fairness": {
            "written": fair["written"],
            "cases": fair["cases"],
            "attributes": len(attrs),
            "flags": {o: sorted(a for a, v in attrs.items() if v["outcomes"][o]["flagged"]) for o in next(iter(attrs.values()))["outcomes"]},
            "too_few_events": {o: sorted(a for a, v in attrs.items() if v["outcomes"][o]["too_few_events"]) for o in next(iter(attrs.values()))["outcomes"]},
            "lowest_ratio": {o: min((v["outcomes"][o]["ratio"], a) for a, v in attrs.items()) for o in next(iter(attrs.values()))["outcomes"]},
            "any_contact_ratio_range": [min(v["outcomes"]["any contact action"]["ratio"] for v in attrs.values()),
                                        max(v["outcomes"]["any contact action"]["ratio"] for v in attrs.values())],
        },
        "invariance": {
            s: {k: d[k] for k in ("written", "cases", "cards_differ", "hardship_gained", "hardship_lost", "passed", "field_differences")}
            | {"scrambled_columns": sum(len(v) for v in d["scrambled"].values()), "scramble_reached_gold": d["scramble_reached_gold"]}
            for s, d in inv.items()
        },
        "all_changes_trace_to": "ei_deposit_flag (docs/reports/fairness_report.tex, invariance section; the cash-flow rule's protective use)",
        "sources": [str(R / n) for n in ("fairness_data.json", "invariance_protected.json", "invariance_all.json")],
    }
    (R / "decision_C3.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2)[:1800])


if __name__ == "__main__":
    main()
