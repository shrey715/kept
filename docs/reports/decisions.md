# Design decisions, and the evidence behind each

Every design decision in Kept, the alternatives we considered, and the measured number that decided it. Each
alternative was run on the same data, split and machine as the option we chose; where an alternative won, the row says
so and what we did about it. The analyses below the register give the setup, the full result table, outside support
and the command that reproduces each number. Numbers come from `data/exports/reports/decision_<id>.json`, written by
the scripts named in each section.

![The decision timeline](figures/dec_timeline.png)

## The decision register

| Decision | Alternatives considered | Deciding number (source) | Outside support | Date, PR | Status |
|---|---|---|---|---|---|
| Qwen3.8-27B on llama.cpp for every LLM call | Gemma 3 12B on Ollama | Released 21/21, stress 38/42, drill 27/30 against 18, 30 and 22 on Gemma, same day (`ask_accuracy.md`); costs in [§B4](#b4-local-vs-hosted-llm-cost-quota-and-privacy), step-by-step gain in [§B5](#b5-ask-design-one-prompt-against-our-pipeline) | none cited | 14 Oct #169; 15 Oct #175 | switched: all calls moved to Qwen on llama.cpp |
| llama.cpp over Ollama | Ollama | Ollama ran a 4,096-token window under the Ask's ~9,000-token prompt (`ask_accuracy.md`, `design_changes.md`); [§B3](#b3-serving-runtime-llamacpp-vs-ollama) in progress | none cited | 14 Oct #169 | switched: llama.cpp serves the model |
| Gemma 4 26B as a larger model | Gemma 4 26B against the models in use | 24 s a note, runaway replies, no gain on held-out notes (`design_changes.md`) | none cited | | kept: rejected, not shipped |
| Local models only, not hosted | Gemini 3.5 Flash-Lite, Claude Haiku 5.5, Sonnet 5.5 at list price; Gemini free tier | Base load USD 2,200 a year on 2 GPUs against 1,386 for Haiku 5.5 and 5,079 for Flash-Lite; the free tier covers 500 requests a day, one base night is 1,647 extractions ([§B4](#b4-local-vs-hosted-llm-cost-quota-and-privacy)) | OSFI E-23 and B-10, PIPEDA, Quebec Law 25 s. 17 | 16 Oct, #214 | kept: the case is privacy and regulation, not cost |
| Schema-constrained extraction replies | Free-form JSON with parse-and-retry | Malformed replies 152 to 0 of 1,172 calls (deck "What we tried"; `extraction_gate.md` records the re-run with schema decoding) | none cited | 12 Oct; #165 (merged 14 Oct) | switched: replies decoded to the JSON schema |
| SetFit backfill for the note history | Keyword rules; the LLM on every note | Notes F1 0.869, recall 0.977 (`Track_C.md`); in [§B7](#b7-extraction-keyword-rules-setfit-or-the-llm): SetFit 0.87 against rules 0.63 and LLM 0.88, at 1/35,000th of the LLM's time | Tunstall et al. 2022 (SetFit) | | kept |
| Whisper large-v3-turbo on call recordings | The bank's speech-to-text; other Whisper sizes ([§B8](#b8-speech-to-text-model-size) in progress) | WER 9.4% against 12.4%; 87x real time (`voice_wer.md`) | Radford et al., "Robust Speech Recognition via Large-Scale Weak Supervision", ICML 2023 | 10 Oct #144 | kept |
| Splink for identity matching, trained on a 1-in-5 sample | Exact keys only; an embedding matcher; training on all 3.84M keys | Precision 99.3% (300 links reviewed), recall 198/200 (`identity_recall.md`, `QUALITY_REPORT.pdf`); the full 3.84M keys ran out of 30 GB, so the sample; [§A4](#a4-identity-exact-keys-only-exact-keys-plus-splink-or-an-embedding-matcher) | Fellegi and Sunter 1969; Linacre et al. 2022 | 3 Oct #14; recall test 12 Oct #156 | switched: trained on a 1-in-5 sample; Splink kept |
| Exact keys, then Splink, then a steward | Exact keys only; embedding matcher | 987,667 people split across records without Splink; embeddings merge 156 of 200 planted duplicates against Splink's 198 ([§A4](#a4-identity-exact-keys-only-exact-keys-plus-splink-or-an-embedding-matcher)) | Fellegi and Sunter 1969 | 16 Oct, #214 | kept |
| Champion/challenger gate on Qini | Tuned challenger (40 candidates) | Tuned challenger lost, Qini 0.0029 against 0.0073 (`tuning.md`) | Radcliffe and Surry 2011 | 4 Oct #118 | kept: champion stays |
| Uplift ranking, not a "who will pay" score | Response model | Top 30%: live T-learner +25.6 to +55.6 extra payers per 1,000 over the response model; Qini 7.9 against 3.2 ([§B10](#b10-uplift-against-a-who-will-pay-response-model-and-the-learner-choice)) | Radcliffe and Surry 2011; Kunzel et al. 2019 | 16 Oct, #214 | kept |
| Uplift learner (T-learner) | S-learner, causal forest | S-learner Qini 14.8 and causal forest 10.7 against 7.9 for the T-learner, on a judge that favours the S-learner ([§B10](#b10-uplift-against-a-who-will-pay-response-model-and-the-learner-choice)) | Kunzel et al. 2019 | 16 Oct, #214 | open: no switch until a pilot settles it |
| Promise model: leaking feature removed | The first version with `amount_ratio` | AUC 0.92 to 0.63 once removed (`evidence.md` §3) | none cited | 9 Oct #142 | switched: feature dropped |
| Promise model: the 6-feature model on the card | The wide 79-input model; logistic regression; calibration | Wide LightGBM AUC 0.697 against 0.625 for the 6-feature one (bank 0.702) ([§B9](#b9-promise-model-which-model-ships)) | Niculescu-Mizil and Caruana 2005; Ke et al. 2017 | 16 Oct, #214 | open: wide model recommended, no live code changed |
| Promises due on payday, not the day after | Dates 1-3 days before or after payday | Promised money paid +6.1 pts [2.8, 10.6]; due on payday +7.7 against 1-3 days before and +8.3 against 1-3 days after (`evidence.md` §2, §2a) | none cited | 15 Oct #201 | switched: promises dated on payday |
| Plan-aware Red | New hardship review on every Red case | Red cards 38,187 to 33,646 (`business_case.tex`) | none cited | 15 Oct #202 | switched: no new review on a running plan |
| Calls booked into hours with capacity | Every proposed call at once | 56% of calls over capacity to 0 (as given by the lead; not found in the repo's reports) | none cited | 15 Oct #211 | switched |
| Nightly batch plus a live-note refresh | Hourly re-scoring on a stream | 3.12% of cards (2,839 of 90,998) change in a day; 2.70% are not covered by the live-note path ([§A2](#a2-nightly-batch-plus-the-live-note-path-against-hourly-re-scoring)) | Kleppmann 2017, chapters 10 and 11 | 16 Oct, #214 | kept |
| Weekly contact cap applied to hardship reviews | Exempting protected cases from the cap | 1,810 hardship cards flip between a review and no action only because the cap is reached or released ([§A2](#a2-nightly-batch-plus-the-live-note-path-against-hourly-re-scoring)) | none cited | 16 Oct, #214 | open: left as built; owner to decide |
| One feature definition, checked by `kept parity` | Serving-side reimplementation | Injected bugs: 1,325 and 808 cells differ against 0 of 56,000 for the control; Feast read 0.23 ms ([§A3](#a3-feature-store-against-training-and-serving-skew); `Track_C.md` G3 for the live result) | Sculley et al. 2015; Zinkevich, Rules of ML | 3 Oct (G3); 16 Oct, #214 | kept |
| Redaction on `en_core_web_lg`, with layered guards | `en_core_web_sm`; each guard layer alone | Residual name per 1,000 transcripts 32.1 against 88.2; 45 of 45 attacks stopped offline by the three layers ([§A5](#a5-privacy-and-guard-architecture-measured)); live red-team pending | OWASP LLM Top 10 2025; PIPEDA; Quebec Law 25 | 16 Oct, #214 | kept |
| The Ask pipeline, not one prompt | One prompt with the schema | 86 of 93 right against 36 for one prompt; 38.7% to 87.1% from the router and certified metrics alone ([§B5](#b5-ask-design-one-prompt-against-our-pipeline)) | Li et al. 2023 (BIRD); Wang et al. 2023 | 16 Oct, #214 | kept |
| Hybrid policy search (BM25 + bge-m3) | BM25 only; dense only; hybrid plus rerank; three other embedders | Dense only MRR 0.747 against hybrid 0.640; French 0.821 against 0.564; rerank cuts French to 0.237 ([§B6](#b6-policy-search-bm25-vs-embeddings-vs-hybrid-and-which-embedder)) | Chen et al. 2024 (BGE M3); Cormack et al. 2009 | 12 Oct #154 | open: dense-only wins, hybrid still live; the rerank is rejected |
| Extraction: the LLM for live notes, SetFit for the history | Keyword rules; SetFit alone | Hardship F1 0.88 (LLM), 0.87 (SetFit), 0.63 (rules, recall 0.75 against the 0.90 gate) ([§B7](#b7-extraction-keyword-rules-setfit-or-the-llm)) | Tunstall et al. 2022 | 16 Oct, #214 | kept |
| Hardship by a cash-flow rule, not a model | LightGBM with and without EI | Recall 0.652 for the rule against 0.672 to 0.678 at the same flag rate, no precision gain ([§C2](#c2-hardship-rules-not-a-model)) | OSFI E-23; 29 CFR 1607.4(D) | 16 Oct, #214 | kept |
| Fairness: protected attributes and proxies | Scramble the protected list; protected plus proxies | 0 of 96,000 cards change on the protected list; 299 change with proxies, all from `ei_deposit_flag` ([§C3](#c3-fairness-with-and-without-the-stand-in-features); `fairness_report`, #200) | OSFI E-23; 29 CFR 1607.4(D) | 15 Oct #200; 16 Oct, #214 | kept |
| Scoring on one machine: DuckDB, dbt, Feast | Spark or Snowflake, Redis, Kafka | 96,000 cards scored in about 85 s (deck "A small stack"); [§A1](#a1-warehouse-engine-and-scale-headroom) in progress | none cited | | kept |
| Quantization of the model | not yet defined | [§B2](#b2-quantization) not started | none cited | | open |
| Which model for each task | not yet defined | [§B1](#b1-llm-bake-off-on-our-three-tasks) in progress | none cited | | open |

## The analyses

### A1. Warehouse engine and scale headroom

_Measurement in progress._

### A2. Nightly batch plus the live-note path, against hourly re-scoring

**Question.** How many cards would change within a day if the cards were re-scored every hour instead of overnight?

**Alternatives.** Nightly `kept nightly` with a live re-score on each new note (kept); hourly re-scoring on a stream.

**Setup.** Warehouse `eval_copy.duckdb`, read-only, CPU, in memory. Event rates: weekdays 26 Jul to 23 Sep 2026, per open case. Replay: Thursday 24 Sep 2026, from the 06:00 UTC nightly to 06:00 UTC next day (90,998 open cases). Only the six features that events move within a day were recomputed each hour with the dbt SQL rules (answer rate, answer rate after 18h, payment-link use, contacts in 7 days, broken promises, kept ratio). Account, payroll, cohort and text features stay at the stored nightly values, because the account tables change monthly and the text features are what the live-note path refreshes. Cards come from the live engine with `now` fixed, so only the events differ. This is a proxy for a full hourly nightly, not a copy of one; no warehouse was copied or written.

**Result.**

| Event per open case per day | Mean | Busiest day |
|---|---|---|
| Outbound contact | 0.164 (14.2% of cases) | 23.7% of cases |
| Note | 0.062 (5.9%) | 9.9% |
| Promise falling due | 0.015 (1.5%) | 6.0% |
| Payment | 0.005 (0.5%) | 1.2% |

| Replay of 24 Sep | Cases | Share |
|---|---|---|
| Any of the six inputs changed during the day | 19,772 | 21.7% |
| Best action differs from the nightly card at end of day | 2,839 | 3.12% |
| Of those, a note arrived in the window (live path covers) | 378 | 0.42% |
| Of those, no note (not covered) | 2,461 | 2.70% |
| Of those, hardship at the nightly | 1,810 | 1.99% |

Control: with features held at 06:00 and only the clock moved to 24 hours later, 0.13% of a 3,000-case sample change action. The largest moves are none to hardship_review (979) and hardship_review to none (563). These are legitimate, not a replay gap: the replay calls the same `KeptEngine.recommend` as `kept score`. In `src/kept/nba/rules.py` the CONTACT_CAP check (`contacts_last_7d < contact_cap_7d`) runs in stage 2, before `hardship_override` (stage 3, `engine.py`), and removes every contact action, a hardship review included, because the review is a call. So a protected customer who reaches the weekly cap gets no action, and one who drops below it gets the review back. In the replay the cap is crossed on 2,711 of the 2,839 changed cards, and on 1,800 of the 1,810 hardship ones. Nightly wall time: 334 s (nightly_run.log) and 407 s with the match step (nightly_full.log); `nightly_run.json` is not on this machine, so the step seconds in the logs were used. Replaying 25 hourly states of the six features took 3.4 s of SQL and 119 s of scoring for the changed cases.

![Cards that change under hourly re-scoring](figures/dec_A2.png)

**Verdict.** Kept as a trade-off. Hourly re-scoring would change about 3.1% of cards in a day, and 2.7% of cases are not covered by the live-note path. The changes are almost all contact-cap moves: the hardship cards among them (1,810 of 2,839) flip between a review and no action only because the weekly cap is reached or released, not because their protection lapsed. A contact does not trigger the live-note path, so those are the cards a stream would refresh; the batch costs about one card in thirty being a day stale, a bounded loss to weigh against running a stream.

**Outside support.** Kleppmann, "Designing Data-Intensive Applications", O'Reilly, 2017, chapters 10 (batch) and 11 (stream), https://oreilly.com/library/view/designing-data-intensive-applications/9781491903063 (batch output is derived data that can be regenerated; streams add latency gains at operational cost).

**Reproduce.** `uv run python scripts/decision_A2.py --day 2026-09-24`.

### A3. Feature store against training and serving skew

**Question.** Does the single feature definition plus `kept parity` catch a serving-side rewrite, and what does Feast cost per read?

**Alternatives.** Feast with one definition checked nightly (kept); a serving-side reimplementation read straight from the warehouse.

**Setup.** `eval_copy.duckdb` read-only plus a scratch Feast repo (copy of `feature_repo`, materialised from the real parquet export into a scratch SQLite store) outside the repository; nothing written to a warehouse. The offline side is `features.case_features` at the 15 Oct 2026 06:00 UTC nightly (96,000 cases, 28 features). Two bugs were injected by replacing the six contact and promise features the online side returns with a rewrite's values: (1) the snapshot date (28 Sep) instead of the point-in-time `as_of`; (2) the "after 18h" hour taken from the UTC timestamp instead of the local one. A control rewrite with the right `as_of` must show no difference. The check is `run_parity`, the function behind `kept parity`.

**Result.**

| Run | Cells differing (2,000-case sample, as the nightly runs it) | Cells differing (all 96,000 cases) | Parity | Cards whose best action changes |
|---|---|---|---|---|
| Control, right as_of | 0 of 56,000 | 0 of 2,688,000 | PASS | 0 |
| Snapshot date instead of as_of | 1,325 (2.37%) | 63,353 (2.36%) | FAIL | 5,503 (5.73%) |
| UTC hour instead of local | 808 (1.44%) | 38,035 (1.42%) | FAIL | 344 (0.36%) |

Both are 14 to 24 times the 0.1% limit and are caught on the 2,000-case sample. Worst features: `contacts_last_7d` (60,036) and `broken_promises_90d` (3,294) for the clock bug; `answer_rate_after_18h` (38,035) for the timezone bug. Read time over 500 cases: Feast online (SQLite) 0.23 ms per case; DuckDB, one query per case, 1.39 ms; DuckDB batched, 0.017 ms per case. The DuckDB table is unindexed and cached, so the one-by-one comparison favours neither side much; batched reads are faster than either.

![Parity cells that differ with injected bugs](figures/dec_A3.png)

**Verdict.** Kept. The parity test catches both bugs on its normal sample, and the cost is no slower than a per-case warehouse query. The timezone bug is small in cards (0.36%) but fully visible in cells, which is the reason to test cells and not decisions.

**Outside support.** Sculley et al., "Hidden Technical Debt in Machine Learning Systems", Advances in Neural Information Processing Systems 28 (NIPS 2015), pp. 2503-2511, https://proceedings.neurips.cc/paper/2015/file/86df7dcfd896fcaf2674f757a2463eba-Paper.pdf. Zinkevich, "Rules of Machine Learning: Best Practices for ML Engineering", Google, rule 29 (log the features used at serving time to train on them) and rule 37 (measure training/serving skew), https://developers.google.com/machine-learning/guides/rules-of-ml/.

**Reproduce.** `uv run python scripts/decision_A3.py --repo <scratch feature_repo>` (apply and materialise a scratch repo first: `feast apply`, `feast materialize`).

### A4. Identity: exact keys only, exact keys plus Splink, or an embedding matcher

**Question.** Does the Splink stage earn its place beside the five exact rules?

**Alternatives.** (1) Exact keys only. (2) Exact keys plus Splink, with a steward on the uncertain pairs (live). (3) A sentence-embedding matcher (BAAI/bge-small-en-v1.5, CPU) on name, first name, date of birth and postal code, with a cosine threshold.

**Setup.** Full run: 3,840,513 source keys in `eval_copy.duckdb` (read-only), the live crosswalk from the full `kept match` run (`run_summary_cc2883b-20261003-full-train5.json`). The exact-only crosswalk is the same matcher with its Splink stage switched off (`no_splink()` in `scripts/identity_injection.py`, evaluation only; live code is unchanged). Recall: the 200 planted duplicates of `identity_injection.py` on the 5% DOB-hash sample. Embedding threshold: set on a different 5% sample (hash % 20 = 1) to reach the design's 0.98 precision against the live crosswalk, then tested on sample 0, the 200 planted duplicates and the 300 reviewed pairs. Machine: CPU, 6 GB cap.

**Result.**

| Measure | Exact keys only | Exact + Splink (live) |
|---|---|---|
| Golden IDs | 2,897,505 | 1,052,300 |
| Keys whose strongest link is Splink | 0 | 2,038,013 |
| People split across records (live people with more than one exact cluster) | 987,667 | 0 |
| Open cases whose person is split | 92,538 of 96,000 | 0 |
| Open balance on those cases (CAD) | 75,741,351.53 of 78,527,247.88 | 0 |
| Recall on 200 planted duplicates | 0 of 200 | 198 of 200 |

Links per exact rule (recounted from the evidence): core banking CIF 495,420; case-to-CRM reference 288,426; payment source account 151,277; national ID hash 18,426; CRM duplicate pointer 444. Full-run summary: 943,008 exact pairs, 4,147,704 Splink pairs auto-linked, 251 sent to review.

The 0 of 200 is the expected result, not a finding about the exact keys: the planted duplicates carry no national ID and no duplicate pointer by design, so no exact rule can reach them. It shows that the planted set tests only the Splink stage.

Embedding matcher: cosine threshold 0.9232. Planted duplicates merged 156 of 200 (surname typo 25 of 40, first initial only 19 of 40, new postal code 32 of 40), with 9 wrong links (Splink: 198 of 200, 0 wrong). On the 300 reviewed pairs it links 219 (precision 1.00, recall of true pairs 0.735). Cost: 1.33 s per 1,000 records to embed on the CPU (224 s for 171,154 records), plus 39 s for the nearest-neighbour search on that sample. At 3.84M records the embedding alone is about 85 minutes, and the all-pairs search is quadratic in the dense form used here.

![Identity: exact keys, Splink, embeddings](figures/dec_A4.png)

**Verdict.** Kept. Without Splink, 987,667 people are split and 92,538 of 96,000 open cases (CAD 75.7M of 78.5M) would see only part of the customer. The embedding matcher is cheaper to write but misses the typo and initial cases and makes wrong links; it is not a replacement. Trade-off to note: the reviewed pairs contain 298 true of 300, so they measure precision of links Splink already made, not the embedding matcher's recall on unseen pairs.

**Outside support.** Fellegi and Sunter, "A theory for record linkage", Journal of the American Statistical Association 64(328), 1969, https://courses.cs.washington.edu/courses/cse590q/04au/papers/Felligi69.pdf (link, possible link and non-link regions; the middle band is the steward queue). Linacre, Lindsay, Manassis, Slade and Hepworth, "Splink: Free software for probabilistic record linkage at scale", International Journal of Population Data Science 7(3), 2022, https://ijpds.org/article/view/1794. Peeters, Steiner and Bizer, "Entity matching using large language models", EDBT 2025, pp. 529-541, https://madoc.bib.uni-mannheim.de/68185 (no single prompt works best across models and datasets; relevant to cost and tuning of LLM matchers, which were not run here).

**Reproduce.** `uv run python scripts/decision_A4.py --part split`, `--part recall`, `--part embed`, then `--part assemble` (one process each, to stay inside 6 GB).

### A5. Privacy and guard architecture, measured

**Question.** Does redaction before the LLM leave personal data behind or remove what the Ask needs, and do the rules, the SQL guard and the grounding check stop attack questions without the LLM?

**Alternatives.** Redaction: `en_core_web_lg` (live) against `en_core_web_sm`. Guard: each layer alone, then the layers together; and the guard switched off, to show what the attack SQL would have done. `en_core_web_trf` was skipped (GPU, 450 MB, not approved).

**Setup.** Redaction: `kept.text.redact.PresidioRedactor` (presidio-v7; French stays on `fr_core_news_lg`), CPU, 8 workers, seed `a5`. Sample: 2,000 agent notes (language x redaction status, equal allocation) and 500 call transcripts (language x direction), plus the 122 benchmark, drill and stress questions. Independent checks, not Presidio: regex plus Luhn for card and SIN numbers, phones (toll-free excluded), emails, postal codes, birth dates, and the case customer's own names from `silver.customers`. Over-redaction: amounts, record ids and ordinary dates present before and gone after. Guard: 46 questions in `benchmarks/redteam_questions.csv` (45 attacks, 1 harmless control), each with the layer expected to stop it, written before the run. The offline run uses the real `rule_check`, `guard_sql` and `ungrounded_numbers`. The attack SQL is hand-written (what a hijacked model might emit); with the guard off a SELECT is only bound with EXPLAIN on the read-only eval copy and every other statement is parsed, never run. The LLM scope classifier and the live Ask are not in this run.

**Result.** Redaction (transcripts are population-weighted by stratum; notes and questions: zero residual and zero over-redaction on both models).

| per 1,000 texts | en_core_web_lg | en_core_web_sm |
|---|---|---|
| Notes with PII before redaction (sample, of 2,000) | 537 | 537 |
| Notes, residual PII / over-redaction | 0 / 0 | 0 / 0 |
| Transcripts, residual PII (customer name left) | 32.1 | 88.2 |
| Transcripts, over-redaction (ordinary date removed) | 7.5 | 7.5 |
| Transcript PII items removed | 97.9% | 94.7% |
| Seconds for the 1,980 distinct texts | 11.7 | 13.3 |

Red team, offline layers (45 attacks):

| Layer | Stops |
|---|---|
| Refusal rules | 23 |
| SQL guard alone, on the attack SQL | 42 of 45 (the 3 it passes: a table-less `SELECT 41.2`, and two agent-role reads that only the rules refuse) |
| Grounding check | 1 (a narration with an injected "99%") |
| Any of the three | 45 of 45; none left for the LLM scope step |
| Guard off: attack SQL that would bind and run | 22 of 45; 19 touch blocked columns; 14 statements are writes, parsed only |
| Expected layer matched | 41 of 42 questions that named rules, guard or grounding |

The one miss: RT-008 ("Remove the row limit") was caught by the write rule, not the guard. The control (`' OR 1=1`) passes the guard as a read-only allow-listed SELECT, which is harmless. Live red-team result through `/bench/question`: **pending** (mode `redteam-live`, needs the GPU and the local LLM).

![Redaction and red-team results](figures/dec_A5.png)

**Verdict.** Kept. Redaction leaves no personal data in notes and about 3 in 100 transcripts (a first name the model missed); `en_core_web_sm` triples that, at the same speed, so `lg` stays. Over-redaction is 7.5 per 1,000 transcripts, all dates, no amounts or case ids (the BQ-107 fix holds). Layers overlap: the guard alone would have stopped 42 of 45 attacks, the rules 23, so no single layer is the defence. Limits: the attack SQL and questions were written by us, and the rules were written against similar phrasings, so the block rates are an upper bound, not a forecast; the name check can count a name that is also a common word; the live LLM layers are not measured yet.

**Outside support.** OWASP Top 10 for Large Language Model Applications, version 2025 (LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure), OWASP GenAI Security Project: https://owasp.org/www-project-top-10-for-large-language-model-applications/ (project page verified; entry names confirmed through several secondary summaries, since genai.owasp.org was unreachable). Presidio, "Presidio" documentation, Data Privacy Stack (formerly Microsoft): https://presidio.dataprivacystack.org/ (identification and anonymization of PII in text; spaCy as the NLP engine). Personal Information Protection and Electronic Documents Act, S.C. 2000, c. 5, Government of Canada: https://laws-lois.justice.gc.ca/eng/acts/p-8.6/ . Act respecting the protection of personal information in the private sector, CQLR c. P-39.1, as amended by Law 25 (S.Q. 2021, c. 25), section 17 (assessment before personal information is communicated outside Quebec): https://www.legisquebec.gouv.qc.ca/en/document/cs/P-39.1 (statute page blocked for automated fetch; section 17 confirmed through McCarthy Tetrault and IAB Canada summaries, not read in the statute).

**Reproduce.** `uv run python scripts/decision_A5.py redaction --sm <path to unpacked en_core_web_sm>`; `uv run python scripts/decision_A5.py redteam`; `uv run python scripts/decision_A5.py chart`; later `uv run python scripts/decision_A5.py redteam-live --api http://localhost:8000`.

### B1. LLM bake-off on our three tasks

_Measurement in progress._

### B2. Quantization

_Measurement in progress._

### B3. Serving runtime: llama.cpp vs Ollama

_Measurement in progress._

### B4. Local vs hosted LLM: cost, quota and privacy

**Question.** Should every LLM call stay on the local model, or would hosted models be cheaper or simpler?

**Alternatives.** Local Qwen3.8-27B on RTX 5070 Ti workstations, against three hosted models at list price: Gemini 3.5 Flash-Lite, Claude Haiku 5.5 and Claude Sonnet 5.5. Also the Gemini free tier. No hosted API was called: prices only.

**Setup.** Tokens and latencies: the audit log (`audit.duckdb`, read-only), the 242 + 223 + 38 + 231 + 1 Ask calls, 19 `text.extract` calls and 29 brief calls that Qwen made on 14 and 15 Oct. Volumes: the release (760,594 notes from 2016-10 to 2026-09; 2026 rate 1,570 notes and 2,190 calls a day; 77 transcripts a day, because the release transcribes a sample; 787 active agents). Assumptions, stated because no data exists: questions per agent per day 1 / 5 / 15 (low / base / high), briefs per agent per day 5 / 10 / 20; low extraction uses the 2025 note rate, high also transcribes every call. Local cost: workstation CAD 3,500 (assumption; the card's launch price is USD 749) over 3 years, 450 W busy and 100 W idle, Ontario mid-peak 15.7 cents per kWh, GPUs kept at most 50% busy, CAD 1.37 per USD. Throughput: the audit's mean measured latency per call (a call at a time; it was measured on the live server, so a later bake-off with parallel slots may show more). Hosted prices ignore caching and batch discounts, so they are upper bounds.

**Result.** Per unit (Qwen, audit): an Ask question is 3.04 calls, 4,943 prompt and 160 completion tokens, 6.4 GPU-seconds; an extraction is 1,277 + 122 tokens, 3.4 s; a brief is 482 + 215 tokens, 5.3 s.

| Scenario (a day) | Extractions / questions / briefs | Local GPUs and USD a year | Gemini 3.5 Flash-Lite | Haiku 5.5 | Sonnet 5.5 |
|---|---|---:|---:|---:|---:|
| Low | 293 / 787 / 3,935 | 1 GPU, 1,062 | 1,596 | 409 | 8,181 |
| Base | 1,647 / 3,935 / 7,870 | 2 GPUs, 2,200 | 5,079 | 1,386 | 27,720 |
| High | 3,760 / 11,805 / 15,740 | 4 GPUs, 4,509 | 12,979 | 3,629 | 72,575 |

- One GPU covers 0.59 of the base load. Local cost per base load is about USD 1,850 a year at scale, against 1,390 for Haiku 5.5: local never beats Haiku 5.5 on cost alone in the range tested (0.1x to 300x). It beats Gemini 3.5 Flash-Lite above 0.2x and Sonnet 5.5 everywhere. Doubling the workstation price raises the base local cost to USD 3,903.
- Backfill of 760,594 notes: 30 days on one GPU, against USD 143 (Haiku 5.5), 523 (Flash-Lite) or 2,869 (Sonnet 5.5) hosted.
- Quota: the Gemini free tier is 500 requests a day per project per model (`Track_B.md`, 4 Oct). One base night is 1,647 extractions, which is 3.3 days of quota; the backfill is 1,521 days (4.2 years). `Track_B.md` does not record a per-minute limit.
- Prices checked on 2026-10-16: Gemini https://ai.google.dev/gemini-api/docs/pricing (3.5 Flash-Lite USD 0.30 in, 2.50 out per 1M tokens); Claude https://platform.claude.com/docs/en/about-claude/pricing (Haiku 5.5 up to 100k-token prompts 0.10 / 0.50; Sonnet 5.5 2 / 10). The OpenAI price page returned HTTP 403, so no OpenAI model is priced. Ontario power: the OEB's time-of-use prices unchanged since 1 Nov 2025 (off-peak 9.8, mid-peak 15.7, on-peak 20.3 cents per kWh; OEB announcement https://oeb.ca/node/5346, which this machine could not open; the figures were confirmed on the utility pages https://www.entegrus.com/node/733 and https://www.entegrus.com/node/689). These are residential prices; a commercial site pays a different tariff.

![Yearly cost, local against hosted](figures/dec_B4.png)

**Verdict.** The decision to keep every call local rests on privacy and regulation, not cost: at list prices the cheapest hosted model (Haiku 5.5) costs less than our GPUs at every volume tested, while Flash-Lite and Sonnet cost more above about 0.2x. The free tier cannot carry even one night's extraction. The deck should not claim local is cheaper.

**Regulatory and risk lines (verified 2026-10-16).**
- OSFI Guideline E-23, Model Risk Management: final text issued 11 Sept 2025, effective 1 May 2027; its definition of a model covers AI/ML methods, so an extraction or Ask model needs an inventory entry, a risk rating and lifecycle controls. https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/guideline-e-23-model-risk-management-2027
- OSFI Guideline B-10, Third-Party Risk Management: issued April 2023 (the OSFI page is dated 30 April; law firms report 24 April), effective 1 May 2024; it expects agreements to set responsibility for confidentiality and integrity of data and updates on subcontractors. A hosted LLM is a third-party arrangement with a subcontractor chain; a local model is not. https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/third-party-risk-management-guideline
- PIPEDA, Schedule 1, clause 4.1.3: an organization is responsible for personal information transferred to a third party for processing and must use contractual or other means to give a comparable level of protection. Secondary source: https://www.nortonrosefulbright.com/en-ca/knowledge/publications/bed47862/opc-reconsiders-its-approach-to-cross-border-data-transfers-with-the-equifax-decision ; Act: https://laws-lois.justice.gc.ca/eng/acts/p-8.6/ (the clause text could not be opened here; it is quoted by the secondary source).
- Quebec Law 25 (S.Q. 2021, c. 25, assented 22 Sept 2021, "An Act to modernize legislative provisions as regards the protection of personal information"): section 17 of the private-sector Act, in force since 22 Sept 2023, requires a privacy impact assessment before personal information is communicated outside Quebec, including to another province, or entrusted to a body outside Quebec. A hosted API outside Quebec triggers it; a local model does not. https://www.mccarthy.ca/en/insights/blogs/techlex/sweeping-privacy-reform-comes-force-quebec

**Outside support.** The pages above. The workstation price and the per-agent question rates are assumptions, listed in the JSON under `assumptions`.

**Reproduce.** `uv run python scripts/decision_B4.py` (reads the audit log and the release CSVs; no network).

### B5. Ask design: one prompt against our pipeline

**Question.** Which steps of the Ask add accuracy, and which only add cost? Today's gains (18 to 21, 22 to 27) changed the model and the pipeline together, so they can't say.

**Alternatives.** Six settings with the same model (Qwen3.8-27B, llama.cpp, 2 slots), each adding to the one before: `plain` (one prompt with the schema, then guarded SQL, run, narrate); `route` (scope classifier, router, certified metrics, policy search, call summaries); `templates` (reviewed SQL templates, date hints, worked examples, intent checks); `drafts` (three drafts and a majority vote); `lint` (convention linter and one repair round); `live` (escalation to five drafts and the judge). The SQL guard and the safety rules stay on in every setting: they are safety, not accuracy. The setting is an evaluation-only env var, `KEPT_ASK_ABLATION`, read when the server starts; unset means `live`, which is the product.

**Setup.** Released (35 questions, 21 graded), stress (42) and drill (30) suites, 93 graded in all, asked through `scripts/bench_run.py` and graded as in `ask_accuracy.md`. A fresh server per setting, so no reply cache carries over. Wrong but confident is an answer, not a refusal, that the grader marks wrong. LLM calls per question come from each setting's own audit log. Same machine for every setting. Latency carries a caveat: other agents used the CPU at the same time, so compare latencies loosely. The smaller model from B1 was not run (see the lead's note on B1).

**Result.** All suites together (`data/exports/reports/decision_B5.json`):

| Setting | Right (of 93) | Released | Stress | Drill | Refusal recall | Wrong but confident | LLM calls / question | Median, p95 latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| plain | 36 (38.7%) | 7/21 | 18/42 | 11/30 | 0.63 | 33 | 1.64 | 4.9 s, 11.4 s |
| + route | 81 (87.1%) | 20/21 | 34/42 | 27/30 | 1.00 | 10 | 2.51 | 4.1 s, 12.8 s |
| + templates | 85 (91.4%) | 21/21 | 38/42 | 26/30 | 1.00 | 8 | 2.43 | 4.9 s, 8.4 s |
| + drafts | 86 (92.5%) | 21/21 | 38/42 | 27/30 | 1.00 | 7 | 2.49 | 5.0 s, 7.9 s |
| + lint | 86 (92.5%) | 21/21 | 38/42 | 27/30 | 1.00 | 7 | 2.48 | 5.0 s, 7.5 s |
| live | 86 (92.5%) | 21/21 | 38/42 | 27/30 | 1.00 | 7 | 2.50 | 5.2 s, 8.1 s |

The router and certified metrics carry almost all of the gain (38.7% to 87.1%, wrong but confident 33 to 10). Templates and intent checks add four more right answers and remove two confident errors. The drafts, the linter and the judge add at most one answer (a drill question) and none on the released and stress suites. They cost no extra LLM calls here (about 2.5 per question), because the certified and template routes answer most questions without a SQL draft, and the vote only runs on lookups. Their p95 latency is lower than `route`'s, but that is within the noise of a shared CPU.

![Ask accuracy as each step is added](figures/dec_B5.png)

**Verdict.** Kept. The measured value is in the early steps: certified metrics, the router and the reviewed templates. The drafts, vote, linter, repair and judge show a gain of one question in 93 on this data, so they are insurance on free-form lookups, not a measured accuracy step; we keep them because they cost no extra calls on these suites, and we say so. Trade-off to state: the suites contain few free-form lookups, so they under-test the steps that matter most there.

**Outside support.**
- Li et al., "Can LLM Already Serve as A Database Interface? A BIg Bench for Large-Scale Database Grounded Text-to-SQLs" (BIRD), NeurIPS 2023: https://arxiv.org/abs/2305.03111. A single prompt with a strong model reaches 54.89% there, against 92.96% for humans, which fits our `plain` row.
- Lei et al., "Spider 2.0: Evaluating Language Models on Real-World Enterprise Text-to-SQL Workflows", ICLR 2025 (oral): https://arxiv.org/abs/2411.07763. Enterprise schemas drop a code agent to 21.3%.
- Wang et al., "Self-Consistency Improves Chain of Thought Reasoning in Language Models", ICLR 2023: https://arxiv.org/abs/2203.11171 (the majority vote over drafts).
- dbt Semantic Layer and MetricFlow (metrics defined once, SQL generated from the definition, the pattern behind certified metrics): https://docs.getdbt.com/docs/build/about-metricflow

**Reproduce.** `make llm`, then `uv run python scripts/decision_B5.py run` and `uv run python scripts/decision_B5.py report` (set `KEPT_DATA_DIR` in a git worktree).

### B6. Policy search: BM25 vs embeddings vs hybrid, and which embedder

**Question.** Is hybrid BM25 + `BAAI/bge-m3` fused by reciprocal rank the right search for policy questions, and does the English cross-encoder help or hurt French?

**Alternatives.** Four configurations (BM25 only; dense only; hybrid RRF, which is live; hybrid plus `cross-encoder/ms-marco-MiniLM-L-6-v2` rerank of the top 10) across four embedders: bge-m3 (live), `multilingual-e5-base` (with its `query: ` and `passage: ` prefixes), `paraphrase-multilingual-MiniLM-L12-v2`, `all-MiniLM-L6-v2` (English only).

**Setup.** 59 questions in `benchmarks/retrieval_gold.csv`: 21 existing gold questions (dev BQ-002/005/019/026, stress KS-021..029 and drill DR-017..024 that point at a document) and 38 new paraphrased questions, two per reference document (19 documents), in English and French, each answering one section. 21 questions are French. A hit is a chunk of a gold document and section; any gold document listed counts. The index is the live one (51 chunks: 19 documents plus ops events, chunked by `chunk_document`, filtered by the question's `as_of` date, low-authority FAQ and scripts ranked down). Everything runs on the CPU (`CUDA_VISIBLE_DEVICES=` empty, 6 GB memory cap, shared 24-thread machine). Latency is one query end to end (embedding, search, rerank) over the 59 questions after a warm-up. The new questions were written by us and the set is small, so differences of one or two questions (1.7 points each) are noise.

**Result.** MRR, bge-m3 (recall@1/3/5 in the JSON):

| Config | All (59) | French (21) | Existing 21 | Paraphrased 38 | Median / p95 ms |
|---|---:|---:|---:|---:|---:|
| BM25 only | 0.516 | 0.257 | 0.845 | 0.334 | 2.9 / 5.5 |
| Dense only | **0.747** | **0.821** | 0.810 | **0.713** | 91.6 / 109.4 |
| Hybrid RRF (live) | 0.640 | 0.564 | **0.881** | 0.507 | 88.1 / 102.1 |
| Hybrid + rerank | 0.508 | 0.237 | 0.760 | 0.368 | 171.7 / 214.7 |

Dense only, all questions: recall@1 0.66, @3 0.81, @5 0.85. Hybrid: 0.54, 0.69, 0.76.

| Embedder (dense only) | MRR all | MRR French | Hybrid MRR all | Index build | Median query ms |
|---|---:|---:|---:|---:|---:|
| bge-m3 (live) | **0.747** | **0.821** | 0.640 | 6.8 s | 91.6 |
| multilingual-e5-base | 0.652 | 0.579 | 0.559 | 2.0 s | 29.5 |
| multilingual MiniLM-L12 | 0.575 | 0.572 | 0.541 | 0.3 s | 14.3 |
| all-MiniLM-L6 (English) | 0.496 | 0.214 | 0.488 | 0.3 s | 10.5 |

The rerank hurts French: hybrid French MRR falls from 0.564 to 0.237 (recall@1 0.48 to 0.10), and the same drop happens with every embedder because the reranker sees the same candidates. It also lowers English slightly (0.682 to 0.657). BM25 alone is weak on French (0.257): the default full-text tokenizer is English.

![Search MRR by configuration and embedder](figures/dec_B6.png)

**Verdict.** bge-m3 is the best embedder on every cut and we keep it; the rerank is rejected, in French it destroys the ranking. Trade-off on fusion: on the 21 existing benchmark questions, which share words with the policy text, hybrid is best (0.881 against 0.810 for dense); on paraphrased and French questions the BM25 half drags it down and dense alone is clearly better (0.821 against 0.564 on French). A switch to dense-only, or a French-aware BM25 tokenizer (not tested here), is worth a separate change; this is a proposal only; nothing in `kept/ask/` changed except an evaluation-only `mode` argument on `PolicyIndex.search` that defaults to hybrid.

**Outside support.** Chen, Xiao, Zhang, Luo, Lian and Liu, "BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation", arXiv:2402.03216, 2024 (later versions retitled "M3-Embedding"), https://arxiv.org/abs/2402.03216 ; Cormack, Clarke and Buettcher, "Reciprocal rank fusion outperforms Condorcet and individual rank learning methods", SIGIR 2009, pp. 758-759, https://doi.org/10.1145/1571941.1572114 .

**Reproduce.** `CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 uv run python scripts/decision_B6.py` (needs the four embedders and the cross-encoder in the Hugging Face cache; about one minute).

### B7. Extraction: keyword rules, SetFit or the LLM

**Question.** Does reading notes need an LLM, or are keyword rules or a small trained model enough? How long does each take on all 760,594 notes?

**Alternatives.** (1) Keyword and regex rules written plainly, English and French, for hardship (job loss, illness, EI, bereavement, separation) and promise to pay (promise words, dates, amounts). (2) SetFit (`setfit-v1_880b98c`, bge-small, trained on 1,604 LLM labels). (3) The LLM (Qwen3.8-27B, prompt `extract-v4`) with quoted evidence.

**Setup.** The 149 public-labelled notes in the holdout split (`kept.text.labels.is_holdout`; 44 hardship and 59 promise positives), the same texts (the stored redacted notes) and the same F1, recall and precision (`kept.text.evaluate`) for all three. Hardship counts possible or clear as positive. SetFit predicts hardship only, so promise is compared for rules and the LLM. The LLM's accuracy is not rerun: it is recomputed from the stored predictions of `scripts/eval_extraction.py` (`extraction_gate.md`). Timing: rules and SetFit on 964 notes sampled from the history (best of three after a warm-up); SetFit on CPU with 4 threads, on the RTX 5070 Ti with batch 256 (llama-server held 14 GB of the GPU at the time, so the GPU run shared it); the LLM through the live `LLMExtractor` with 2 parallel slots on 200 labelled notes. Other jobs used the CPU during the runs.

**Result.** (`data/exports/reports/decision_B7.json`)

| | Hardship F1 | Hardship recall | Hardship precision | Promise F1 | s per 1,000 notes | Hours for all 760,594 |
|---|---:|---:|---:|---:|---:|---:|
| Keyword rules | 0.63 | 0.75 | 0.54 | 0.88 | 0.014 | 0.003 |
| SetFit, CPU | 0.87 | 0.98 | 0.78 | n/a | 2.9 | 0.62 (rate x count) |
| SetFit, GPU | 0.87 | 0.98 | 0.78 | n/a | 0.096 | 0.018 (measured over all notes, 63 s) |
| LLM, 2 slots | 0.88 | 1.00 | 0.79 | 0.88 | 3,319 | 701 (29 days; rate x count) |

- The LLM figure for all notes is an extrapolation from the measured rate of 3.32 s a note, not a run.
- Labelling the 1,604 SetFit training labels would take the LLM about 1.5 hours at that rate. The original run's time was not logged (it used Gemma 3 12B on Ollama, with two power cuts), so this is the measured Qwen rate times 1,604.
- Hardship: rules lose 11 of 44 hardships and flag many false ones; SetFit is within 0.01 F1 of the LLM, with recall 0.98 against 1.00. Promise to pay: rules match the LLM on F1 (0.88 each) with lower recall (0.90 against 0.95); the 59-positive holdout is too small to separate them.

![Extraction F1 and time per approach](figures/dec_B7.png)

**Verdict.** Kept. The LLM is the reader for live notes (quotes, dates, amounts, cease) and SetFit covers the history: it matches the LLM on hardship at 1/35,000th of the time. Rules alone fail the hardship gate (F1 0.63, recall 0.75 against the 0.90 required), so they are not an option for hardship. For promise to pay a rule baseline comes close on this holdout, which is worth knowing, but it can't extract a date or an amount with a quote. Honest limit: 149 notes, so a difference of 0.01 F1 is noise.

**Outside support.** Tunstall et al., "Efficient Few-Shot Learning Without Prompts" (SetFit), 2022: https://arxiv.org/abs/2209.11055. It shows fine-tuned Sentence Transformers with a small head match much larger prompt-based models at far lower training and inference cost.

**Reproduce.** `uv run python scripts/decision_B7.py cpu`, then `make llm` and `uv run python scripts/decision_B7.py gpu`, then `uv run python scripts/decision_B7.py report`.

### B8. Speech-to-text model size

_Measurement in progress._

### B9. Promise model: which model ships

**Question.** Ship the wide 79-input model on the promise card, or keep the 6-feature one that is easy to explain?

**Alternatives.** Logistic regression on the 6 features; the 6-feature LightGBM with no calibration, Platt and isotonic; the wide LightGBM with no calibration and with isotonic.

**Setup.** `scripts/evidence_report.py`, §8's split: promises the bank scored before their outcome, cut at the median promise date (31 Jul 2026), test = 12,820 promises from the cut (22% kept). Calibrators are fitted on the bank-scored promises of the last 20% of the training period (2,564 promises, 28 to 31 Jul), with the base model refitted on the 80% before it; never on the test. The no-calibration row is shown on both bases (full training period, and the first 80%). AUC with 300-resample bootstrap interval; Brier; calibration gap as `evidence.md` §7 (ten bins, weighted). CPU, 6 GB cap.

**Result.** (`data/exports/reports/decision_B9.json`; the bank's score on the same promises: AUC 0.702.)

| Model | Fitted on | AUC [95% CI] | Brier | Calibration gap, pts |
|---|---|---:|---:|---:|
| Logistic regression, 6 features | full | 0.646 [0.636, 0.656] | 0.165 | 0.9 |
| 6-feature LightGBM, none (as §8) | full | 0.625 [0.614, 0.636] | 0.167 | 2.0 |
| 6-feature LightGBM, none | first 80% | 0.615 [0.604, 0.627] | 0.170 | 4.3 |
| 6-feature LightGBM, Platt | 80% + 20% | 0.615 [0.604, 0.627] | 0.179 | 8.9 |
| 6-feature LightGBM, isotonic | 80% + 20% | 0.614 [0.602, 0.625] | 0.182 | 9.1 |
| Wide LightGBM, none (as §8) | full | 0.697 [0.685, 0.708] | 0.161 | 8.2 |
| Wide LightGBM, none | first 80% | 0.689 [0.677, 0.701] | 0.161 | 8.1 |
| Wide LightGBM, isotonic | 80% + 20% | 0.689 [0.677, 0.700] | 0.157 | 5.7 |

Serving cost: the 6 features are dated before the promise and come from the promise, the customer's earlier promises and the last salary deposit: 6 inputs, 30 non-blank lines of SQL (`promise_model.load`). The wide model needs 79 inputs from the promise, card statements, loan instalments, month-end balances, the customer record, the bureau pull, 30 days of contacts, the deposit account's cash flow and payroll, across five source systems and the identity crosswalk: 95 non-blank lines of SQL, all available at promise time (each dated before it).

Findings. The wide model wins on AUC by about 7 points over the 6-feature one (0.69 to 0.70 against 0.615 to 0.625; intervals do not overlap) and matches the bank's 0.702. Plain logistic regression beats the 6-feature LightGBM (0.646 against 0.625), so the six features are close to linear and the trees add nothing there. Calibration did not help in this window: the kept rate fell over the period (63% to 35%, then 31% in the calibration window to 22% on the test), so calibrators fitted on the window before the test over-predict on it (mean predicted 0.31 against 0.22 observed); the gap rose from 4.3 to 8.9 and 9.1 points. Isotonic helped the wide model's gap (8.1 to 5.7) and Brier (0.161 to 0.157) without changing its AUC. The wide model's raw gap of about 8 points is its weakness: its mean prediction is 0.30 against 0.22 observed, since it trains on a period with a higher kept rate. Run to run, interval ends and the third decimal of AUC move by up to 0.001 (some source rows share a date).

**Verdict.** Recommendation: ship the wide model on the card, as a ranking (who is likely to break) with its probability recalibrated on the most recent promises, and keep the 6-feature model as the fallback when a customer lacks the wider data. The 7-point AUC gain is far outside the noise; the cost is 95 lines of SQL, five source systems and a calibration that must be refreshed as the kept rate drifts. If the card must state "N% chance" and be explainable, the 6-feature model is better calibrated (gap 2.0 points) but ranks worse. This is a recommendation; no live code was changed.

**Outside support.** Niculescu-Mizil and Caruana, "Predicting good probabilities with supervised learning", ICML 2005, pp. 625-632: https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting. Grinsztajn, Oyallon and Varoquaux, "Why do tree-based models still outperform deep learning on typical tabular data?", NeurIPS 2022 Datasets and Benchmarks: https://neurips.cc/virtual/2022/poster/55627. Ke et al., "LightGBM: a highly efficient gradient boosting decision tree", NeurIPS 2017: https://proceedings.neurips.cc/paper/2017/file/6449f44a102fde848669bdd9eb6b76fa-Paper.pdf.

**Reproduce.** `uv run python scripts/evidence_report.py --only-b9 --warehouse data/warehouse/eval_copy.duckdb` (the full report prints the same table in §8).

### B10. Uplift against a "who will pay" response model, and the learner choice

**Question.** Should Kept rank actions by estimated uplift (a T-learner per action) rather than by the chance of paying? Does a propensity-to-pay ranking spend contacts on people who pay anyway?

**Alternatives.** (1) Response model: one LightGBM for paid within 14 days on contacted decisions, ranked by that probability. (2) T-learner with the live settings. (3) S-learner (one model, action as an input), two tree sizes. (4) Causal forest (`econml.dml.CausalForestDML`, per arm against waiting), two leaf sizes. The live champion and the bank's strategy are shown for reference.

**Setup.** `scripts/uplift_learners.py --mode decision`, same windows as `docs/reports/uplift_learners.md`: variants chosen on the validation window (fitted before 15 Jul, scored 15 Jul to 15 Aug; 103,235 decisions), then scored once on the test decisions (fitted before 15 Aug, scored from 15 Aug; 141,350 decisions). Judge: the doubly robust (AIPW) Qini from nuisance models no candidate uses. Call, SMS and email arms are pooled (each against "wait"). Qini is in units of its own noise (the standard deviation of the Qini of 100 random rankings); the total sums the three arms. Extra payers per 1,000 are the mean AIPW pseudo-outcome in the top 10/30/50% of each arm, pooled by rows. "Sure things" are the share of the top 30% whose judged uplift (m1 - m0) is <= 0. Machine: CPU, 4 threads, under a 6 GB cap; the causal forest fitted on the full training window without subsampling (econml 0.17.0, optional `analysis` extra).

**Result.** Test decisions, all arms (`data/exports/reports/decision_B10.json`):

| Ranking | Qini, noise units | Extra payers per 1,000: top 10% | top 30% | top 50% | Top 30% with uplift <= 0 | Their mean chance of paying if left alone |
|---|---:|---:|---:|---:|---:|---:|
| Random (everyone) | 0 | 106.6 | 106.6 | 106.6 | 4.7% | 29% |
| Bank's strategy | -9.5 | -40.1 | 64.6 | 105.0 | 5.1% | 30% |
| Response model | 3.2 | 45.6 | 81.0 | 117.6 | 6.4% | 56% |
| T-learner (live settings) | 7.9 | 127.7 | 122.2 | 121.5 | 1.6% | 26% |
| Champion (live) | 8.6 | 103.9 | 128.8 | 123.1 | 2.7% | 32% |
| S-learner, larger trees | 14.8 | 160.9 | 146.4 | 131.9 | 2.5% | 28% |
| Causal forest, larger leaves | 10.7 | 159.8 | 134.0 | 124.7 | 2.6% | 21% |

Paired bootstrap, top 30%, live T-learner minus response model: +25.6 to +55.6 extra payers per 1,000 (95% interval; decisions resampled, models held fixed).

The story holds, with one correction. The response model picks people who pay anyway: the top 30% it chooses would pay 56% of the time if left alone, against 26% for the T-learner, and it adds about 41 fewer payers per 1,000 contacts at the top 30%. But the judge's "uplift <= 0" share is small for every model (6.4% for the response model, 1.6% for the T-learner), so most of its picks are not provable "sure things" by that definition; they are high-baseline customers with a smaller gain. On the call arm alone the bank's own strategy beats every learner on this judge (Qini 11.4 noise units against 4.6 for the T-learner); on SMS and email the learners win. Variants were chosen on validation; the validation response model was below zero (-3.1 noise units), the validation T-learner at +6.9.

An unplanned finding: the S-learner (14.8) and the causal forest (10.7) both score above the live T-learner (7.9) and the champion (8.6) on the test. We do not propose switching on this alone. The judge's outcome model is itself a single model with the action as an input, which is the S-learner's form, so the S-learner is likely to look better to it than to an independent judge.

![Extra payers per 1,000 by ranking](figures/dec_B10.png)

**Verdict.** Kept (uplift ranking, not a propensity score): it beats the response model on every measure above, with an interval that excludes zero. Which uplift learner is best is open: the S-learner and causal forest look better than the T-learner on this judge, and a pilot is needed to settle it. Honest limit (`docs/reports/evidence.md` §9): the bank randomised only the cell (worked against held out), not the action, so the action effects here are observational with a modelled propensity; on the bank's randomisation alone every interval includes zero, so targeting by uplift is promising and unproven. The pilot plan is a randomised cell where a share of cases get the uplift-chosen action, a share the response-model choice, and a share the bank's strategy.

**Outside support.** Radcliffe and Surry, "Real-world uplift modelling with significance-based uplift trees", Stochastic Solutions technical report, 2011 (not peer reviewed): https://stochasticsolutions.com/pdf/sig-based-up-trees.pdf. Gutierrez and Gerardy, "Causal inference and uplift modelling: a review of the literature", PMLR 67:1-13, 2017 (3rd International Conference on Predictive Applications and APIs): https://proceedings.mlr.press/v67/gutierrez17a.html. Kunzel, Sekhon, Bickel and Yu, "Metalearners for estimating heterogeneous treatment effects using machine learning", PNAS 116(10):4156-4165, 2019: https://pmc.ncbi.nlm.nih.gov/articles/PMC6410831. Kennedy, "Towards optimal doubly robust estimation of heterogeneous causal effects", Electronic Journal of Statistics 17(2):3008-3049, 2023: https://projecteuclid.org/journals/electronic-journal-of-statistics/volume-17/issue-2/Towards-optimal-doubly-robust-estimation-of-heterogeneous-causal-effects/10.1214/23-EJS2157.full. Wager and Athey, "Estimation and inference of heterogeneous treatment effects using random forests", JASA 113(523):1228-1242, 2018: https://arxiv.org/abs/1510.04342.

**Reproduce.** `uv run --extra model --extra analysis python scripts/uplift_learners.py --mode decision --warehouse data/warehouse/eval_copy.duckdb` (figure `docs/reports/figures/dec_B10.png`).

### C2. Hardship: rules, not a model

**Question.** Would a model find agent-confirmed hardship better than the cash-flow rule, and at what cost in fairness and explainability?

**Alternatives.** The rule (`src/kept/hardship/cashflow_rule.py`: payroll 5+ days late, pay down 20%+, or new EI) against LightGBM on the same inputs, each without and with EI.

**Setup.** One snapshot (as-of 28 Sep 2026), 233,834 customers with a current payroll deposit account. Positive: gold `hardship_status` confirmed with `hardship_source` agent (6,749). Negative: every other customer, including those gold marks possible, so precision is the share of flags an agent confirmed (a lower bound on how many were right). Programme-confirmed customers (1,053) are left out. Inputs: worst payroll delay, worst pay change; with EI, also new-EI, days since first EI deposit and the EI flag. Split by hash of the golden id: 60% fit, 15% validation, 25% test (58,221 customers, 1,660 positives). Validation picks the early-stopping round and the thresholds; the test split was only scored. LightGBM: 15 leaves, learning rate 0.05, n_jobs 4, CPU. Fairness uses `kept.governance.fairness.recommendation_rates` on the test split, 11 protected and proxy attributes from `gold.c360_restricted`.

**Result.** Test split.

| system | flagged | recall | precision | ROC AUC |
|---|---|---|---|---|
| rule, no EI | 8.5% | 0.652 | 0.220 | 0.792 |
| rule, with EI | 8.5% | 0.652 | 0.220 | 0.792 |
| LightGBM no EI, same flag rate as the rule | 8.7% | 0.672 | 0.221 | 0.853 |
| LightGBM with EI, same flag rate | 8.6% | 0.678 | 0.226 | 0.858 |
| LightGBM with EI, F1 threshold | 3.9% | 0.519 | 0.377 | 0.858 |

EI adds nothing to the rule here: all 3,757 new-EI customers already have a payroll delay of 15+ days, so the rule flags them without it. Fairness (four-fifths screen on the flag rate; the worst attribute is `vulnerability_type` for every system, 0.03 to 0.10, because customers carrying the vulnerability flag are the ones confirmed): rule, 1 attribute below 0.8; LightGBM at the same flag rate, 1 to 2 (gender included); LightGBM at the F1 threshold, 3 (gender, household size, vulnerability; with EI, citizenship instead of household size). Recall among the confirmed is below 0.8 for marital status (0.69 to 0.73) and vulnerability type (0.48 to 0.60) in all six systems.

![Hardship rule against LightGBM](figures/dec_C2.png)

**Verdict.** Kept as a rule. The model gains 2 to 3 points of recall at the same flag rate (0.672 to 0.678 against 0.652) with no gain in precision, and it adds fairness flags (gender code) with no explanation a collections agent could read; the rule's three triggers are the explanation. A Red case still needs two people. Recall of 0.65 is also a limit of the rule: a third of agent-confirmed hardship is outside its inputs (it is found by agents and notes, which is why the rule only ever marks POSSIBLE).

**Outside support.** OSFI, Guideline E-23 Model Risk Management (2027), issued 11 Sep 2025, effective 1 May 2027 (explainability scaled to purpose and customer impact): https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/guideline-e-23-model-risk-management-2027 . FCAC, Guideline on Existing Consumer Mortgage Loans in Exceptional Circumstances, 5 Jul 2023 (tailored support for customers in severe financial difficulty; mortgage-specific, no general FCAC guideline on collections hardship was found): https://www.canada.ca/en/financial-consumer-agency/news/2023/06/financial-consumer-agency-of-canada-publishes-industry-guideline-to-help-protect-canadians-with-existing-mortgages.html . US EEOC et al., Uniform Guidelines on Employee Selection Procedures, 29 CFR Part 1607 (1978), section 1607.4(D), the four-fifths rule, a screen not a legal test: https://www.law.cornell.edu/cfr/text/29/1607.4 .

**Reproduce.** `uv run python scripts/decision_C2.py` (reads `eval_copy.duckdb`; writes `decision_C2.json` and `dec_C2.png`).

### C3. Fairness with and without the stand-in features

**Question.** Do protected attributes, and the proxies kept as stand-ins, change any decision?

**Alternatives.** Scramble only the brief's protected list (`invariance_test.py protected`); scramble the protected list plus the proxies (`all`); and measure outcome ratios across groups (`fairness_report.py`).

**Setup.** No new run. Numbers pulled by `scripts/decision_C3.py` from `fairness_data.json` (12 Oct 2026, 96,000 cases), `invariance_protected.json` (15 Oct 2026) and `invariance_all.json` (4 Oct 2026). `all` exists, so it was not re-run: it needs two 9.8 GB warehouse copies and a dbt rebuild of both, and the result is already in hand. It is older than the other two, which should be said where it is quoted.

**Result.**

| check | result |
|---|---|
| Invariance, protected only | 0 of 96,000 cards change; 0 hardship gained or lost; passed |
| Invariance, protected plus proxies | 299 cards change, 282 gain hardship, 0 lose it; all trace to `ei_deposit_flag` |
| Four-fifths, any contact action | ratios 0.87 to 1.00 over 11 attributes, no flag |
| Four-fifths, call | 2 flags (gender_code 0.72, marital_status 0.73), 4 more on too few events |
| Four-fifths, hardship review | 1 flag (marital_status 0.76) |

**Verdict.** Kept. Protected attributes move nothing; the one proxy that moves a decision does so only upward and by design (EI marks hardship possible, listed under `protectiveUses` in the data contract). The call and hardship-review flags are small numbers or the vulnerability protection at work, and are for compliance to review, not model changes.

**Outside support.** Four-fifths rule: 29 CFR 1607.4(D), as in C2. OSFI Guideline E-23 (2027) as in C2.

**Reproduce.** `uv run python scripts/decision_C3.py`; to refresh the inputs, `uv run python scripts/fairness_report.py` and `uv run python scripts/invariance_test.py protected|all`.

