# Next-round plan: from a strong build to a winning presentation

Sits next to `TEAM_PLAN.md` (the build plan). That plan got us here; this one gets us from the online round
(**Friday 16 October, ~11:00 IST**) into the **top 6** that go on to the offline round.

---

## 0. Where we are

- **Status:** we made the next round. The build phase is closed and `main` holds everything we submitted on 4 October.
- **The organisers' feedback to every team:** *"most presentations were fairly low effort and didn't go deep into the
  background of the problem. Please polish your solutions and presentations before the 16th."*
- **What that means for us:** our build is among the deepest. The gap is in **story, evidence and robustness under live
  questioning**, not in the amount of code. Every hour this week goes to things a judge will see or ask about.

**Judging weights** (unchanged, from the build-phase instructions):

| Criterion | Weight |
|---|---|
| Technical quality and working demo | 30% (the benchmark score counts here; judges ask unseen questions live) |
| Business understanding | 20% |
| Presentation and storytelling | 20% |
| Innovative ideas | 15% |
| Team work | 15% |

---

## 1. The original plan in one page (so we don't stray)

**The idea.** Kept is a *guarded* next-best-action system for Maple Bank's collections team. Collections loses money when
cases **roll** into worse buckets; the cheapest way to stop a roll is a **promise the customer can actually keep**. The
bank's own history shows promises dated just after payday are kept far more often (62.5% vs 51.5% of the promised money
paid), so Kept dates and sizes every promise to the customer's payday and spare cash. It contacts the people a contact
actually helps (uplift, not propensity), protects anyone showing hardship, and lets a person release every action.

**Four layers, four tracks** (`TEAM_PLAN.md` §1):

| Layer | Owner | What it does |
|---|---|---|
| 1 · Data & IDs (A) | Satvik | 31 tables and 68.2M rows → one golden C360 (1.05M IDs, 99.3% precision), contract gate, quality report |
| 2 · Ask (B) | Abhishek | plain-English questions → certified metrics, guarded SQL, cited policy, refusals for protected or bulk-personal data |
| 3 · Text & features (C) | Akshat | redaction, hardship and promise extraction with quotes, SetFit backfill, cash-flow rule, GPU runs |
| 4 · Decide & app (D) | Shreyas | rules → uplift model → payday sizing → tiered human release, the web app and the audit trail |

**Principles we never break:**
- Free or local LLMs only, every call through `kept.common.llm` and audited.
- No protected attribute or proxy in any decision; hardship only ever protects.
- Nothing reaches a customer without a person (Green / Amber / Red; Red needs two people).
- Every number we show comes from a file in the repo; no answer is edited by hand.
- Merge commits, PRs to `main`, CI green.

**What we shipped (4 Oct):**
- **Pipeline:** all four layers, `kept nightly` end to end, 96,000 cards a night.
- **Ask:** dev split 20/21 with 100% refusal recall and precision, every answer cited and verifiable.
- **Fairness:** contact ratio 0.86–1.00 across protected groups; scrambling protected attributes changes 0 of 96,000 decisions.
- **Business case:** $2.2M a year in the base case, 3.8× year-one ROI.
- **Deliverables:** quality, fairness, drift and business-case reports in LaTeX; a 42-question stress suite; the Bench page; the deck and the video.

---

## 2. Honest assessment: what holds us back

Our own reports and track logs already name these. A sharp judge finds each one in under a minute, so we fix them or
say them first, with evidence.

