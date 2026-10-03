# Track B: Ask

Person: Garimella Sai Abhishek · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: G3 prep done (code); full benchmark scorecard in `docs/benchmark_scorecard.md` (dev 78%, recall 100%)
- Working on: nothing; waiting for a Mistral key (Gemini's free quota is used up until ~05:30 IST)
- Waiting on: the new model key; G3 for the fairness run on real recommendations (D's `kept score` output)

## Done
- `LiteLLMGateway.complete` (`kept/common/llm.py`) with retry test: 5 gateway tests pass.
- `load_metric_definitions`, `compile_metric` (`kept/ask/metrics.py`): tests pass.
- `kept/ask/certified.py`: reviewed SQL for 14 of 15 metrics. Run on the real release tables; promise-kept (BQ-034), average DPD (BQ-004), hardship (BQ-032), broken-rate by site (BQ-007), delinquency (BQ-012) and RPC by hour (BQ-011) match the dev gold answers. Roll rate matches for card; other products differ by a few accounts because the gold SQL drops `MM/DD/YYYY` rows (silver cleaning).
- `load_benchmark`, `parse_tolerance`, `score`, `write_answers` (`kept/ask/benchmark.py`): tests pass; CSV columns match the release template.
- PR: https://github.com/shrey715/kept/pull/3 (draft)

- Phase 2: `rule_check`, `check_scope`, `refusal_for`, `make_classifier` (S5) in `kept/ask/scope.py`; `route` in `kept/ask/router.py`; `guard_sql`, `execute_guarded` in `kept/ask/sql_guard.py`; `suppress_small_groups` in `kept/ask/privacy.py`. 153 Track B tests pass; CI command (`pytest --allow-stubs -m "not integration and not perf"`) 249 passed; ruff and mypy clean on Track B files.

- Phase 3: `kept/ask/lookup.py` (`generate_candidates`, `normalize_result`, `majority_result`), `kept/ask/grounding.py`, `kept/ask/service.py` (`CollectionsAsk.ask`). 198 Ask tests pass; metric SQL also passes the guard on the 8-table Ask list. `/ask` route and its test were already on main (D). PR: https://github.com/shrey715/kept/pull/9

- G0 lines: reviewed PR #10; the 16 Ask tables cover B's SQL; picked Gemini Flash-Lite (`gemini/gemini-3.5-flash-lite`, `GEMINI_API_KEY`, Groq 8B as the spare) and posted the `.env.example` lines as a comment on #10.

- G1 check (17:16): built silver locally for the 8 Ask tables (`kept land`, then `dbt build`: 8 of 8 models OK, 44 s). `scripts/ask_g1_check.py` runs the dev answers' reference SQL through `guard_sql` with the real contract and real silver columns (`build_sql_policy`): all 12 allowed, 9 match the gold answers exactly; BQ-010 and BQ-011 match once written for silver (`channel_v2` and the date parsing are already cleaned there); BQ-017 is covered by the certified roll rate. All 14 certified metrics pass the guard and run on real silver.

- Phase 4 (local, not pushed): `effective_windows`, `chunk_document`, `PolicyIndex` (LanceDB full-text/BM25, current sections only, policy outranks FAQ and call scripts), `build_policy_index` in `kept/ask/policy.py`; `scripts/build_policy_index.py` builds `data/policy/lancedb` (45 chunks from 19 documents). The 5 dev policy questions (BQ-002, 005, 019, 026, 033) return the gold source first, and the BQ-026 trap (FAQ says 6 months, POL-COLL-004 v4.2 says 3) comes out right. The service answers policy questions with citations. 206 Ask tests pass.

- Phase 5 (PR #19): `kept benchmark` (answers CSV in the release template, dev scoring, LLM calls per question), `build_ask`, `lineage_violations` (+ CI check on the real contract), `recommendation_rates`. 1012 tests pass.
- First real-model baseline (19:01, Gemini 3.5 Flash-Lite, local silver, pass-through redactor on the synthetic benchmark questions): dev accuracy **67% (12 of 18)**, refusal recall 100% (3 of 3), 2.8 LLM calls per question. Went from 44% by: scope classifier that no longer refuses policy and regulatory questions, value lists and conventions in the lookup schema doc, per-metric filter hints for the router, `assignment_method` and `prior_broken_ptp_count` on the promise metrics, and a scorer that allows 2% on group sizes.

- G2 check (19:58): `kept benchmark` with the real Presidio redactor, the real Gemini model and the real gold C360 (`data/exports/c360_customer/part-000.parquet`, 1,052,300 rows, pulled from the shared folder) on 10 dev questions: **7 of 8 in scope correct (88%), refusals 2 of 2, 2.7 LLM calls per question**, 1 min 45 s. Lookups vary run to run (the 3-draft vote can disagree: BQ-010 passed once and was refused once).
- Found by the G2 run and fixed: relative dates ("today") came from gold's `refreshed_at` (build time, 3 Oct) instead of its `as_of_date` (the data snapshot, 28 Sep), so snapshot questions came back empty; the router over-grouped delinquency by `dpd_bucket` (removed from that metric: a rate per bucket is always 0% or 100%).
- **The gold I tested on is a pre-backfill export (3 Oct 18:48).** Its `hardship_status` (32,306 confirmed, 3,998 possible) comes from the agent flags, account programmes and the 50 real extractions only; the SetFit backfill has not landed. No hardship number from it is an answer. Rerun hardship questions after the backfill and a gold rebuild.

- G3 prep (23:30): updated gold (3 Oct 20:41, with the SetFit backfill) loaded; silver rebuilt; "match the key" decided with the user: BQ-003 groups 3+ prior broken promises, BQ-035 groups by the stored `current_bucket`. Full 35-question run: dev **78% (14 of 18)**, refusal recall 100%, 103 calls. Scorecard: `docs/benchmark_scorecard.md`. BQ-017 can't be matched from the Ask side (silver keeps no raw date format: needs one column from A); BQ-016 and BQ-022 (transcripts) skipped by decision; BQ-006 is an ambiguous reading.
- **Free-tier quota finding:** Gemini's free tier is 500 requests per day **per Google project per model** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), shared by every key in the project, and resets about 6 hours after the limit is hit. Today's tuning used it up (resets about 05:30 IST on 4 Oct). A second key from the same project does not help; a key from a different project, a different model, or a different provider does. For 4 Oct: keep about 250 calls for the 19:00 run.

## Decisions and changes from the plan
- `generate_candidates` gained a required `question: RedactedText` keyword: the intent alone doesn't carry what the user asked, and the LLM needs it. Nothing else calls it.
- Refusal labels for the hidden questions: the local scorecard only covers the dev split. A dev case's `should_refuse` is "gold_answer starts with `Refuse`" (BQ-018, BQ-024, BQ-031). Test-split questions can't be scored here; `kept benchmark` still answers them and writes the CSV, and the organisers grade it.
- Tolerances the scorer can't parse ("direction of effect", "exact count, ±1 CAD"): `parse_tolerance` keeps raising `ValueError`; the scorer will catch it and mark the case manual (not counted in accuracy) instead of guessing. Proposed rule: "direction of effect" = same sign as the gold answer; "exact count, ±1 CAD" = count equal and amount within 1.
- The service sends metric SQL through `guard_sql` as well as lookup SQL, so one rule covers every query that runs.
- Policy questions are answered from `PolicyIndex` when the service is given one, else refused politely (`DATA_UNAVAILABLE`).
- Policy search is keyword (BM25) search, not embeddings: no model download, and the 19 documents are small. Switch to embeddings only if paraphrased questions miss.
- `SqlPolicy` gained an optional `table_columns` (additive shared-contract change, agreed in chat): a star is refused over a table with a blocked column or with unlisted columns. Nobody else imports `SqlPolicy`.
- Test changes: `tests/ask/conftest.py` policy fixture now passes `table_columns`; one `test_allowed_queries` row used `GOLD.COLLECTIONS_CASES`, which is not an allowed table, so it is now `SILVER.COLLECTIONS_CASES` (the row tests case-insensitivity).
- `route` takes an optional `as_of` date for relative dates.
- `load_benchmark` defaults `should_refuse`, `question_type`, `expected_tables`: the released `benchmark_questions.csv` has no such columns (only question_id, question_text, difficulty, metric_id, as_of_date, tolerance, split).
- `write_off_rate` has no certified query: its period bounds only the numerator, which one date column can't express.
- The gateway generates its own event ids (uuid4) so it doesn't depend on Track D's `new_event_id` stub.

## Open questions
- **For C:** the real redactor turns a case id into a phone number: `CS-2026-614370` becomes `CS-<PHONE_NUMBER>`, so any question that names a case (BQ-016, 021, 022) loses its id before the Ask sees it. Local setup note: Hugging Face's spaCy wheels are the 3.7.x models (en 3.7.1, fr 3.7.0) run on spaCy 3.8 here (GitHub's 3.8.0 models downloaded at ~100 KB/s); the redaction output may differ slightly from C's machine.
- **Gold vs correct (team call).** Three dev gold answers differ from what the data supports: BQ-017 (the reference SQL drops the MM/DD date format), BQ-035 (gold counts use the raw `current_bucket` label; the dev note says ~4% are wrong and a strong answer recomputes from `current_dpd`, which gives 35,000 / 25,000 / ...), and BQ-003 (the gold folds 3 or more prior broken promises into one row). We compute from clean data. Matching the gold would mean copying its omissions. Not decided.
- **Transcript questions (BQ-016, 021, 022).** "Summarise the most recent recorded call" needs call transcripts, which are not an Ask table (PII). They are refused today (3 of 35 questions). Option: a redacted-transcript lookup fed by C's `text.transcripts`.
- **Quota.** 2.8 LLM calls per question on average (lookups cost more): a full 35-question run is about 100 calls, the extra 4 Oct questions about the same. Free-tier rate limits slow it (up to ~30 s on a throttled question) but did not fail it.
- **Gold SQL drops a date format (matters for scoring).** The raw `account_monthly_snapshot.month_end_date` has 4 formats (ISO 90%, DD/MM 3.3%, MM/DD 3.3%, YYYYMMDD 3.3%). The reference SQL parses 3 and silently drops MM/DD rows, so its BQ-017 counts are ~6% lower than silver's (card 2,699 vs 2,870). Our roll rate on all rows: card 4.9 (gold 4.9), student_loc 25.0 (25.0), chequing 4.7 (5.0), mortgage 3.4 (3.6), auto 8.0 (7.4), personal 5.5 (4.9), unsecured 5.3 (5.9). The tolerance is ±0.5 pts, so some products would fail against the gold. We use all the data (correct); matching the gold means copying its omission. Team call.
- **For A (silver):** `dpd_bucket` / `current_bucket` are still the raw source values: 3.7% of rows in `account_monthly_snapshot`, `card_accounts` and `loan_accounts` disagree with `dpd` (461,396 snapshot rows), `dpd` is NULL on 8% (1.0M snapshot rows), and 1% of `collections_cases.current_bucket`. Ask computes buckets from `dpd`, but a clean derived column in silver would help everyone.
- Agents are only checked for case ids named in the question. A lookup like "average DPD by queue" is not filtered to `own_case_ids`, so an agent sees aggregates over every case. Decide at G1 whether agent lookups get a row filter (needs `assigned_agent_id` in the allowed columns) or are limited to metrics.
- Which silver tables does the Ask table list (G0) include? Certified SQL reads collections_cases, promises_to_pay, agents, contact_history, account_monthly_snapshot, card_accounts, loan_accounts, deposit_accounts.
- Refusal labels: only dev answers say "Refuse: …" (BQ-018, BQ-024, BQ-031). The scorecard needs a rule for the hidden ones. The docs say nothing (release README: "deciding which is part of the challenge").
- `parse_tolerance` raises on "direction of effect" and "exact count, ±1 CAD" (test questions). Decide how the scorer treats them.

## Log
Times are IST, newest first. Earlier entries are reconstructed from file and commit times.
- 2026-10-03 23:30: Gemini free quota exhausted (500 per day per project per model); stopped the benchmark run; scorecard from the 23:11 run committed; waiting for a Mistral key.
- 2026-10-03 23:11: full 35-question run, dev 78% / recall 100%.
- 2026-10-03 23:02: pulled main, updated gold (20:41), rebuilt silver; matched the key on BQ-003 and BQ-035.
- 2026-10-03 19:58: G2 check done on real gold with the real redactor (7 of 8, refusals 2 of 2); fixed the as-of date and the delinquency router bug.
- 2026-10-03 19:25: pulled the gold C360 from the shared folder with rclone and loaded it into the local warehouse.
- 2026-10-03 19:16: PR #19 merged (kept benchmark, lineage check, fairness rates, Ask quality fixes).
- 2026-10-03 19:01: Phase 5 code done (PR #19); real-model dev baseline 67% / recall 100%; fixes to the classifier, schema doc and router hints.
- 2026-10-03 18:42: Gemini key in `.env` (gitignored); `gemini/gemini-3.5-flash-lite` verified with one call.
- 2026-10-03 17:46: Phase 4 parallel tasks done locally (policy index + service path); not pushed, C is merging.
- 2026-10-03 17:16: G1 check done on real silver (see Done); fixed the certified roll rate to use `dpd`, not the raw bucket; pushed.
- 2026-10-03 15:49: G0 review comment posted on PR #10 (Ask model, table list); Phase 3 done, stopped.
- 2026-10-03 15:47: Phase 3 parallel tasks done (PR #9); free Ask model research done, waiting on the pick.
- 2026-10-03 ~15:15: pulled main (all Phase 1 PRs merged), started Phase 3 per docs/NEXT_STEPS.md.
- 2026-10-03 14:56: Phase 2 parallel tasks done; CI command green (249 passed).
- 2026-10-03 14:36: Phase 2 started early (user's call) while waiting on G0.
- 2026-10-03 14:35: `ask` extra installed; gateway and certified-SQL parse tests pass (42 Track B passed, contract 92 passed, lint clean). Phase 1 done; waiting on G0.
- 2026-10-03 14:03: certified SQL test and this file committed and pushed.
- 2026-10-03 14:01: lint clean; draft PR #3 opened.
- 2026-10-03 13:58: gateway, metrics, certified SQL and benchmark code committed; branch `track-b` pushed.
- 2026-10-03 13:32: dataset downloaded to `~/Documents/kept_dl` (started 13:18).
- 2026-10-03 ~13:10: Track B confirmed; plan read.
