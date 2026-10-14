"""Write numbers.tex: every number the deck shows, read from the reports and the warehouse, as LaTeX macros.

    uv run python docs/deck/build_numbers.py && (cd docs/deck && xelatex kept.tex && xelatex kept.tex)

No number in kept.tex is typed by hand: rerun this after a report changes and the slides follow.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from kept.app.portfolio import overview

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "data" / "exports" / "reports"


def load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((REPORTS / name).read_text())


def esc(s: object) -> str:
    return str(s).replace("%", r"\%").replace("$", r"\$").replace("&", r"\&").replace("_", r"\_")


def main() -> None:
    card, biz, fair, drift = load("model_card.json"), load("business_data.json"), load("fairness_data.json"), load("drift_data.json")
    inv = load("invariance_protected.json")
    p = overview(duckdb.connect(str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"), read_only=True))
    tot, roi, pay = biz["total"], biz["year1_roi"], biz["payback_months"]
    m: dict[str, str] = {
        # tonight's book
        "openCases": f"{p.cases:,}",
        "balanceAtRisk": f"\\${p.balance / 1e6:.1f}M",
        "expectedRecovery": f"\\${p.expected / 1e6:.2f}M",
        "actionableShare": f"{p.actionable / p.cases:.0%}".replace("%", r"\%"),
        "redCases": f"{p.red:,}",
        "hardStops": f"{p.hard_stops:,}",
        # business case
        "valueBase": f"\\${tot['Base'] / 1e6:.2f}M",
        "valueLow": f"\\${tot['Low'] / 1e6:.2f}M",
        "valueHigh": f"\\${tot['High'] / 1e6:.2f}M",
        "roiBase": f"{roi['Base']:.1f}",
        "paybackBase": f"{pay['Base']:.1f}",
        # models
        "promiseAuc": f"{card['promise']['auc']:.3f}",
        "promiseBrier": f"{card['promise']['brier']:.3f}",
        "promiseRows": f"{card['promise']['rows_test']:,}",
        "qiniAny": f"{card['uplift']['qini_any_contact']:.4f}",
        "qiniNoise": f"{card['uplift']['qini_noise']:.4f}",
        "upliftRows": f"{card['uplift']['rows_test']:,}",
        # governance
        "invarianceCards": f"{inv['cases']:,}",
        "invarianceDiffer": str(inv["cards_differ"]),
        "driftHeadline": esc(drift["headline"]),
        "fairnessAttributes": str(len(fair["attributes"])),
    }
    lines = [f"\\newcommand{{\\K{k}}}{{{v}}}" for k, v in m.items()]
    # value drivers, base case, in $k, largest first (for the value-tree bars)
    drivers = sorted(((k, v) for k, v in biz["scenarios"]["Base"].items() if not k.startswith("_") and v), key=lambda kv: -kv[1])
    lines.append("\\newcommand{\\Kdrivers}{" + ",".join(f"{v / 1e3:.0f}/{{{esc(k)}}}" for k, v in drivers) + "}")
    # the bank's A/B: kept rate and Wilson 95% interval per cell, in percent
    lines.append(
        "\\newcommand{\\Kab}{"
        + ",".join(f"{c.kept_rate * 100:.2f}/{c.kept_lo * 100:.2f}/{c.kept_hi * 100:.2f}/{{{esc(c.test_cell.replace('_', ' '))}}}/{c.promises}" for c in p.ab_test)
        + "}"
    )
    # promise model reliability: predicted/observed per bin, in percent
    lines.append(
        "\\newcommand{\\Kreliability}{"
        + " ".join(f"({r['predicted'] * 100:.1f},{r['observed'] * 100:.1f})" for r in card["promise"]["reliability"])
        + "}"
    )
    lines.append(
        "\\newcommand{\\Kreldots}{"
        + ",".join(f"{r['predicted'] * 100:.1f}/{r['observed'] * 100:.1f}" for r in card["promise"]["reliability"])
        + "}"
    )
    lines.append(
        "\\newcommand{\\Kimportance}{"
        + ",".join(f"{f['share'] * 100:.0f}/{{{esc(f['label'])}}}" for f in card["promise"]["importance"])
        + "}"
    )
    out = Path(__file__).with_name("numbers.tex")
    out.write_text("% written by build_numbers.py from data/exports/reports and the warehouse: don't edit by hand\n" + "\n".join(lines) + "\n")
    print(f"{len(lines)} macros -> {out}")


if __name__ == "__main__":
    main()
