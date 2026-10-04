# ruff: noqa: E501  (chart labels)
"""Shared bits for the reports in docs/reports/: one chart style, and the compile step.

The reports are hand-written LaTeX (docs/reports/<name>.tex, house style kept-report.sty). The report scripts only
query the data, cache the numbers in data/exports/reports/ and draw the figures into docs/reports/figures/.
    uv run python scripts/reportlib.py            # compile every report (QUALITY_REPORT.pdf goes to the repo root)
Charts: Open Sans, one blue for a single series, ink text, a faint grid, value labels at the bar tips.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "docs" / "reports"
FIG = REPORTS / "figures"
BUILD = REPO / "data" / "exports" / "reports"
HEADER = REPORTS / "report_header.tex"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"  # categorical slots 1-3 and the red pole
KEPT = "#c8102e"


def style() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.edgecolor": GRID,
            "axes.labelcolor": MUTED,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "xtick.color": MUTED,
            "ytick.color": INK,
            "text.color": INK,
            "font.family": ["Open Sans", "DejaVu Sans"],  # DejaVu covers arrows and math signs
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def tidy(ax: plt.Axes, axis: str = "x") -> None:
    ax.grid(axis=axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["left" if axis == "x" else "bottom"].set_visible(axis != "x")


def save(fig: plt.Figure, name: str) -> str:
    """Save under docs/reports/figures/ and return the Markdown image path (relative to the repo root)."""
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)
    return f"docs/reports/figures/{name}.png"


def hbar(
    labels: list[str],
    values: list[float],
    name: str,
    *,
    fmt: str = "{:,.0f}",
    xlabel: str = "",
    title: str = "",
    log: bool = False,
    colors: list[str] | None = None,
    ref: tuple[float, str] | None = None,
) -> str:
    """Horizontal bars, largest-first order as given, value at each tip. `ref` draws a labelled vertical line."""
    style()
    fig, ax = plt.subplots(figsize=(7.2, 0.3 * len(labels) + 1.0))
    y = list(range(len(labels)))[::-1]
    ax.barh(y, values, height=0.55, color=colors or BLUE)
    span = max(values) if values else 1
    for yi, v in zip(y, values, strict=True):
        ax.text(v * 1.04 if log else v + span * 0.01, yi, fmt.format(v), va="center", fontsize=8)
    ax.set_yticks(y, labels)
    if log:
        ax.set_xscale("log")
    if ref:
        ax.axvline(ref[0], color=INK, linewidth=1, linestyle="--")
        ax.text(ref[0], len(labels) - 0.4, f" {ref[1]}", fontsize=8, va="bottom")
    ax.set_xlim(right=span * (5 if log else 1.2))
    ax.set_xlabel(xlabel)
    if title:
        ax.set_title(title, loc="left")
    tidy(ax)
    return save(fig, name)


REPORTS_TEX = ("quality_report", "business_case", "fairness_report", "drift_report", "benchmark_report")


def compile_report(name: str) -> Path:
    """docs/reports/<name>.tex (hand-written, kept-report.sty) -> PDF via XeLaTeX, run twice for references.
    The quality report is deliverable 4 and goes to the repo root as QUALITY_REPORT.pdf."""
    with tempfile.TemporaryDirectory() as out:
        for _ in range(2):
            subprocess.run(
                ["xelatex", "-interaction=nonstopmode", f"-output-directory={out}", f"{name}.tex"],
                cwd=REPORTS,
                capture_output=True,
            )
        built = Path(out) / f"{name}.pdf"
        if not built.exists():
            log = Path(out) / f"{name}.log"
            raise RuntimeError(
                "XeLaTeX produced no PDF:\n" + (log.read_text()[-3000:] if log.exists() else "")
            )
        dest = REPO / "QUALITY_REPORT.pdf" if name == "quality_report" else REPORTS / f"{name}.pdf"
        shutil.copy(built, dest)
    return dest


if __name__ == "__main__":  # uv run python scripts/reportlib.py [name ...]: compile the hand-written reports
    import sys

    for n in sys.argv[1:] or REPORTS_TEX:
        print(compile_report(n))
