# Deck issues: make the slides deeper

The round-1 feedback was that presentations were generic and thin on the problem's background. This tracker lists
what each slide should add: system design, architecture, the reasoning behind each decision, and the business value
with its working. Every number must come from a report in the repo (the "Source" line), and every claim should
survive a judge asking "how do you know?".

Status: `[ ]` open · `[~]` drafted on the deck · `[x]` reviewed in a dress rehearsal. One owner per issue.

**The deck is now LaTeX** (`docs/deck/kept.tex`, Beamer, XeLaTeX): `make deck` reads every number from the reports into
`numbers.tex` and builds `docs/deck/kept.pdf` (21 slides). DK-01 to DK-17 are drafted there (speaker notes: `docs/deck/SPEAKER_NOTES.md`; appendix: roles, benchmarks,
tuning, drift and fairness). Left: the video link (DK-18: the team's URL), and a dress-rehearsal review of every slide.

## System design

- [~] **DK-01 · One end-to-end system diagram (new slide, after the problem)**
  - Four layers left to right: data and identity → Ask → text and voice → decide and release. One arrow per data
    flow, labelled with what crosses it (golden ID, feature vector, extraction with quote, card, proposal).
  - Mark what runs nightly (`kept nightly`: dbt build, features, score) and what runs live (the API, a release recheck).
  - Mark where a person is in the loop (release, steward review, cease confirmation).
  - Source: `src/kept/cli.py` (nightly steps), `docs/design/SharpeShooters_SystemDesign.pdf`.
- [~] **DK-02 · Data and identity slide: show the matching, not just the result**
  - 31 source tables, 5 systems, 5 keys per person → one golden ID: exact links first, then probabilistic matching
    (Splink), uncertain pairs to a steward.
  - Numbers: identity recall 99% (198 of 200 injected duplicates found, no wrong merges); 36,279 pairs waiting for
    review, oldest first, paged.
  - Source: `docs/reports/identity_recall.md`, `QUALITY_REPORT.pdf`.
- [~] **DK-03 · The Ask as a graph (LangGraph), with one traced answer**
  - The nodes: safety rules → scope → route → policy search | certified metric | voted SQL lookup → grounded
    narration. Show a real trace from the app ("Route: metric cost_per_rpc · SQL guard: allowed · 1 row ·
    narration checked").
  - Why each guard exists: protected attributes refused before any model call; the SQL guard (read-only, allowed
    tables and columns); three SQL drafts and a majority vote; every number in the answer must be in the rows.
  - Numbers: released 21/21, stress 34–35/42, unseen drill 26/30.
  - Source: `src/kept/ask/graph.py`, `docs/reports/ask_accuracy.md`.
- [~] **DK-04 · Text and voice slide: the pipeline and the privacy boundary**
  - Redaction first (Presidio), then the local model (Gemma 3 12B, schema-constrained JSON), every value with the exact
    quote it rests on. Voice: Whisper on this machine, word error rate 9.4% against the bank's 12.4%.
  - Draw the privacy boundary: every model runs on this machine; nothing leaves it.
  - Numbers: every extraction field passes F1 ≥ 0.80; hardship recall 1.00; 1,172 of 1,172 recorded calls read.
  - Source: `docs/reports/extraction_gate.md`, `docs/reports/voice_wer.md`.
- [~] **DK-05 · Decide slide: from features to a released action, step by step**
  - Features (dbt, point in time; Feast online store) → uplift per action (LightGBM T-learner) → payday sizing within
    spare cash → hard stops and permissions → tier (Green / Amber / Red) → a person releases → the gate rechecks on
    fresh data.
  - Show one card's full "why" (the TreeSHAP drivers chart on the case page), not just the top three reasons.
  - Source: `src/kept/nba/engine.py`, `src/kept/nba/release.py`, the case page.

## Architecture

- [~] **DK-06 · Architecture slide: the stack and why it fits a bank**
  - DuckDB warehouse (one writer, columnar, file on disk), the audit log in its own DuckDB file, append-only and
    hash-chained (`kept audit-verify`); FastAPI; Next.js workspace; MLflow for model runs; one GPU box for local models.
  - Production mapping: what each piece becomes at a bank (warehouse → the bank's lakehouse; DuckDB audit → WORM
    storage; personas → SSO). Keep it honest: this is a demo stack built to be swapped, not a production claim.
- [~] **DK-07 · Performance and scale numbers**
  - 96,000 cards scored in about 85 s; portfolio overview in about 40 ms; audit page 7.9 s → 0.04 s after moving
    filters into SQL; steward queue paged (36,279 pairs).
  - Source: PR descriptions #167, #168, #171; `kept score` output.
- [~] **DK-08 · Governance architecture: who can see and do what**
  - Role table (agent, specialist, team lead, compliance, analyst, steward): what each sees, masks and releases.
    Analysts get aggregates only; names masked for everyone but compliance.
  - Tamper evidence: one edited audit record breaks the chain; concurrent writes can't fork it (lock + test).
  - Source: `src/kept/governance/access.py`, `src/kept/common/audit.py`.

## Decision reasoning (one line of "why" per choice, with the alternative we rejected)

- [~] **DK-09 · A "decisions we made" slide (ADR style)**
  - Uplift, not propensity: contact whoever a contact changes, not whoever would pay anyway.
  - Timing over channel: the bank's own A/B shows strategies keep promises at the same rate (66.4% vs 66.4–66.7%,
    every 95% interval overlaps), while due-after-payday adds 6.1 points.
  - Local models only (since 14 Oct): no hosted API and no keys, so nothing leaves the machine and no quota can stop a demo.
  - Certified metrics before free SQL: reviewed definitions answer most questions with no model-written SQL.
  - Two-person release for Red: hardship decisions are never one person's or a model's.
  - Schema-constrained decoding: 152 of 1,172 call replies were malformed before; 0 after.
  - Source: `docs/reports/evidence.md`, `docs/reports/extraction_gate.md`, the Portfolio page's A/B panel.
- [~] **DK-10 · "What we tried and didn't ship" slide (judges trust this)**
  - Gemma 4 26B as the text model: too slow on a 16 GB GPU (about 24 s a note against 3 s) and not more accurate.
  - A 40-candidate hyperparameter search for the uplift model: the best was worse than the champion on held-out
    decisions, so the gate kept the champion.
  - Payroll features in training: didn't beat the champion. A leaky promise feature: found and dropped (AUC 0.92 → 0.63).
  - Source: `docs/reports/tuning.md`, `docs/reports/evidence.md` §3, PR #169.

## Business value, with the working

- [~] **DK-11 · Value tree: where the $1.55M comes from**
  - Break the base case into its drivers (more promises kept from payday timing, fewer wasted contacts, agent time)
    with each assumption and its source; show low $0.44M / base / high $4.27M side by side.
  - Year-one ROI 2.4×, payback about 2.6 months; the low case doesn't pay back in year one, and we say so.
  - Source: `docs/reports/business_case.pdf`, `data/exports/reports/business_data.json`.
- [~] **DK-12 · Measured, not assumed: the evidence ladder**
  - Randomised: +6.1 pts of promised money paid when due just after payday (95% CI 2.8–10.6).
  - Off-policy estimate (labelled as an estimate): 38.6–42.0% paid in 14 days under Kept's policy against
    32.4–32.5% for the bank's; two estimators agree.
  - Model quality: promise model AUC 0.61 on 50,653 held-out promises with a reliability curve; ours plus the bank's
    score 0.728 against 0.702.
  - Source: `docs/reports/evidence.md` §1, §2, §6; `data/exports/reports/model_card.json`.
- [~] **DK-13 · Customer and risk value (not only dollars)**
  - Hardship heard the first time (recall 1.00), cease requests confirmed by a person, contact caps and calling hours
    enforced at release, fairness invariance 0 of 96,000 cards changed when protected attributes are scrambled.
  - Regulatory angle: every action explainable and on the record.
  - Source: `docs/reports/fairness_report.pdf`, `docs/reports/separated_review.md`.
- [~] **DK-14 · Pilot plan with a decision rule**
  - 20% hold-out first, then a permanent 5%; a randomised due-date cell; the metric (promised money paid) and its guard
    metrics; the rule that ends the pilot early either way.
  - Source: `docs/team/NEXT_ROUND_PLAN.md`.

## Presentation craft

- [x] **DK-15 · Every number slide names its source in the footer** (file and section), as `impact` and `safe` do now.
- [~] **DK-16 · Speaker notes: a 20-second answer per slide to "how do you know?"**
- [~] **DK-17 · Appendix for Q&A: the full architecture diagram, the A/B forest plot, the drift and fairness panels,
  the tuning table, and the role matrix**, so detailed questions get a slide, not a description.
- [~] **DK-18 · Export the final deck as PDF into the repo** (`docs/deck/`) with the video link as real text (Phase 5).
