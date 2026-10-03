# Track B: Ask

Person: Garimella Sai Abhishek · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 3 done; G1 check for B done (guard on real silver). G1 opens when C reports Phase 2.
- Working on: nothing
- Waiting on: C's Phase 2 stop message (G1), then G2

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

## Decisions and changes from the plan
- `generate_candidates` gained a required `question: RedactedText` keyword: the intent alone doesn't carry what the user asked, and the LLM needs it. Nothing else calls it.
- Refusal labels for the hidden questions: the local scorecard only covers the dev split. A dev case's `should_refuse` is "gold_answer starts with `Refuse`" (BQ-018, BQ-024, BQ-031). Test-split questions can't be scored here; `kept benchmark` still answers them and writes the CSV, and the organisers grade it.
- Tolerances the scorer can't parse ("direction of effect", "exact count, ±1 CAD"): `parse_tolerance` keeps raising `ValueError`; the scorer will catch it and mark the case manual (not counted in accuracy) instead of guessing. Proposed rule: "direction of effect" = same sign as the gold answer; "exact count, ±1 CAD" = count equal and amount within 1.
- The service sends metric SQL through `guard_sql` as well as lookup SQL, so one rule covers every query that runs.
- Policy questions refuse politely (`DATA_UNAVAILABLE`) until Phase 4 builds `PolicyIndex`.
- `SqlPolicy` gained an optional `table_columns` (additive shared-contract change, agreed in chat): a star is refused over a table with a blocked column or with unlisted columns. Nobody else imports `SqlPolicy`.
- Test changes: `tests/ask/conftest.py` policy fixture now passes `table_columns`; one `test_allowed_queries` row used `GOLD.COLLECTIONS_CASES`, which is not an allowed table, so it is now `SILVER.COLLECTIONS_CASES` (the row tests case-insensitivity).
- `route` takes an optional `as_of` date for relative dates.
- `load_benchmark` defaults `should_refuse`, `question_type`, `expected_tables`: the released `benchmark_questions.csv` has no such columns (only question_id, question_text, difficulty, metric_id, as_of_date, tolerance, split).
- `write_off_rate` has no certified query: its period bounds only the numerator, which one date column can't express.
- The gateway generates its own event ids (uuid4) so it doesn't depend on Track D's `new_event_id` stub.

## Open questions
- **Gold SQL drops a date format (matters for scoring).** The raw `account_monthly_snapshot.month_end_date` has 4 formats (ISO 90%, DD/MM 3.3%, MM/DD 3.3%, YYYYMMDD 3.3%). The reference SQL parses 3 and silently drops MM/DD rows, so its BQ-017 counts are ~6% lower than silver's (card 2,699 vs 2,870). Our roll rate on all rows: card 4.9 (gold 4.9), student_loc 25.0 (25.0), chequing 4.7 (5.0), mortgage 3.4 (3.6), auto 8.0 (7.4), personal 5.5 (4.9), unsecured 5.3 (5.9). The tolerance is ±0.5 pts, so some products would fail against the gold. We use all the data (correct); matching the gold means copying its omission. Team call.
- **For A (silver):** `dpd_bucket` / `current_bucket` are still the raw source values: 3.7% of rows in `account_monthly_snapshot`, `card_accounts` and `loan_accounts` disagree with `dpd` (461,396 snapshot rows), `dpd` is NULL on 8% (1.0M snapshot rows), and 1% of `collections_cases.current_bucket`. Ask computes buckets from `dpd`, but a clean derived column in silver would help everyone.
- Agents are only checked for case ids named in the question. A lookup like "average DPD by queue" is not filtered to `own_case_ids`, so an agent sees aggregates over every case. Decide at G1 whether agent lookups get a row filter (needs `assigned_agent_id` in the allowed columns) or are limited to metrics.
- Which silver tables does the Ask table list (G0) include? Certified SQL reads collections_cases, promises_to_pay, agents, contact_history, account_monthly_snapshot, card_accounts, loan_accounts, deposit_accounts.
- Refusal labels: only dev answers say "Refuse: …" (BQ-018, BQ-024, BQ-031). The scorecard needs a rule for the hidden ones. The docs say nothing (release README: "deciding which is part of the challenge").
- `parse_tolerance` raises on "direction of effect" and "exact count, ±1 CAD" (test questions). Decide how the scorer treats them.

## Log
Times are IST, newest first. Earlier entries are reconstructed from file and commit times.
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
