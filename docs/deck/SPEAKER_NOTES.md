# Speaker notes: the Kept deck

One block per slide of `docs/deck/kept.pdf`: what to say (about 40 seconds), then a 20-second answer to the question
a judge is most likely to ask, with where the proof lives. Numbers come from `numbers.tex`; if a report changes, run
`make deck` and reread these notes against the new slide.

The deck explains the architecture and why each model was chosen before it shows the solution: Jane comes after the
decisions, as their result. The HTML version (`docs/deck/present/index.html`) follows the same order in 16 slides.

## 1 · Title
**Say:** Kept turns collections from chasing money on the bank's calendar into promises dated after the customer's
payday, released by a person.
**If asked "what's new here?":** timing, not channel. The bank's own randomised test shows channel and intensity
don't move promises; payday timing does.

## 2 · The problem
**Say:** five systems, five keys per person; promises dated by the calendar; more contact doesn't help; hardship gets
missed in free text.
**How do you know?** `docs/reports/evidence.md` §1 (the bank's four randomised cells) and §2 (+6.1 pts when due within two
days of payday, 95% CI 2.8–10.6), §2a (the peak is payday itself).

## 3 · System design
**Say:** four layers, one decision; nightly batch, live release; three places a person is in the loop.
**If asked "why four layers?":** each has its own failure mode and its own gate: identity recall, Ask benchmarks,
extraction F1, uplift Qini. A layer can be replaced without touching the others.

## 4 · Architecture
**Say:** a small stack that maps onto a bank's: lakehouse, WORM storage, model risk sign-off, on-prem inference. Every row carries a number we measured: DuckDB ran every workload to 20x to 40x today's data on 4 GB and never failed; uplift Qini 7.9 against 3.2 for a response model; SetFit reads all 760,594 notes in 63 s where the LLM would need about 29 days; the full Ask pipeline gets 86 of 93 right against 36 for one prompt.
**If asked "does it scale?":** 96,000 cards in about 85 s on one machine; the slow page we found (audit, 7.9 s) went to
0.04 s by moving filters into SQL.

## 5 · Data and identity
**Say:** exact links first, then probabilistic matching, uncertain pairs to a steward.
**How do you know?** 200 duplicates injected into the release: 198 found, none merged wrongly
(`docs/reports/identity_recall.md`).

## 6 · Decide and release
**Say:** seven checked steps; uplift not propensity; due on payday; people release.
**If asked "what if the model is wrong?":** it can't send anything. Hard stops run before it, the release rechecks on
fresh data, Red needs two people, and one switch reverts everyone to the bank's strategy.

## 7 · The Ask, as a graph
**Say:** every answer walks the graph and shows its path; the checks keep the local model on the rails.
**If asked "why a graph?":** each step is testable and traced; when the router slips (a dropped "calls", an "opened"
read as "open"), a deterministic check fixes it without retuning a prompt. Scores on the slide are from the local model.

## 8 · Text and voice
**Say:** redaction first, the local model reads, every value carries its quote; Whisper on our GPU.
**How do you know?** `docs/reports/extraction_gate.md` (every field F1 ≥ 0.80, hardship recall 1.00) and
`docs/reports/voice_wer.md` (9.4% vs the bank's 12.4%).

## 9 · Explainability
**Say:** the promise model's reliability curve sits near the diagonal; the case page shows every factor, both ways.
**How do you know?** `data/exports/reports/model_card.json`, from `scripts/model_card.py`, on promises the model never saw.

## 10 · Decisions
**Say:** each choice, the alternative we rejected, and the measured number that decided it. Uplift finds 122 extra payers per 1,000 contacts in the top 30% against 81 for a propensity score. Local models are not cheaper: hosted Haiku 5.5 would cost less than our two GPUs, so the reason is privacy and regulation. Certified metrics and the router take the Ask from 36 to 81 of 93 right; the drafts and judge add one more, and confident wrong answers fall from 33 to 7. Two rows are open: hybrid policy search loses to dense-only (MRR 0.640 against 0.747), and we have not switched yet.
**If asked "why local models only?":** customer words never leave the machine, which is what OSFI B-10 and E-23, PIPEDA and Quebec Law 25 ask of a third party; a quota can't stop a demo or a collector mid-shift (the free tier covers 500 requests a day, one night is 1,647 extractions). Not cost: `docs/reports/decisions.md` §B4.
**If asked "why Qwen3.8-27B, and why llama.cpp?":** we measured. The 12B model kept missing conventions; tracing showed
Ollama ran a 4k window under a 9k-token prompt. llama.cpp sets the window explicitly and runs two requests at once;
Qwen3.8-27B (Aug 2026, Apache 2.0) is the strongest open model that fits 16 GB at 3-bit, about 51 tokens a second.

## 11 · What we didn't ship
**Say:** a bigger model, a tuned uplift model and a leaky feature, each measured and rejected.
**How do you know?** `docs/reports/tuning.md` (40 candidates; the best lost beyond noise), `evidence.md` §3 (AUC 0.92 was leakage).

## 12 · Safe by construction
**Say:** 0 of 96,000 cards change when protected attributes are scrambled; contact ratio 0.87–1.00; hash-chained audit.
**If asked about the three fairness flags:** small groups or explained by recorded hardship; listed in the appendix.

## 13 · Jane
**Say:** one customer, end to end: pay due in 3 days, down 27%, answers after 18:00, shifts cut. Her card: a call in the
evening slot, $140 × 3 due on payday, Red because of hardship.
**How do you know?** It's case CS-2026-118204 in the guided demo; the reasons are the card's TreeSHAP drivers.

## 14 · The product
**Say:** one workspace for every role; the cited brief, the portfolio's A/B, the Ask's traced answers.
**Demo hand-off:** open the case page for Jane, then Portfolio, then ask a question in the Ask.

## 15 · Measured impact
**Say:** the bank's strategies overlap; timing adds 6.1 points; when Kept chooses the action, 61 more customers in every
1,000 pay within 14 days (interval 55–67).
**If asked "is the +61 real?":** it's an off-policy estimate (the bank chose the actions, so we model how it chose and
correct for it, paired on the same decisions); two estimators agree; the pilot's randomised cell turns it into a trial.

