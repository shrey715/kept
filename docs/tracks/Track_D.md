# Track D: Model and UI

Person: Shreyas Deb · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: parallel tasks for Phases 1-5 done
- Working on: nothing; what's left needs other tracks (see Open questions)
- Waiting on: G0 (merge), then G2 for real features/labels, G3/G4 for real services

## Done
- `DuckDBAuditLog` + `new_event_id` (early provider, Q2): `tests/common/test_audit.py` 7/7. Branch `track-d`.
- Labels `paid_within`, `rolled_forward`, `roll_forward_rate`: label tests in `tests/nba/test_uplift_explain_labels.py` 14/14.
- Rules `hard_stops`, `permission_gate`, `allowed_actions`, `hardship_override`: `tests/nba/test_rules.py` 54/54.
- Access and masking: `tests/governance/test_access.py` 39/39.
- `/health`: `tests/app/test_api.py::test_health`.
- Phase 2: feature definitions + deny-list (`tests/features/test_definitions_and_store.py` 56/56); legacy code mapping from real data (`tests/nba/test_legacy.py` 17/17); tiers, hold-out, staleness, batch sample.
- Phase 2: dbt feature models (`dbt/models/features/`): spine, promise, contact, cohort, `case_features`. `tests/features/test_dbt_features.py` checks the SQL against the Python definitions point in time (4/4, needs dbt: see the test's docstring).

- Phase 3: `KeptContextBuilder` (S3, `tests/nba/test_context.py` 13/13); `TLearnerUplift` + Qini (uplift tests 8/8, incl. the LightGBM integration test); `FeastFeatureProvider` + `export_features` (`tests/features/test_feast_store.py` 4/4).

- Phase 4: Kept sizing and ranking (`test_sizing_ranking_tiers.py` 45/45); explanations with a fixed sentence for every model feature + TreeSHAP contributions; `KeptEngine` stages 1-7 (`test_engine.py` 15/15).
- Phase 5: `Releaser` + `cancel_pending` (`test_release.py` 34/34); `/cases/{id}/nba` and `/proposals/{id}/decision` with access checks (`tests/app` 8/8, `/ask` is B's); `kept serve --demo`.
- Frontend: Next.js app in `web/` (case card + review/release, Ask, steward). Screenshot-checked on desktop and phone.

## Decisions and changes from the plan
- Audit log: a file-backed log opens a DuckDB connection per call (K5); `:memory:` keeps one. Events are stored as JSON, so reads are lossless.
- `roll_forward_rate` skips cases with a null `dpd_at_day_30` (younger than 30 days). Otherwise they'd count as cures and flatter the rate. New test added.
- `test_local_calling_hours` now allows Sunday contact: the DST fall-back case (1 Nov 2026) is a Sunday, and the Sunday rule masked the hour under test. Own commit.
- `mask_phone` assumes 10-digit national numbers (NANP); every customer is Canadian.

- **Random assignment** (§9 TBC, answered from the data): `collections_cases.assignment_method = 'random'` (146,573 cases). `no_contact_holdout` is random only: a clean "do nothing" arm for uplift.
- **Legacy codes** (§9 TBC, answered): `nba_recommendation_last` has 5 values; `send_letter` and treatment `letter` map to no Action (we don't send letters).
- **Contact attempts** = `direction = 'outbound'` rows. Inbound calls and `internal`/`system` events don't use the 7-day cap or count in answer rates.
- **Feature grain:** promise and answer-rate features are per CRM customer (`coll_customer_ref`) until A's golden ID lands (G2); `contacts_last_7d` is per case (the cap is per case).
- **Cohorts** group by product x **entry** bucket, not `current_bucket`: the case row holds only the latest state, so `current_bucket` would leak the future into training.
- Account, deposit and text features are null columns in `case_features` until G2: silver keeps only each account's latest snapshot (history must come from `account_monthly_snapshot`), deposits need A's crosswalk, text needs C's `text.extractions`. **For A:** please keep `account_monthly_snapshot` in silver with full history.
- **For A (dbt):** `pyproject.toml` has `dbt-core>=1.8`, so `uv.lock` picks dbt-core 1.8.8 with dbt-duckdb 1.11, which crashes on start (`Capability.MicrobatchConcurrency`). `dbt-core>=1.10` works (1.12.5). Until then: `uv run --with "dbt-core>=1.10" --with "dbt-duckdb>=1.9" dbt ...`.
- **For A (K3 layout), from the release:** `data/raw/` = the 31 tables only; `data/files/{transcripts,docs}` (the tables' `file_path` columns are relative to `files/`); `data/labels/` = the two public label files; `data/benchmark/` = dev answers + answers template; `data/release/` = release README, MANIFEST, schema, dictionary. `primary_product` uses `card` (not `credit_card`).

- **Feast offline store is `file`, not `duckdb`:** Feast's duckdb store needs `ibis`, which we don't install. It reads the same Parquet export.
- **Context builder** reads the case row from `silver.collections_cases` (cap, case-level hard stops, `nba_recommendation_last`). A fresh text hardship signal raises `NONE` to `POSSIBLE` before gold catches up; it never lowers gold. Unknown time zone or contact count fails closed.
- **Qini test** threshold was above the analytic value (0.01875); it now asserts that value. Own commit.

- **UI is Next.js, not the plan's static page** (§4 S7 said "no frontend framework"). Shreyas's call. Cost: `web/` with ~450 MB node_modules; the demo machine (C's) needs Node 22 + pnpm; the demo runs two processes (`make serve-demo` / `make serve` and `make web`). A's steward queue and B's Ask box are pages in `web/`, calling their existing API routes.
- **Engine checks safety at the proposed slot**, not "now": a 06:00 batch would otherwise block every contact. The release gate rechecks everything at release time.
- **Release re-tiers** ALTERNATIVE/OVERRIDE to the stricter tier of the two actions, and a hardship flag that appears after the proposal makes it Red.
- **SHAP without the shap package:** LightGBM's own `pred_contrib`, converted to probability points per feature (leave-one-out; signs and sizes right, not exactly additive).
- Port 8000 is taken by VS Code on Shreyas's machine; `kept serve --port` and `KEPT_API_URL` cover it. In dev, open `localhost:3000`, not `127.0.0.1` (Next 16 blocks dev resources cross-origin).

## Open questions
- **paid_14d source (§9, D + A):** dated payment events exist in `loan_instalments` (`paid_date`, `paid_amount`), `card_statements` (`payments_amount`, `first_payment_after_due_date`, per cycle), `transactions` (sample only) and `contact_history.payment_taken_flag`. Proposal for A: loans from `loan_instalments.paid_date`; cards from `transactions` where present, else `card_statements` (cycle-level, so `paid_14d` is approximate for cards). Needs A's silver.
- **Still needs other tracks:** `kept train` (real features + labels, after G2), `kept score` and real `kept serve` (A's `DuckDBC360Reader`, G3/G4), `kept nightly` (every track's subcommands), hardship programmes on the banner (C's `eligible_programs`).
- **G0 contract proposal:** `GoldenCustomer` should carry `hard_stop_flags: frozenset[HardStop]` (A already computes it in `kept.data.gold.hard_stop_flags`). Today gold only has a yes/no `collections_hold`, so the context builder labels an unexplained hold INSOLVENCY. Additive change across the four golden-record copies (plan §8), A's files.

## Log
- 3 Oct: Phases 3-5 parallel tasks done against fakes; Next.js frontend; demo server.
- 3 Oct: dataset downloaded and laid out under data/; Phase 2 parallel tasks done; continuing into later phases against fakes.
- 3 Oct: PR to main held until the other tracks finish Phase 1 (Shreyas's call).
- 3 Oct: Phase 1 parallel tasks done; rebased onto force-pushed main (4b21af6).
