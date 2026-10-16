"""The decision timeline for docs/reports/decisions.md: each major design decision on the day it landed, with the
measured number that triggered it (from git history and the reports named in the register).

    uv run python scripts/decision_timeline.py      # -> docs/reports/figures/dec_timeline.png
"""

from __future__ import annotations

from datetime import date

from reportlib import BLUE, INK, KEPT, MUTED, plt, save, style, tidy

# (day, decision, the number that triggered it, kept or switched)
DECISIONS = [
    (date(2026, 10, 3), "T-learner uplift on randomly assigned cases", "Qini against random rankings", "kept"),
    (date(2026, 10, 3), "Exact keys, then Splink, then a steward", "precision 99.3%, recall 198/200", "kept"),
    (date(2026, 10, 4), "Splink trained on a 1-in-5 sample", "all 3.84M keys ran out of 30 GB", "switched"),
    (date(2026, 10, 4), "Champion/challenger gate on Qini", "tuned model lost, 0.0029 vs 0.0073", "kept"),
    (date(2026, 10, 9), "Leaky promise feature dropped", "AUC 0.92 was amount_ratio; honest 0.63", "switched"),
    (date(2026, 10, 10), "Whisper large-v3-turbo on calls", "WER 9.4% vs the bank's 12.4%", "kept"),
    (date(2026, 10, 12), "Schema-constrained extraction replies", "malformed replies 152 to 0", "switched"),
    (date(2026, 10, 12), "Hybrid policy search (BM25 + bge-m3)", "French and paraphrased questions", "switched"),
    (date(2026, 10, 14), "Local models only, on llama.cpp", "Ollama cut the prompt to 4,096 tokens", "switched"),
    (date(2026, 10, 15), "Qwen3.8-27B for every LLM call", "drill 27/30 vs 22/30 on Gemma 3 12B", "switched"),
    (date(2026, 10, 15), "Promises due on payday, not the day after", "+7.7 pts kept vs 1-3 days before", "switched"),
    (date(2026, 10, 15), "No new hardship review on a running plan", "Red cards 38,187 to 33,646", "switched"),
    (date(2026, 10, 15), "Calls booked into hours with capacity", "56% of calls over capacity to 0", "switched"),
]


def main() -> None:
    style()
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    days = sorted({d for d, *_ in DECISIONS})
    x0 = days[0].toordinal()
    seen: dict[date, int] = {}
    for i, (d, what, why, status) in enumerate(DECISIONS):
        k = seen.get(d, 0)
        seen[d] = k + 1
        x = d.toordinal() - x0
        y = len(DECISIONS) - i
        ax.scatter([x], [y], s=46, color=KEPT if status == "switched" else BLUE, zorder=3)
        ax.text(x + 0.25, y + 0.12, what, fontsize=7.6, color=INK, va="center")
        ax.text(x + 0.25, y - 0.32, why, fontsize=6.6, color=MUTED, va="center")
    ax.set_yticks([])
    ticks = [d.toordinal() - x0 for d in days]
    ax.set_xticks(ticks, [d.strftime("%-d Oct") for d in days], fontsize=7.5)
    ax.set_xlim(-0.5, (days[-1].toordinal() - x0) + 6.5)
    ax.set_ylim(0.2, len(DECISIONS) + 0.9)
    ax.scatter([], [], color=BLUE, label="kept after the test")
    ax.scatter([], [], color=KEPT, label="switched on the evidence")
    ax.legend(loc="lower left", frameon=False, fontsize=7)
    ax.set_title("Design decisions, and the number behind each", loc="left")
    tidy(ax, "x")
    save(fig, "dec_timeline")


if __name__ == "__main__":
    main()