## 16 · Is it real?
**Say:** one table, every claim, the test, the interval, and a plain verdict. Walk the verdicts, not the numbers:
the payday effect holds three ways (randomised cases, due on payday against a day or three either side, the same
customer on and off payday) and fake paydays show nothing; our promise model ties the bank's and together they're
much better; uplift targeting on the bank's own randomisation is unproven, which is what the pilot is for; and the
business case pays back in 99.97% of simulated draws.
**If asked "did you beat the bank's model?":** not alone, and we don't claim to. A wider model on the same kinds of
inputs the bank's score uses matches it (0.697 against 0.702, interval −1.9 to +1.0 points). Ours exists the moment a
promise is made, about nine days before the bank's score, and averaged with it the two reach 0.763 (+6.1 points). The
bank keeps its model and gains ours.
**If asked "why is uplift so small?":** the bank's randomised test says contact intensity barely moves outcomes, so a
small uplift signal is the honest result. We tried X- and doubly robust learners: they win some actions and lose
others, so the gate kept the live model. That's why the lever is the due date.
**If asked "is it causal?":** the sharp comparison around payday, the same-customer comparison and the placebos are the
strongest checks short of a trial; a promise due on payday is kept 8 points more often than one due a day or three
either side, and a payday that isn't real shows nothing. The randomised due-date cell in the pilot is the trial.
**How do you know?** `docs/reports/evidence.md` §2, §2a, §4, §8, §9; `docs/reports/uplift_learners.md`;
`docs/reports/business_case.pdf` §8. One command reproduces each: `uv run python scripts/evidence_report.py`.

## 17 · Business value
**Say:** $1.55M base, by driver; ROI 2.4×; payback about 2.6 months. Across 20,000 draws of every assumption, 99.97%
pay back in year one; even with no payday effect at all it pays back.
**How do you know?** `docs/reports/business_case.pdf`; every assumption is listed there with its source.

## 18 · Value beyond dollars
**Say:** the guard metrics: caps, hours, hardship, fairness, complaints; complaints need a live cell.

## 19 · The pilot
**Say:** a 20% hold-out first, which shows the payday effect within two weeks at 80% power, then a permanent 5%; a
randomised due-date cell; a decision rule that ends it either way.

## 20 · How we built it
**Say:** four tracks, gated; every claim in `JUDGES.md` with the command that reproduces it.

## 21 · Close
**Say:** read Jane's line, then stop.

## Appendix (only when asked)
- **Roles:** who sees, masks and releases what.
- **Benchmarks:** the three suites on the local model, and what counts as right.
- **Tuning:** the champion against the tuned challenger on held-out decisions.
- **Drift and fairness:** the largest PSIs and the three flags, each reviewed.
- **Backend:** **Say:** DuckDB ran `roll_rate` to 40x today's data in 62 s on 4 GB; Polars ran out of memory at 10x, Postgres needs about 33 GB of disk, Spark is four times slower at 10x. Re-scoring hourly would change 3.1% of cards in a day; one feature definition and `kept parity` catch a wrong clock (1,325 of 56,000 cells) that the control never shows. `decisions.md` §A1 to A3.
- **Ask ablation:** **Say:** same model, one step added at a time. The router and certified metrics take 38.7% to 87.1%; reviewed templates add four answers; drafts, vote, linter and judge add one in 93 and take confident wrong answers from 8 to 7. `decisions.md` §B5.
- **Model choices:** **Say:** SetFit matches the LLM on hardship (F1 0.87 against 0.88) in 63 s instead of about 29 days; uplift ranking beats a response model on Qini (7.9 against 3.2), and the S-learner scored higher still, so a pilot decides; the wide promise model ranks better (AUC 0.697 against 0.625) and matches the bank's 0.702. `decisions.md` §B7, B9, B10.
- **Which local model:** **Say:** we ran Qwen3-14B, Qwen3-8B and Gemma 3 12B against the live Qwen3.8-27B. The live model answers 86 of 93 Ask questions with 7 confident wrong answers; the others get 71 to 75 with 13 to 17. Smaller models are faster, and Qwen3-8B matches the live one on transcript hardship (0.989 against 0.99), but only one model fits the 16 GB card, so one model serves all three jobs. Gemma's transcript extraction and briefs were not run. Ollama's default 4,096-token window cut our 9,743-token test prompt; with the context matched it is as fast as llama.cpp (78.3 against 79.4 tokens a second). Live red team: 41 of 43 attacks refused, 2 answered on a reviewed query, and the answer text was not stored. `decisions.md` §B1, B3, A5.
