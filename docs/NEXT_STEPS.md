# Next steps: Phase 6 (demo, video, deck, submission)

Updated 4 Oct, after G4. The build is done: every gate (G0–G4) passed, every track's code is on `main`,
and no PRs are open. What's left is the team's deliverables. Agents: read this file and `CLAUDE.md`
("Phase 6" section); the per-track phase rules no longer apply.

**Fixed times (IST, 4 Oct):** 19:00 extra benchmark questions released · **21:00 submission deadline**
(commits after 21:00 don't count).

---

## 1. Where we are

| Gate | Passed | Proof (on Akshat's machine, the demo machine) |
|---|---|---|
| G0 | 3 Oct | contracts, the four early providers on `main` |
| G1 | 3 Oct | real bronze + silver; crosswalk v1: 3,840,513 keys → **1,052,300 golden IDs** |
| G2 | 3 Oct | gold with text + cash-flow hardship, gate PASS, 96,000 cases in Feast |
| G3 | 4 Oct | `kept score`: a card for every open case; **a new note flips hardship** on real `kept serve`; parity PASS |
| G4 | 4 Oct | full `kept nightly` end to end (incl. match, ~7 min); benchmark dev 83% accuracy / 100% refusal recall; fairness report; CI green |

Numbers worth quoting (all from real runs): match precision **99.3%** on 300 human-reviewed pairs;
785,594 notes and calls redacted with **0 leaks** in a full scan; text hardship gate on held-out labels
recall 0.98 (notes) / 0.99 (calls); uplift vs the current strategy: call Qini 0.0073 vs 0.0017;
parity 0 of 56,000 cells; 96,000 cards: Red 38,115 · Green 31,539 · Amber 3,288 · no action 23,058;
no protected group treated materially differently (fairness ratios 0.93–1.00 on contact actions).

## 2. How we work now (strict)

- **`main` is the only long-lived branch.** Don't commit to `track-a/b/c/d` any more. Keep them: they are
  the history of the work (team work is 15% of the score).
- **Every change gets its own short branch off `main`, named by purpose:** `docs/demo-script`,
  `docs/deck`, `fix/<thing>`, `bench/answers`. PR to `main`, CI green, **merge commit** (no squash or
  rebase), the owner merges. Pull `main` before you branch.
- **Keep building, keep `main` demo-ready.** New features and visual work (data viz, a better card) are welcome
  until the deadline. Each is a small PR with tests and lint green; nothing may break `kept nightly`, `kept serve`
  or the demo script.
- **After 19:00 nothing touches the Ask** (`kept/ask/**`, its prompts, the allow-list): the extra
  questions are answered by the system as it is (TEAM_PLAN Q13). Don't edit answers by hand.
- **Nothing is pushed after 21:00.**
- Data never goes into git (K4). Hand-over files go through the team Drive.
- One `KEPT_HOLDOUT_SALT` for everyone (the demo machine uses `.env.example`'s value). Commit messages:
  one plain line, no AI attribution trailers.

## 3. Who does what (in this order)

| # | What | Owner | Done when |
|---|---|---|---|
| 1 | **Video script** `docs/demo_script.md`: the §7 scenario of TEAM_PLAN in ≤ 5 minutes, with the case ids, the note text and who clicks what | Satvik | merged |
| 2 | **Demo dry run ×2 on Akshat's machine** (commands below); fix only demo blockers | all, Akshat drives the machine | two clean runs |
| 3 | **Record the video** (≤ 5 min, real data), unlisted YouTube or Drive link | Satvik records, others on standby | link shared |
| 4 | **Deck** (≤ 10 slides, PDF) from `docs/deck_outline.md`; each owner sends their slide's numbers/screenshot | Akshat assembles | PDF ready |
| 5 | **Final architecture diagram** `docs/architecture.{png,pdf}` (numbers refreshed) | Akshat | merged |
| 6 | **README final**: how to run (D), what changed from the design (each owner's lines), AI tools used (each owner) | Shreyas + everyone | merged |
| 7 | **Repo private + organisers added as collaborators** | Akshat (or the repo owner) | done |
| 8 | **19:00–20:30: `kept benchmark`** on the full set incl. the extra questions → answers CSV (release template) committed | Abhishek | CSV on `main` |
| 9 | **Submit the form before 21:00**: repo, diagram, contract, quality report, answers CSV, video link, deck | Akshat | submitted |

## 4. Submission checklist (Build Phase instructions, "What to submit")

| # | Deliverable | Where | Status |
|---|---|---|---|
| 1 | Code repo: private, organisers added, README (run / what changed / AI tools) | GitHub | README: run steps + C's lines in; others' lines and private + collaborators pending |
| 2 | Architecture diagram, PDF or PNG | `docs/architecture.png`, `.pdf` | draft in; final refresh pending |
| 3 | Data contract for the golden C360 | `contracts/c360_customer.odcs.yaml` | frozen at G3 |
| 4 | Data quality report | `docs/quality_report.md` | in |
| 5 | Benchmark answers CSV (template columns `question_id, answer, sql_or_sources, refused`) | from `kept benchmark` | 19:00 run |
| 6 | Demo video, ≤ 5 min, real data | YouTube/Drive link | pending |
| 7 | Pitch deck, ≤ 10 slides, PDF | link / file in the form | pending |

## 5. The demo machine (Akshat's)

```bash
git checkout main && git pull --ff-only && uv sync --all-extras --inexact
set -a; . ./.env; set +a                     # KEPT_HOLDOUT_SALT, KEPT_TEXT_LLM_MODEL, MLflow (sqlite)
uv run kept nightly                          # ~7 min: land, silver, match, gold, gate, extract, features, parity, score
curl -s localhost:11434/api/generate -d '{"model":"gemma3:12b-it-qat","keep_alive":-1}'  # keep Gemma loaded (live note ~5 s)
uv run kept serve                            # API on :8000 (real services)
cd web && pnpm dev                           # app on http://localhost:3000 (use localhost, not 127.0.0.1)
```
Live-note demo case used in the G3 check: `CS-2026-820205` (agent `AG-8365`): "Send an app reminder"
(push, Green) → after the note "spoke w/ cust, lost shifts at the plant since Aug, can only pay 50 on the 15th"
→ "Call to start a hardship review" (Red, specialist banner). Remove test notes afterwards
(`delete from text.extractions where source_id like 'N-LIVE-%'`).

## 6. Open team calls (settle today)

- One `KEPT_HOLDOUT_SALT` value on every machine.
- The Red share (40% of cards: hardship review for protected cases). Explain it in the deck, or add a rule
  for customers already on a hardship plan (D's question).
- Benchmark "gold vs correct" on BQ-017 / BQ-035 / BQ-003 (B): we compute from clean data.
- Ask: per-agent row filter for lookups (B).
