# Track D: Model and UI

Person: Shreyas Deb · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 2, then the later phases' parallel tasks against fakes (Shreyas's call while G0 waits)
- Working on: Phase 4 (sizing, ranking, explanations, engine)
- Waiting on: G0 for merging; nothing blocks coding

## Done
- `DuckDBAuditLog` + `new_event_id` (early provider, Q2): `tests/common/test_audit.py` 7/7. Branch `track-d`.
- Labels `paid_within`, `rolled_forward`, `roll_forward_rate`: label tests in `tests/nba/test_uplift_explain_labels.py` 14/14.
- Rules `hard_stops`, `permission_gate`, `allowed_actions`, `hardship_override`: `tests/nba/test_rules.py` 54/54.
- Access and masking: `tests/governance/test_access.py` 39/39.
- `/health`: `tests/app/test_api.py::test_health`.
- Phase 2: feature definitions + deny-list (`tests/features/test_definitions_and_store.py` 56/56); legacy code mapping from real data (`tests/nba/test_legacy.py` 17/17); tiers, hold-out, staleness, batch sample.
- Phase 2: dbt feature models (`dbt/models/features/`): spine, promise, contact, cohort, `case_features`. `tests/features/test_dbt_features.py` checks the SQL against the Python definitions point in time (4/4, needs dbt: see the test's docstring).

- Phase 3: `KeptContextBuilder` (S3, `tests/nba/test_context.py` 13/13); `TLearnerUplift` + Qini (uplift tests 8/8, incl. the LightGBM integration test); `FeastFeatureProvider` + `export_features` (`tests/features/test_feast_store.py` 4/4).

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

## Open questions
- **G0 contract proposal:** `GoldenCustomer` should carry `hard_stop_flags: frozenset[HardStop]` (A already computes it in `kept.data.gold.hard_stop_flags`). Today gold only has a yes/no `collections_hold`, so the context builder labels an unexplained hold INSOLVENCY. Additive change across the four golden-record copies (plan §8), A's files.

## Log
- 3 Oct: dataset downloaded and laid out under data/; Phase 2 parallel tasks done; continuing into later phases against fakes.
- 3 Oct: PR to main held until the other tracks finish Phase 1 (Shreyas's call).
- 3 Oct: Phase 1 parallel tasks done; rebased onto force-pushed main (4b21af6).
