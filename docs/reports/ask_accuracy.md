# Ask accuracy: released, stress and unseen

Three question sets, run through the live system (`kept serve`, the Bench page's route) by `scripts/bench_run.py`, graded
automatically: a table answer needs every gold row within the tolerance; a policy answer needs the gold document cited and
every gold number in the text; a refusal must refuse. Run on 12 October, after the hybrid search (#154) and the stress fixes (#158).

| Question set | Who wrote it | Right | |
|---|---|---:|---|
| Released dev split | the organisers | **21 of 21** | no regressions from this round's changes |
| Stress suite (`benchmarks/stress_*`) | us, aimed at the release's traps | **35 of 42 (83%)** | was 33 of 42 before this round |
| Unseen drill (`benchmarks/drill_*`) | us, never tuned on | **26 of 30 (87%)** | 16 data, 8 policy (one in French), 6 refusals |

Refusals: every one right in all three sets (protected grounds, bulk personal data, write actions, out of scope).

## What's still wrong, and why

**Stress suite (7):**
- KS-009, KS-014: our own gold counts insolvency and deceased holds in the cure rate; the bank's certified definition
  excludes them (`metric_definitions.csv`) and the Ask follows the bank. We keep it that way.
- KS-013: quarter-end snapshots double-count accounts (three date formats in the release).
- KS-018: the 180+ overdraft bucket over-counts accounts with no days past due.
- KS-020: the denominator counts customers with any payroll deposit, not payroll-flagged chequing accounts.
- KS-021: the answer is right ("40% for 2 months, v4.1"); the gold also quotes the new terms, and the grader wants every
  number.
- KS-022: cites the hardship policy instead of the vulnerable-customer script (scripts rank below policies).

**Unseen drill (4):**
- DR-024 (in French): the answer is right, *"entre 07 h et 21 h"*; the grader looks for the digits of "07:00".
- DR-014: "total promised" was routed to the collected-amount metric. A real routing miss.
- DR-016: the hardship-rate metric doesn't expose `test_cell` yet (the cure rate does since #158).
- DR-007: attempts per case divided by every open case, not by the cases contacted that month.

## Reproduce

```bash
uv run kept serve                         # then:
uv run python scripts/bench_run.py data/benchmark/benchmark_questions.csv --gold data/benchmark/benchmark_dev_answers.csv --out data/exports/reports/released_answers.csv
uv run python scripts/bench_run.py benchmarks/stress_questions.csv --gold benchmarks/stress_gold.csv --out data/exports/reports/stress_answers.csv
uv run python scripts/bench_run.py benchmarks/drill_questions.csv --gold benchmarks/drill_gold.csv --out data/exports/reports/drill_answers.csv
```

The gold for the stress suite and the drill is built from the raw release by `benchmarks/build_stress_suite.py` and
`benchmarks/build_drill.py`, independent of the Ask.
