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
**How do you know?** `docs/reports/evidence.md` §1 (the bank's four randomised cells) and §2 (+6.1 pts when due just
after payday, 95% CI 2.8–10.6).

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
**Say:** seven checked steps; uplift not propensity; dated after payday; people release.
**If asked "what if the model is wrong?":** it can't send anything. Hard stops run before it, the release rechecks on
fresh data, Red needs two people, and one switch reverts everyone to the bank's strategy.

## 7 · The Ask, as a graph
**Say:** every answer walks the graph and shows its path; the checks keep a 12B local model on the rails.
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

## 11 · What we didn't ship
**Say:** a bigger model, a tuned uplift model and a leaky feature, each measured and rejected.
**How do you know?** `docs/reports/tuning.md` (40 candidates; the best lost beyond noise), `evidence.md` §3 (AUC 0.92 was leakage).

## 12 · Safe by construction
**Say:** 0 of 96,000 cards change when protected attributes are scrambled; contact ratio 0.87–1.00; hash-chained audit.
**If asked about the three fairness flags:** small groups or explained by recorded hardship; listed in the appendix.

## 13 · Jane
**Say:** one customer, end to end: pay due in 3 days, down 27%, answers after 18:00, shifts cut. Her card: a call in the
evening slot, $140 × 3 due the day after payday, Red because of hardship.
**How do you know?** It's case CS-2026-118204 in the guided demo; the reasons are the card's TreeSHAP drivers.

## 14 · The product
**Say:** one workspace for every role; the cited brief, the portfolio's A/B, the Ask's traced answers.
**Demo hand-off:** open the case page for Jane, then Portfolio, then ask a question in the Ask.

## 15 · Measured impact
**Say:** the bank's strategies overlap; timing adds 6.1 points; off-policy, Kept's policy beats the bank's.
**If asked "is the 38.6–42.0% real?":** it's an estimate (actions weren't randomised); two estimators agree; the pilot's
randomised cell turns it into a trial.

## 16 · Business value
**Say:** $1.55M base, by driver; ROI 2.4×; payback about 2.6 months; the low case doesn't pay back in year one.
**How do you know?** `docs/reports/business_case.pdf`; every assumption is listed there with its source.

## 17 · Value beyond dollars
**Say:** the guard metrics: caps, hours, hardship, fairness, complaints; complaints need a live cell.

## 18 · The pilot
**Say:** a 20% hold-out, then 5%; a randomised due-date cell; a decision rule that ends it either way.

## 19 · How we built it
**Say:** four tracks, gated; every claim in `JUDGES.md` with the command that reproduces it.

## 20 · Close
**Say:** read Jane's line, then stop.

## Appendix (only when asked)
- **Roles:** who sees, masks and releases what.
- **Benchmarks:** the three suites on the local model, and what counts as right.
- **Tuning:** the champion against the tuned challenger on held-out decisions.
- **Drift and fairness:** the largest PSIs and the three flags, each reviewed.
