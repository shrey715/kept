# Track B: Ask

Person: Garimella Sai Abhishek · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 2 (started early against fakes, your call; G0 integration still waits on the other tracks)
- Working on: nothing, Phase 2 parallel tasks are done
- Waiting on: gate G0 (Phase 1 of A, C, D) and then G1

## Done
- `LiteLLMGateway.complete` (`kept/common/llm.py`) with retry test: 5 gateway tests pass.
- `load_metric_definitions`, `compile_metric` (`kept/ask/metrics.py`): tests pass.
- `kept/ask/certified.py`: reviewed SQL for 14 of 15 metrics. Run on the real release tables; promise-kept (BQ-034), average DPD (BQ-004), hardship (BQ-032), broken-rate by site (BQ-007), delinquency (BQ-012) and RPC by hour (BQ-011) match the dev gold answers. Roll rate matches for card; other products differ by a few accounts because the gold SQL drops `MM/DD/YYYY` rows (silver cleaning).
- `load_benchmark`, `parse_tolerance`, `score`, `write_answers` (`kept/ask/benchmark.py`): tests pass; CSV columns match the release template.
- PR: https://github.com/shrey715/kept/pull/3 (draft)

- Phase 2: `rule_check`, `check_scope`, `refusal_for`, `make_classifier` (S5) in `kept/ask/scope.py`; `route` in `kept/ask/router.py`; `guard_sql`, `execute_guarded` in `kept/ask/sql_guard.py`; `suppress_small_groups` in `kept/ask/privacy.py`. 153 Track B tests pass; CI command (`pytest --allow-stubs -m "not integration and not perf"`) 249 passed; ruff and mypy clean on Track B files.

## Decisions and changes from the plan
- `SqlPolicy` gained an optional `table_columns` (additive shared-contract change, agreed in chat): a star is refused over a table with a blocked column or with unlisted columns. Nobody else imports `SqlPolicy`.
- Test changes: `tests/ask/conftest.py` policy fixture now passes `table_columns`; one `test_allowed_queries` row used `GOLD.COLLECTIONS_CASES`, which is not an allowed table, so it is now `SILVER.COLLECTIONS_CASES` (the row tests case-insensitivity).
- `route` takes an optional `as_of` date for relative dates.
- `load_benchmark` defaults `should_refuse`, `question_type`, `expected_tables`: the released `benchmark_questions.csv` has no such columns (only question_id, question_text, difficulty, metric_id, as_of_date, tolerance, split).
- `write_off_rate` has no certified query: its period bounds only the numerator, which one date column can't express.
- The gateway generates its own event ids (uuid4) so it doesn't depend on Track D's `new_event_id` stub.

## Open questions
- Which silver tables does the Ask table list (G0) include? Certified SQL reads collections_cases, promises_to_pay, agents, contact_history, account_monthly_snapshot, card_accounts, loan_accounts, deposit_accounts.
- Refusal labels: only dev answers say "Refuse: …" (BQ-018, BQ-024, BQ-031). The scorecard needs a rule for the hidden ones. The docs say nothing (release README: "deciding which is part of the challenge").
- `parse_tolerance` raises on "direction of effect" and "exact count, ±1 CAD" (test questions). Decide how the scorer treats them.

## Log
Times are IST, newest first. Earlier entries are reconstructed from file and commit times.
- 2026-10-03 14:56: Phase 2 parallel tasks done; CI command green (249 passed).
- 2026-10-03 14:36: Phase 2 started early (user's call) while waiting on G0.
- 2026-10-03 14:35: `ask` extra installed; gateway and certified-SQL parse tests pass (42 Track B passed, contract 92 passed, lint clean). Phase 1 done; waiting on G0.
- 2026-10-03 14:03: certified SQL test and this file committed and pushed.
- 2026-10-03 14:01: lint clean; draft PR #3 opened.
- 2026-10-03 13:58: gateway, metrics, certified SQL and benchmark code committed; branch `track-b` pushed.
- 2026-10-03 13:32: dataset downloaded to `~/Documents/kept_dl` (started 13:18).
- 2026-10-03 ~13:10: Track B confirmed; plan read.
