# Pitch deck outline (deliverable 7: up to 10 slides, PDF)

Owner: Akshat (C) assembles; each track drafts its own slide (TEAM_PLAN §2). Final deck in Phase 6
(4 Oct, 15:00–19:00). Numbers marked **TBD** come from runs still to happen; fill them from the
named source, never by hand.

Judging (Build Phase instructions): technical quality + working demo 30% · business understanding 20% ·
presentation and storytelling 20% · innovative ideas 15% · team work 15%. Rules the judges check:
a plain-English reason for every decision, a human can review anything that affects a customer,
no protected attributes, financial hardship flagged.

One story, told once: **an agent opens a case → Kept knows who the customer really is, what they said
on their last call, and when they get paid → it proposes the action most likely to help, sized to a
promise they can keep → a person releases it → everything is logged.**

| # | Slide | Owner | Content | Visual | Criterion |
|---|---|---|---|---|---|
| 1 | **Kept**: promises customers can keep | C | One line: a guarded next best action for collections that dates and sizes promises around payday, with safety rules first and a person releasing every action. Team names. | Title + the NBA card thumbnail | storytelling |
| 2 | Why collections struggles today | A + C | A customer's story is scattered: 31 tables, 6 systems, no shared customer ID (3.84M source keys for 1M people); the best signals are buried in 785K free-text notes and calls; treatment is generic and often due before payday. The metric we move: 30-day roll-forward rate for cases entering 1–30 DPD. | Before/after: six key fragments → one customer | business |
| 3 | Kept in one picture | C | The four layers and what each one guarantees. Mark what changed from the design (orange). | `docs/architecture.png` | technical |
| 4 | One customer, not six fragments (Layer 1) | A | Exact keys then Splink: 3,840,513 keys → **1,052,300 golden IDs**; held clusters for review (two national IDs) instead of guessing; quality gate from the data contract; data traps fixed (snapshots, DPD vs cycles, bureau scales, renamed columns). Precision evidence: **TBD** (300-pair review, Phase 4). | Funnel: keys → golden IDs; one golden record with lineage | technical |
| 5 | Ask anything, safely (Layer 2) | B | Four live examples: a metric (certified SQL shown), a lookup (3 SQL drafts, majority), a policy question (cited section), a protected-attribute question (refused with a suggestion). Benchmark: **TBD** accuracy / **TBD** refusal recall (`kept benchmark`, target ≥80% / ≥95%). | Screenshot of the Ask box with SQL and citation | technical |
| 6 | Reading the notes, with proof (Layer 3, text) | C | Presidio redaction (English + French, Canadian SIN/postal/cards): 785,594 notes and calls, **0 leaks** in a full scan. A local LLM (free, on our GPU) extracts hardship, promises, disputes, cease, third party, **each with a verbatim quote**; a quote that isn't in the note is dropped. Held-out F1 gate: 6 of 7 features pass (hardship recall 1.00). Cease failed on precision, so **it only blocks contact after an agent confirms it**. SetFit trained on LLM labels backfills all history. | A note with highlighted evidence quotes → extracted fields | innovation |
| 7 | The NBA card (Layer 4) | D | Safety first (hard stops, consent, calling hours, 7-day cap, hardship override), then an uplift model (who actually changes behaviour if contacted), then **Kept sizing**: due the day after payday, within spare cash. Plain-English reasons (TreeSHAP top 3) and a release gate: Red needs a specialist + a second person. | The card (screenshot, real case) | technical + rules |
| 8 | Live: a new note flips hardship | D + C | The demo moment: the agent adds "lost shifts at the plant since Aug" → hardship becomes possible (quoted) → risky actions drop out, the card changes → a hardship specialist and a second person release it → the audit log shows every step. | 3-frame strip: before → note → after | demo |
| 9 | Does it work, and is it fair? | D + B | Qini of the uplift model vs the current strategy (`nba_recommendation_last`) on randomly assigned cases: **TBD**. Hypothesis: 1–2 pts lower roll rate at the same or fewer contacts; $ value: **TBD** (roll reduction × monthly inflow balance × charge-off share). Permanent 5% hold-out. Fairness: recommendation rates across protected groups (Fairlearn) **TBD**; lineage CI check proves no feature uses a protected attribute or proxy. | Qini curve + fairness bars | business + innovation |
| 10 | Built responsibly, built together | all | Governance on every layer (role-based access, PII redaction before any LLM, free LLMs only, every LLM call audited, hardship protects and never scores). What changed from the design and why (README). Team: four tracks, gates G0–G4, PRs and CI throughout (commit counts **TBD** from git). | Governance band + team/track grid | team work |

## What to collect before Phase 6 (owner, source)
- Benchmark accuracy and refusal recall: B, `kept benchmark` scorecard in `docs/`.
- Precision on the 300 reviewed pairs: A, `check_review_precision`.
- Qini vs legacy, uplift model version: D, MLflow run.
- Fairness rates: B, `recommendation_rates` on real recommendations.
- Real NBA card screenshots (before/after the note): D, from `kept serve` on C's machine.
- Commit and PR counts per person: C, `git shortlog -sn` on main.

## Innovation points to land (one line each, slides 6–9)
- Every extracted value carries a verbatim quote; no quote, no value.
- A feature that fails its quality gate doesn't silently ship: cease needs a human to confirm.
- Promises dated to payday and sized to spare cash, not to the balance.
- Uplift (who changes behaviour), not propensity (who would pay anyway).
- All text AI runs locally and free; the Ask uses a free tier; no customer text leaves the machine unredacted.