| # | Gap | Where it's recorded | Risk on the day |
|---|---|---|---|
| G1 | **The deck is generic** and doesn't explain the problem's background (the organisers' main complaint) | deck, email | loses Presentation (20%) and Business (20%) |
| G2 | **The payday benefit is observational**; there's no measured effect. The ROI rests on stated assumptions | business case §2, §7 | "how do you know it works?" |
| G3 | **Uplift signal is small** (call Qini 0.0073 vs 0.0017, any-contact 0.0008) and we never compared against the **bank's own model** in `model_scores` | `README`, Track C G3 log | "does your model beat the bank's?" |
| G4 | **Promise model AUC 0.92 probably leaks**: `amount_ratio` is the release's `ptp_to_overdue_ratio`, a field that may be filled from the outcome | `kept/nba/promise_model.py`, PR #116 | an inflated metric, which is the fastest way to lose a judge's trust |
| G5 | **The payroll features are blank in training**, so the model never learned the payday effect our pitch is built on | drift report §2 | undercuts the core idea |
| G6 | **`promise_intent`** is a model input that's always empty | drift report §3 | sloppy if spotted |
| G7 | **Cease extraction failed its F1 gate**, and dispute and date extraction are weak | Track C log | a governance question ("you miss cease requests?") |
| G8 | **Voice was never built**, although the release ships 2,000 recordings | release, design | Innovation and smart use of AI |
| G9 | **Benchmark has room to grow**: BQ-006 wrong, the stress suite was ~50% before fixes, and the free tier rate-limits mid-run | Bench runs | Technical (30%), and live unseen questions |
| G10 | **The demo is fragile**: LLM quota exhaustion, stale features, a stuck server holding the DuckDB lock, a demo case that stays flipped | session logs | a live demo failing on camera |
| G11 | **The pay link** offers plans to only ~25% of customers (payday detection coverage), so it's switched off | PR #127 | a feature we can't show |
| G12 | **Fairness open items**: no minimum-events rule for call flags; separated customers get an 8-point hardship-review gap not yet reviewed | fairness report §6 | a governance question |
| G13 | **The README is long** and has no 2-minute path for a judge | `README.md` | clarity |

---

## 3. Pitfalls common across the field: make sure we don't have them

These are the mistakes that most often cost teams credibility in this challenge. Each needs an explicit check from us.

1. **Leaky headline metrics.** Promise or break models with AUC above 0.9 almost always lean on an outcome-generated field
   (amount-to-overdue ratio, current DPD). *Check:* ablate every model, publish the AUC with and without suspicious
   features, and headline only the honest one (G4).
2. **No comparison with the bank's incumbent.** The release ships the bank's own scores (`model_scores`). A model that
   doesn't beat it, or wasn't compared, reads as unproven. *Check:* report ours against theirs on the same split (G3).
3. **Benefit "estimated", never measured.** The release has **randomised test cells** (`assignment_method = 'random'`,
   champion and challengers). Use them for a measured effect with confidence intervals, plus an off-policy estimate of
   Kept's own policy (G2).
4. **Deck or video missing from the repo, or image-only.** A judge who can't open it can't score it. *Check:* the deck PDF
   (with real text, not images) and the video link are both in the repo and the README.
5. **Claims that don't trace to a file.** *Check:* every number on a slide links to a report or CSV in the repo.
6. **Keys committed** (including in `.env.example`). *Check:* scan the repo and git history before the presentation.
7. **Open fairness flags with no owner.** *Check:* each flag has a decision and a named owner (G12).
8. **Benchmark answers that need a paid key, or were patched by hand.** Ours run on free tiers, from one run; keep it that way.
9. **Protected attributes leaking in through "vulnerability" or language.** Ours is tested (the invariance test). Say so.
10. **A README written for us, not for judges.** *Check:* a short judge guide on top (G13).

---

## 4. Workstreams

Each has an owner, what "done" means, and the criterion it moves. Owners follow the original tracks, so each person
presents what they built (that's the 15% for team work).

### WS1 · The problem, told properly (Presentation 20% · Business 20%): Akshat, with Shreyas
The organisers' feedback names this directly, so it opens the deck and the talk.
- **Background:**
  - why collections matters for a bank (losses, provisioning, cost to collect);
  - why it matters for the customer (stress, fees, credit file);
  - what the regulators expect in Canada (FCAC treatment of customers in financial hardship, provincial collection rules,
    CASL, the DNCL).
- **Maple Bank's version of it, from its own data:**
  - 194,515 entries a year at 1–30 DPD;
  - 48.8% roll within 30 days;
  - rolling is the only road to a charge-off (2.5% of rolled cases, ~$12.5K each);
  - 5,328 contacts outside calling hours;
  - 290 contact-cap breaches;
  - promises dated before payday break.
- **The human story:** one anonymised composite customer (Jane) whose promise breaks because it falls before payday, and
  how Kept changes that. Carry her through every slide.
- **Root causes, not symptoms:**
  - wrong timing (payday);
  - wrong person (propensity instead of uplift);
  - hardship found late (it sits in notes);
  - fragmented identity (5 systems, no shared key).

  Each maps to one layer.
- **Done when:** a non-banker on the team can explain the problem in 60 seconds before Kept is mentioned.

### WS2 · Measured evidence, not estimates (Business 20% · Technical 30%): Shreyas, with Satvik
- **Randomised-cell result:** promise-kept, cure-30 and roll-30 by test cell, randomised cases only, with 95% CIs. That's a
  *measured* effect of strategy differences.
- **Off-policy estimate of Kept's policy** on the randomised cases (IPS or doubly robust, with CIs). Report it honestly,
  even if the interval includes zero.
- **Payday effect, made causal where possible:** among randomised promises, compare due-after-payday against before
  (within-cell), controlling for amount and DPD. Replace "observational" with a measured or bounded number.
- **Bank-incumbent comparison:** our uplift and promise models against `model_scores` on the same time split (AUC, Qini,
  calibration).
- **Leakage audit (G4):** promise-model AUC with and without `amount_ratio` / `ptp_to_overdue_ratio` and `dpd`. Headline
  only the leak-free number, and say why.
- **Business case refresh:** feed the measured numbers in and keep the low / base / high bands. The deck shows the measured
  number first and the estimate second.
- **Done when:** every business number in the deck has a measured source or an explicitly bounded estimate, all in
  `docs/reports/`.

### WS3 · Ask accuracy and live robustness (Technical 30%): Abhishek
- **Fix BQ-006:** the disputes-raised convention is drafted on `fix/disputes-raised`. Test it three times live, then merge.
- **Stress suite:** take every stress-suite category to ≥ 80%:
  - filters dropped or added (outbound calls, open cases);
  - policy versions ("before March 2026");
  - French and Quebec documents;
  - count versus rate.
- **Retrieval:** add hybrid search (BM25 plus a small local multilingual embedding model on C's GPU) so French sections
  and paraphrases are found. Ask before downloading the model.
- **Rate-limit resilience:**
  - retry with backoff;
  - a response cache for repeated questions;
  - a *free* fallback provider already in `.env.example` (Groq), switched on only with the team's agreement (free-only rule).
- **Live-question drill:** 30 unseen questions written by the team (not the benchmark), run on the Bench page every day.
  Track accuracy over the week.
- **Done when:** dev 21/21, stress ≥ 80%, live drill ≥ 85%, and zero failures caused by rate limits.

### WS4 · Model and data depth (Technical 30%): Akshat (GPU) and Satvik
- **Payroll features point-in-time (G5):** rebuild `payroll_delay_days`, `pay_change_vs_3m_avg` and `days_to_next_payroll`
  for past decisions from `salary_credit_history` (dated deposits), retrain, and show the model now uses payday. Keep the
  champion/challenger gate, so a worse model can't go live.
- **`promise_intent` (G6):** wire it from the LLM extractions or drop it from the model's inputs.
- **Cease and dispute extraction (G7):**
  - a prompt v4 with few-shot quotes;
  - a rule backstop for explicit "stop calling" phrases;
  - re-gate on the public labels and publish precision and recall.
- **Pay link coverage (G11):** fall back to the bank's `expected_next_payroll_date` and pay frequency when deposits are
  missing. Re-enable the page only if most customers get a plan.
- **Fairness follow-ups (G12):**
  - a minimum-events rule (20+) on call-ratio flags;
  - a 50-card review of separated customers' hardship reviews, written up.
- **Done when:** retrain results and the extraction re-gate are in `docs/reports/`, and the drift report is regenerated.

### WS5 · Voice (Innovation 15% · smart use of AI): Akshat
- Whisper (local, GPU) on the 2,000 recordings → transcripts, with **WER against the release's transcripts**.
- Feed the transcripts into the same redaction and extraction pipeline, and compare against the text-only extraction.
- **No voice biometrics, accent or pitch features:** they're protected or proxy attributes in our contract. Say so on stage.
- **Done when:** a WER report plus one demo moment ("a call becomes a hardship flag with the exact quote").

### WS6 · A demo that can't fail, and a judge path (Technical 30% · Clarity): Shreyas, with Satvik
- **`kept demo-reset`:** one command that clears demo notes, refreshes features and cards, and restarts serve.
- **Pre-flight script:**
  - LLM key quota check;
  - Ollama warm-up;
  - features fresh;
  - no stale server holding the warehouse lock.

  Run it 15 minutes before the slot.
- **Offline fallback:** the demo mode (`kept serve --demo`) works with no network. Rehearse switching to it.
- **`JUDGES.md`:**
  - a one-page, 2-minute path: what to run, what to click, where each claim's evidence lives;
  - a link at the top of the README;
  - the README trimmed to a crisp summary, with detail moved into `docs/`.
- **Done when:** two full dry runs pass on a cold machine with a fresh key.

### WS7 · Team work, made visible (15%): everyone
- Each person presents their own layer (about 2 minutes each) and answers questions on it.
- One slide on how we worked: tracks, integration gates G0–G4, 87 merged PRs, CI, the test count, and a contribution
  breakdown by person.
- Update the track logs (`docs/team/tracks/`) with this week's work.

---

## 4a. Execution phases (the order we work in)

The workstreams above, sequenced. Each phase ends with its PRs merged (CI green) and a short note in the track log.

| Phase | When | Workstreams | Exit check |
|---|---|---|---|
| **0 · Safe base** ✅ | Fri 9 Oct | WS3 (BQ-006), WS6 (`kept preflight`, `kept demo-reset`), plan + ignore rules | dev 21/21; preflight GO (done: #131–#134) |
| **1 · Measured evidence** | Sat 10 | WS2: randomised-cell results with CIs, off-policy estimate of Kept, head-to-head with the bank's `model_scores`, promise-model leakage audit | a report in `docs/reports/`, every number reproducible |
| **2 · Model depth and voice** | Sun 11 | WS4: point-in-time payroll features + retrain (champion/challenger), `promise_intent`, cease/dispute re-gate · WS5: Whisper + WER | retrain and extraction reports; WER report |
| **3 · Ask accuracy and robustness** | Mon 12 | WS3: stress suite ≥ 80%, hybrid retrieval (French, paraphrase), rate-limit retry and cache, 30-question unseen drill | dev 21/21, stress ≥ 80%, drill ≥ 85% |
| **4 · Story and judge path** | Tue 13 | WS1: problem background and Jane's story · WS2: business case refresh · WS6: `JUDGES.md`, README trim · deck v2 · WS4: fairness follow-ups | deck v2 complete; rehearsal 1 |
| **5 · Rehearse and freeze** | Wed 14 – Thu 15 | WS7 and everything: two cold-machine dress rehearsals, final benchmark run, freeze Thu 18:00, §7a runbook | rehearsal 2 clean; features refreshed |

Downloads (Whisper, an embedding model) and any switch of LLM provider are asked about first (`CLAUDE.md`).

## 5. The new deck and talk (outline)

Built to answer "didn't go deep into the background of the problem". Real text (not images), every number linked to a file.

1. **The cost of a broken promise:** Jane's story in one picture. Collections losses, and what a missed payment does to a customer.
2. **Background:**
   - the Canadian regulatory frame;
   - how collections works today (buckets, rolls, charge-off at 181 days);
   - where the money leaks (Maple Bank's numbers).
3. **Root causes:** timing, targeting, hardship found late, fragmented identity. Each with evidence from the bank's own data.
4. **Kept, in one sentence and one picture:** a guarded next best action, with promises dated to payday.
5. **Layer 1:** one customer from five systems, quality we can prove, a contract gate.
6. **Layer 2:** ask anything, every answer cited and verifiable, refusals with reasons. The live benchmark result.
7. **Layers 3–4:** hardship read from notes and voice with the exact quote; uplift, not propensity; payday sizing; the
   person releases. Our model against the bank's.
8. **Measured impact:** the randomised-cell results with CIs, then the business case (low / base / high).
9. **Fair and safe by construction:** the invariance test, the fairness ratios, the audit trail, champion/challenger and the drift alarm.
10. **How we built it, and what's next:** four tracks and gates, the PR and test stats, the pilot plan (20% hold-out, then 5%).

**Live demo (about 4 minutes) inside the talk:**
1. Jane's case: the card.
2. A note flips it to hardship.
3. Two-person release.
4. Audit.
5. One live unseen Ask question.

Have a recorded backup ready in a second tab.

---

## 6. Q&A preparation (owner per answer)

| Likely question | Answer with (evidence) | Owner |
|---|---|---|
| How do you know the payday effect is real? | randomised-cell result and the within-cell payday comparison, with CIs (WS2) | Shreyas |
| Does your model beat the bank's? | head-to-head against `model_scores` on the same split | Shreyas |
| Your promise AUC looks high: leakage? | the ablation table; we headline the leak-free number | Shreyas |
| Can a protected attribute influence a decision? | the invariance test (0 of 96,000), CI lineage check, the restricted table | Abhishek |
| What if the LLM is wrong or hallucinates? | SQL guard, grounding check on every number, verifiable citations, refusals | Abhishek |
| What about cease requests you miss? | the extraction re-gate, the rule backstop, a person reviewing Red cards | Akshat |
| Why should a bank trust your identity resolution? | 99.3% precision, the steward queue, the quality report | Satvik |
| What does it cost to run? | $150K a year: one ops engineer plus compute, local models, no per-call fees | Akshat |
| How would you roll it out? | 20% hold-out for 2 months, then 5%, a kill switch, champion/challenger | Shreyas |
| What would you do with more time? | live pilot, voice in production, payday detection coverage | everyone |

---

## 7. Schedule (IST)

| Day | Focus | Exit check |
|---|---|---|
| **Fri 9 Oct** | this plan agreed; reply to the organisers by **1 PM 10 Oct** about any class clash on the 16th | owners confirmed |
| **Sat 10** | WS1 background research; WS2 randomised-cell analysis; WS3 BQ-006 merge and live drill v1; WS6 `demo-reset` | first numbers in |
| **Sun 11** | WS2 leakage audit and bank comparison; WS4 point-in-time payroll features; WS5 Whisper run on GPU | reports drafted |
| **Mon 12** | WS4 retrain plus extraction re-gate; WS3 retrieval and stress ≥ 80%; deck v2 storyline (WS1) | Ask accuracy at target |
| **Tue 13** | business case refresh with measured numbers; JUDGES.md; README trim; deck v2 complete | full dress rehearsal 1 |
| **Wed 14** | fix everything rehearsal 1 found; final benchmark run; fairness follow-ups written up | dress rehearsal 2 on a cold machine |
| **Thu 15** | freeze at 18:00 (code and deck); evening: `kept features && kept score` on the demo machine (§7a); Q&A drill | everything merged, CI green, features fresh |
| **Fri 16** | `kept preflight` 15 minutes before the slot must print GO (§7a); present | — |

Rules for the week:
- Same as `TEAM_PLAN.md` §0: branch per change, PR to `main`, CI green, merge commits only.
- Nothing merges after Thursday 18:00 except a fix for something broken.

---

## 7a. Day-of runbook (any machine: do not skip)

Whoever's laptop runs the demo, these steps apply. The system needs the warehouse built on that machine (`kept nightly`, or a
copy of `data/`), a `.env` with a working free Gemini key, and Ollama with `gemma3:12b-it-qat` pulled.

**The evening before (Thu 15 Oct)**
```bash
uv run kept features && uv run kept score   # features go stale after 26 h; stale features make every card "no action"
```

**15 minutes before the slot (Fri 16 Oct)**
```bash
uv run kept serve                            # terminal 1 (real data)
cd web && pnpm dev                           # terminal 2
uv run kept preflight                        # terminal 3: must print "kept preflight: GO"
```
On NO GO, the failing check names its fix:
- **features:** run `kept features && kept score` with `kept serve` stopped.
- **warehouse lock:** a stale `kept serve` holds it; stop that process.
- **Ask LLM:** the key is out of quota; swap in a fresh free key and restart `kept serve`.
- **text LLM:** start Ollama.
- **web:** run `pnpm dev`.

**Between rehearsal takes**
```bash
# stop kept serve first (DuckDB allows one writer), then:
uv run kept demo-reset                       # removes notes typed in earlier takes, so the demo case starts Green again
uv run kept serve
```

**Fallback:** `uv run kept serve --demo` runs twelve in-memory cases with no warehouse and no network.

---

## 8. Definition of done for the round

- [ ] Deck v2: background-first, Jane's story throughout, every number linked, real text, in the repo as PDF.
- [ ] Measured impact (randomised cells, CIs) and an honest leak-free model comparison against the bank's incumbent.
- [ ] Ask: dev 21/21, stress ≥ 80%, live drill ≥ 85%, rate-limit-proof.
- [ ] Point-in-time payroll features in the model, and the extraction re-gated.
- [ ] Voice: a WER report and one demo moment.
- [ ] `JUDGES.md`, a trimmed README, `kept demo-reset`, the pre-flight script.
- [ ] Two clean dress rehearsals; each person presents their own layer.
- [ ] Day-of runbook (§7a) followed on the demo machine: features refreshed the evening before, preflight GO before the slot.
