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
**Say:** a small stack that maps onto a bank's: lakehouse, WORM storage, model risk sign-off, on-prem inference.
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
**Say:** each choice with the alternative we rejected and why.
**If asked "why local models only?":** customer words never leave the machine, there's no per-call cost, and a quota
can't stop a demo or a collector mid-shift.
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
promise is made, about nine days before the bank's score, and averaged with it the two reach 0.764 (+6.1 points). The
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
