# Ask accuracy: released, stress and unseen

Three question sets, run through the live system (`kept serve`, the Bench page's route) by `scripts/bench_run.py`, graded
automatically: a table answer needs every gold row within the tolerance; a policy answer needs the gold document cited and
every gold number in the text; a refusal must refuse. Run on 14 October on **local models only**: Qwen3.8-27B (3-bit,
llama.cpp, two 16k-token slots) for every model call, no hosted API and no keys.

| Question set | Who wrote it | Right | Before (Gemma 3 12B on Ollama, same day) |
|---|---|---:|---:|
| Released dev split | the organisers | **21 of 21** | 18 of 21 |
| Stress suite (`benchmarks/stress_*`) | us, aimed at the release's traps | **38 of 42 (90%)** | 30 of 42 |
| Unseen drill (`benchmarks/drill_*`) | us, never tuned on | **27 of 30 (90%)** | 22 of 30 |

Refusals: every one right in all three sets (protected grounds, bulk personal data, write actions, out of scope). Median
answer time about 6 seconds. We tuned on the released and stress sets only; the drill was held out to check that the
changes generalise, and it moved with them (22 to 27).

## What changed, and why it moved the numbers

**The runtime was cutting the prompt.** Tracing the 12B model's misses showed Ollama running every call in a 4,096-token
window while the lookup prompt (schema, conventions, worked examples) is about 9,000 tokens: the model never saw most of
the conventions. llama.cpp sets the window explicitly (16,384 per slot) and runs two requests at once.

**The model.** Qwen3.8-27B (August 2026, Apache 2.0) is the strongest open model that fits the 16 GB GPU, at 3-bit with an
8-bit KV cache, about 51 tokens a second. Gemma 4 26B was rejected earlier (24 s a note, runaway replies).

**The harness: deterministic checks around the model**, each traced on the answer:
- Reviewed SQL first: templates for contact events (calls, disputes, complaints by day or site), QA scores, open cases and
  overdraft past due, each checked row for row against the gold. A period comparison ("compared with the 8 days before")
  runs the reviewed query once per period.
- Intent checks: a bucket the question names becomes a filter; two month-end points set the roll-rate cohort date;
  "today" on a snapshot metric pins the as-of date; "each day" groups by day; a route naming no certified metric becomes a
  lookup instead of failing.
- A convention linter on every SQL draft (calls need `channel = 'call'`, disputes are counted in contact history, open cases
  have no outcome, breakdowns need GROUP BY, dates must be the ones worked out from the question, compared periods come back
  one row each): a draft that breaks a rule goes back to the model with the reason, like a linter's error.
- `CURRENT_DATE` and `now()` are pinned to the snapshot date; bare table names get their schema.
- Drafts that disagree escalate from three to five, then the model compares the competing results and picks one, instead of
  refusing.

## What's still wrong, and why

**Stress suite (4):**
- KS-009, KS-014: our own gold counts insolvency and deceased holds in the cure rate; the bank's certified definition
  excludes them (`metric_definitions.csv`) and the Ask follows the bank. We keep it that way.
- KS-021: the answer is right ("40% for 2 months, v4.1"); the gold also quotes the new terms, and the grader wants every
  number.
- KS-022: cites the hardship policy instead of the vulnerable-customer script (scripts rank below policies). The answer
  itself is right.

**Unseen drill (3):**
- DR-024 (in French): the answer is right, *"entre 07 h et 21 h"*; the grader looks for the digits of "07:00".
- DR-016: the hardship-rate metric doesn't expose `test_cell`, so it can't split the randomised cells.
- DR-007: attempts per case divided by every open case, not by the cases contacted that month.

## Reproduce

```bash
make llm                                  # Qwen3.8-27B on llama.cpp (:8081)
make serve                                # then:
uv run python scripts/bench_run.py data/benchmark/benchmark_questions.csv --gold data/benchmark/benchmark_dev_answers.csv --out data/exports/reports/released_answers.csv
uv run python scripts/bench_run.py benchmarks/stress_questions.csv --gold benchmarks/stress_gold.csv --out data/exports/reports/stress_answers.csv
uv run python scripts/bench_run.py benchmarks/drill_questions.csv --gold benchmarks/drill_gold.csv --out data/exports/reports/drill_answers.csv
```

The gold for the stress suite and the drill is built from the raw release by `benchmarks/build_stress_suite.py` and
`benchmarks/build_drill.py`, independent of the Ask.
