# For judges: Kept in 15 minutes

Every claim we make, the file that shows it, and the command that reproduces it. Nothing here asks you to trust us.

## 1. The problem (2 minutes)

[`docs/story.md`](docs/story.md): why collections matters to the bank, the customer and the regulator; Maple Bank's own
numbers (half of new cases roll within 30 days, and rolling is the only road to a charge-off); one customer, Jane, whose
promise breaks because it falls due before payday; and the four root causes, each mapped to the layer that fixes it.

## 2. See it work (5 minutes)

```bash
make setup-all && make web-setup   # libraries, then the web app
uv run kept serve --demo          # twelve in-memory cases, no warehouse, no network
cd web && pnpm dev                # http://localhost:3000
```

Open a case: the card shows the action, three plain-English reasons and the release tier. Add the note *"lost shifts at
the plant since Aug, can only pay 50 on the 15th"*: the card turns to a hardship review, citing those exact words. Release
it as a specialist, then as a team lead (Red needs two people), and read the audit trail. On the real data, a case with a
recorded call also has a **Calls** panel: the recording and its transcript, with the hardship quote highlighted.

## 3. Check the claims

| Claim | Where it's shown | Reproduce |
|---|---|---|
| Dating a promise to just after payday: **+6.1 pts** of the promised money paid (95% CI 2.8–10.6), measured on the bank's randomised cases | [`docs/reports/evidence.md`](docs/reports/evidence.md) §2 | `uv run python scripts/evidence_report.py` |
| The bank's own A/B cells can't tell its strategies apart | evidence §1 | same |
| Kept's contact policy, off-policy: **38.6–42.0%** paid in 14 days vs the bank strategy's **32.4–32.5%** on the same decisions | evidence §4 | same |
| A leaky feature found and removed (promise AUC 0.92 → 0.63), and the leak-free model combined with the bank's score beats the bank's alone (0.728 vs 0.702) | evidence §3, §6 | same |
| Every extracted field passes F1 ≥ 0.80 on held-out notes and calls; hardship recall **1.00** | [`docs/reports/extraction_gate.md`](docs/reports/extraction_gate.md) | `uv run python scripts/eval_extraction.py --source transcripts --split holdout` |
| Whisper on 2,000 calls: **9.4%** word error rate vs the bank's speech-to-text at 12.4%, even across noise and accents | [`docs/reports/voice_wer.md`](docs/reports/voice_wer.md) | `uv run python scripts/voice_wer.py --report-only` |
| One person per customer: precision **99.3%** (300 links by hand), recall **99%** (198 of 200 planted duplicates, no wrong merges) | [`QUALITY_REPORT.pdf`](QUALITY_REPORT.pdf), [`docs/reports/identity_recall.md`](docs/reports/identity_recall.md) | `uv run python scripts/identity_injection.py` |
| Ask, on a local model only (Qwen3.8-27B): released dev split **21 of 21**; our stress suite **38 of 42**; an unseen drill **27 of 30**; refusals all right, every miss explained | [`docs/reports/ask_accuracy.md`](docs/reports/ask_accuracy.md) | `uv run python scripts/bench_run.py benchmarks/drill_questions.csv --gold benchmarks/drill_gold.csv --out data/exports/reports/drill_answers.csv` |
| Protected attributes never change a decision: scramble all of them, rebuild, rescore, **0 of 96,000** cards change | [`docs/reports/fairness_report.pdf`](docs/reports/fairness_report.pdf) §5 | `uv run python scripts/invariance_test.py protected` |
| Contact is even across groups: any-contact ratio **0.87–1.00** on every protected attribute; 3 small flags, reviewed ([separated customers](docs/reports/separated_review.md)) | fairness report | `uv run python scripts/fairness_report.py` |
| No decision record can be edited unnoticed: every audit event is hash-chained | `src/kept/common/audit.py` | `uv run kept audit-verify` |
| A worse model can't go live: when payroll features didn't help, the champion/challenger gate kept the current model | [`docs/reports/drift_report.pdf`](docs/reports/drift_report.pdf) | `uv run kept train` |
| The models, measured on held-out data: promise AUC, calibration by score bin, uplift Qini against random rankings, the strongest inputs | [`docs/reports/model_card.md`](docs/reports/model_card.md) | `uv run python scripts/model_card.py` |
| What changed from the design, and the evidence behind each change | [`docs/reports/design_changes.md`](docs/reports/design_changes.md) | — |
| Business case: **$1.55M a year** base (low $0.44M, high $4.27M), every assumption named and swung | [`docs/reports/business_case.pdf`](docs/reports/business_case.pdf) | `uv run python scripts/business_case.py` |

## 4. What we know isn't solved

- **The payday effect is measured, not yet trialled.** Due dates weren't randomised, so the interval is wide. The pilot
  plan holds out 5% on the old strategy and adds a randomised due-date cell.
- **Payday is known for about 1 customer in 4** from deposit data. The pay page asks the rest; agents already hear it on
  calls (41% of open customers have stated one).
- **The uplift signal is small** (call Qini 0.0073). Payroll features added to training didn't beat the champion.
- **Three fairness flags remain** (calls by gender and by marital status, hardship reviews by marital status), all on
  small numbers or explained by recorded hardship; a minimum-events rule marks four more as too few to judge.
- **Sign-in is a demo persona picker.** The API enforces every role rule itself (case scope, aggregates only for
  analysts, masking for everyone but compliance), but it takes the caller's role from the request. In production the
  API sits behind the bank's single sign-on (OIDC) and reads the user and role from the signed token.
