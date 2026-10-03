# Track D: Model and UI

Person: Shreyas Deb · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: G2 work done on real gold (features, Feast, training rows, `kept train`); ready to integrate
- Working on: nothing until G2 passes
- Waiting on: nothing; next: real `/queue` from `nba.cards`, `kept nightly` (G4), C's `eligible_programs` on the banner

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
- Product flows: persona sign-in (deep link `/signin?as=agent-7&next=/queue`), ranked queue, case card with what-if sizing and interactive probabilities, approvals inbox (Red two-step, Green batch), audit trail, guided demo (§7 script), scroll-driven 3D landing (light and dark). API routes `/queue`, `/approvals`, `/audit`, `/cases/{id}/customer`, `/demo/cases/{id}/notes`; `tests/app/test_demo_flows.py` 9/9.

- **G1 (3 Oct, this laptop, real data):** `kept land` (31 bronze tables, counts = release README); `dbt build --select bronze silver` **38/38 pass** (4m11s, DuckDB capped at 2.5 GB: see below); `dbt build --select path:models/features identity_crosswalk` **13/13 pass** (5 s) on real silver + stub gold. `features.case_features`: 96,000 rows = every case open at 2026-09-28 06:00 in silver, no duplicates, columns = feature registry. **Parity on 200 random real cases: 200/200 match the Python reference definitions.** Built features: broken_promises_90d (mean 0.34), kept_promise_ratio (45% non-null), answer_rate (58%), answer_rate_after_18h (40%), payment_link_usage (75%), contacts_last_7d (max 8: real cap breaches), cohort_recovery_rate (0.965–0.999: little variance), cohort_kept_rate (0.45–0.64).

- **G2 (3 Oct, this laptop, real gold):** gold from Satvik's crosswalk (`identity_crosswalk_4ac9c37-20261003-full-train5`): 38/38 pass, **matches his gold export** (1,052,300 golden IDs, same set; 11 key columns identical except `expected_next_payroll_date` on 3 rows). Features on real gold: 96,000 cases, **every case has a golden ID**, parity 200/200. **Feast:** `kept features` = dbt + export + apply + materialize (31 s, 1.8 GB); online read of real cases returns a full `FeatureVector`, unknown case -> KeyError (G2 exit check). **Training:** `features.training_rows` (323,560 decisions on randomly assigned cases, 230,545 with a trusted label, paid rate 0.38 call .. 0.49 email, WAIT 0.40); `kept features --training` builds features one second before each decision into `features_train` (304,944 rows, 0 leaks, parity 200/200); `kept train` fits the T-learner (fit before 15 Aug, test after: 162k / 68k rows), Qini vs WAIT positive for every action (call 0.077, sms 0.051, email 0.051, push 0.018), logs to MLflow, model in `data/exports/models/uplift.pkl`. Tests: `tests/nba/test_train.py`, `tests/features/test_dbt_features.py` 5/5.
- **G2 with C's extractions** (`extractions_880b98c_20261003.parquet`, 785,594 notes and transcripts): loaded into `text.extractions`; `text_signals` rebuilt (times now match silver exactly, see below); text features on real data match the rules on 200/200 rows (serving and training); Feast re-materialised (96,000 cases, 41 s, 1.9 GB). **`KeptContextBuilder` on A's real `DuckDBC360Reader` + real Feast + C's real store: 2,000/2,000 random open cases build, no errors** (hardship none 1,049 / possible 286 / confirmed 665; hard stops on 195; hold-out 4.75%). Retrained: same model (the only text model input, `promise_intent`, is never set by SetFit).
- Context builder reads `ExtractionStore.for_case`: a fresh note raises hardship via `hardship.combine`, a confirmed text cease is a hard stop, gold `hard_stop_flags` used (`test_context.py` 18/18). Text features (`text_features.sql`) joined into `case_features` from C's `text_signals`, point in time.

- **The 11 empty features are wired** (`account_points.sql`, `account_features.sql`; the snapshot history was already in silver, no A work needed). On real data (96,000 open cases): `times_30plus_dpd_12m` = the snapshot's `times_30dpd_12m` on 99.6%; `days_in_bucket` = `bucket_entry_date` on 95%; `max_dpd` = gold's on 91%; `days_to_next_payroll` = the Python definition on every case within a pay period. Training features: max DPD on 89% of rows, no leaks. New fixture test `test_account_features_match_the_rules` (dbt tests 6/6). Engine on 300 real cases: 300/300 cards.

- **C's G3 asks (3 Oct):** (1) real `Services` in `kept/app/real.py`, `kept serve` without `--demo` runs it; (2) the card's add-note path = C's `extract_into` with Presidio + the LLM built once at startup (`POST /cases/{id}/notes`); (3) `GET /cases/{id}/extractions` + a "Possible cease request: confirm" banner on the case page that confirms through `/extractions/{id}/confirm`; (4) the 30/90 rule in `text_features` (text-only hardship on open cases 41% -> 18%; Red cards 26% -> 15% on 300 real cases); (5) `kept train` reports Qini against the legacy strategy: model beats legacy on calls (+0.0062 vs +0.0017, noise 0.0003) and on any contact vs wait (+0.0006 vs -0.0009); email is noise for both. **Real-mode smoke test on real data:** startup 2.6 s, card 0.09 s, a typed note -> live extraction 4.3 s -> the card turns Red (hardship review), cease confirmed -> hard stop.

- **`kept score` (G3 exit check):** a card for every open case: **96,000 cards -> `nba.cards` in 152 s** (2.4 GB): red 31,140 (almost all hardship reviews), green 38,789, amber 3,731, no action 22,340 (wait best 10,707, insolvency/bankruptcy 6,378, cease 2,707, hold-out 2,340). One RECOMMENDATION audit event per card, written in one go. `tests/nba/test_score.py`.
- G3 follow-ups: a protected case is offered a hardship review instead of "no action" (CS-2026-820205); `.env.example` MLflow URI -> `sqlite:///mlflow.db` (MLflow 3 refuses `file:./mlruns`), and `kept train` loads `.env`.

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

- **Design system: Radix Themes, "Maple" theme** (sand neutrals, ruby accent, Source Serif headings); Red tier is plum so it never clashes with the accent. Motion for animation; three.js (R3F + drei + postprocessing) for the landing only. Shreyas's call.
- **Red tier releases in two steps:** the specialist's approval moves a proposal to `APPROVED`; a different person (team lead, compliance or specialist) releases it after a fresh recheck. Uses the existing `ProposalStatus.APPROVED`, no contract change.
- **Demo clock:** `kept serve --demo` runs on a business-hours clock (shown in the header) so releases can pass the real calling-hours check at any time of day.
- **For B:** `/ask` is now a one-line pass-through to `services.ask` (it raised before even with a service injected). The demo Ask answers the kept-rate metric with real SQL over `data/raw`; everything else is B's.

- **Features read silver through `ref()`** (was `source('silver', ...)` until A's silver existed), so dbt orders them after A's models. The fixture parity test now selects only the feature models.
- **Memory on 14 GB laptops:** `kept land` and `dbt build --select silver` were OOM-killed at default DuckDB settings (≈4.7 GB). With `memory_limit = 2.5–3GB`, `threads = 1`, `preserve_insertion_order = false` both pass (peak 3.7 GB). I used a local profile copy in `data/warehouse/local/` (not committed); **for A:** worth adding `settings: {memory_limit: ...}` to `dbt/profiles.yml` and the same `SET`s in `connect()` for the demo laptop.

- **Features join the crosswalk on `source_system = 'collections'`** (was `crm`): `coll_customer_ref` is a collections key, as in A's `int_open_case`. As a crm key it missed 2,872 cases (3%) and gave the wrong customer for 586.
- **Cohort features use running totals + ASOF joins** (same values on all 96,000 real rows): the old range join grew with every distinct as_of and couldn't take the training spine.
- **Training spine:** `--vars '{training_spine: true}'` builds every feature model one second before each decision, into schema `features_train`, so serving tables are never overwritten.
- **paid_14d as agreed with Satvik (PR #13):** the five sources; a "no" is trusted only for loan accounts or accounts in the transactions sample (`paid_14d_known`). Card rows are about half known, overdraft a quarter.
- **`collections_cases.account_ids`** is a JSON list except 18,314 cases holding one bare ID; `training_rows` reads both. **For A:** worth normalising in silver.
- **No text extractions in the warehouse yet:** I created the empty `text.extractions` with C's `DuckDBExtractionStore` so `text_signals` builds; text columns are null until C's backfill runs.
- **`text` models get the `TimeZone = 'UTC'` pre-hook** (`dbt_project.yml`, one line in C's section, same as features): `text_signals.written_at` is `timestamptz` (coalesce with `extracted_at`), so naive UTC note times were read in the build machine's zone; on IST machines every note was 5.5 hours early. **For C:** your machine's `text_signals` has the shift; rebuild after this merges.
- **`CLOSE_CALL_MARGIN` = 0.05 (superseded below)** (was TBC 0.02; Shreyas asked me to pick). It is relative: top two dollar scores within 5% of the top. Chosen from 6 bootstrap retrains on real data: the *kind* of action (wait / green / call) is stable in 95% of resamples, and the margin barely separates stable from unstable cases (cross-kind cases below 0.02 hold 54%, 0.02-0.05 71%, above that 55-83% with no trend), so it works as a review-load setting: 7.2% of cases are close calls (0.02: 3.7%, 0.1: 18%).
- **Model limitation:** which green channel (email / push / SMS) wins for a given case is noise: the exact top action holds in only about 37% of resamples. The Qini numbers are against WAIT. Upgrade: fewer features or stronger regularisation, or a pooled model with action as a feature.
- **Engine with the real model:** promise, plan and hardship review were never randomised, so the model has no arm for them, and 193 of 300 real cards failed closed with a `KeyError`. They are call conversations, so they now take the call model's P(paid); hardship review only when hardship or vulnerability protects the case (with the call's P(paid) and a lower burden it would beat every call). `ponytail` note: a P(kept | promise) model is the upgrade. On 300 real cases: 300/300 cards, 182 proposals (green 93, amber 12, red 77). New test in `test_engine.py`.
- **For the team:** 26% of real cards are Red hardship reviews (C's high-recall hardship: 41% of open cases), a large specialist review load.
- **Account features, point in time:** every card/loan/deposit snapshot carries 12 monthly columns (`m{k}` = month-end k months before the snapshot month, data dictionary). `account_points` unpacks them so serving and training read the same history. `max_dpd` = latest DPD per account, aged by the days since a month-end within a month (`ponytail`: assumes no payment since); `days_in_bucket` = DPD past the bucket's first day (no look-ahead, unlike `bucket_entry_date`); `days_to_next_payroll` projects the expected payday back along the schedule (semi-monthly = every 15 days in this data). **Snapshot-only, null in training** (no history; the snapshot is after every decision): `payroll_delay_days`, `pay_change_vs_3m_avg` (= the snapshot's per-payday `payroll_amount_change_pct`; monthly totals swing with paydays per month), `estimated_monthly_spare_cash` (pay per payday x paydays a month, minus housing, essentials, other lenders). `balance_at_risk` = case `total_overdue`.
- **The WAIT arm was wrong, now fixed:** I used the `no_contact_holdout` cell at case open + 1 day, but that cell delays contact (median first contact day 12 vs 6) rather than withholding it, and every WAIT row was a brand-new case (DPD 0.2) compared with calls at day 61 (DPD 61). Earlier Qini numbers (call 0.077, email 0.051) were mostly that artefact. WAIT is now "a weekly check-in day (1..120 days after open) with no outbound contact that day" on any randomly assigned case: 268,771 known rows at day 31 / DPD 28, matching the contact arms.
- **Honest uplift result:** calls show real uplift (Qini 0.0062, z = +21 against random rankings on the test split); email, push and SMS are within noise (z -1.1..+1.9): the model can't tell which customers a message helps more. Uplift params are now regularised (100 trees, 7 leaves, 300 min rows, L2 5): best call Qini of the four settings tried.
- **`CLOSE_CALL_MARGIN` back to 0.02** with the new model (0.05 now makes 17% of cases close calls; 0.02 gives the same ~7% as before). The margin still barely tracks stability, so it is a review-load setting.
- **For A:** `kept features --training` peaks at 4.9 GB with `dbt/profiles.yml` (no DuckDB memory cap); a `settings: {memory_limit: 3GB}` there would keep it safe on 14 GB laptops.
- **One warehouse connection in the API:** DuckDB refuses a read-only and a read-write connection to one file in the same process, and C's store writes. `real_services` holds one read-write connection and every reader takes a cursor (A's reader through a subclass in `real.py`, not an edit to A's file). Also cuts a card from 0.3 s to 0.09 s. The API owns the file while it runs (K5).
- **`kept features` defaults to the latest 06:00 UTC** (was fixed at 28 Sep): with the real clock, 28 Sep features are stale (> 26 h) and every card says "no action". The data ends 28 Sep, so nothing leaks; the features age correctly.
- **Context builder, fresh notes:** an unconfirmed store note counts only if newer than the features and not from the SetFit backfill (history comes through the features and their 30/90 rule); a person's confirmation always counts. Demo cease now needs an agent's confirmation too, like the real path.
- **The 30/90 rule lives in our `text_features`** (point in time per as_of), not C's planned `text.case_hardship` table, which has a single as_of and can't serve training. Same rule; C can keep the table for gold.
- **Not yet:** real `/queue` (needs `kept score`, G3); hardship programmes on the real banner (C's `eligible_programs` needs a `ProgramCase` per case).
- **`kept score` design:** the same `KeptContextBuilder` and `KeptEngine` as the live API, fed by in-memory readers loaded in bulk (gold, the feature table Feast serves, case rows, confirmed or live extractions: 8 s); the uplift model answers from one vectorised batch (1 s) looked up per card, falling back to the model for a row it hasn't seen (identical cards on 400/400 checked); the proposal store keeps nothing (the engine's cancel scan was O(n) per card, O(n^2) over a run: 58 min -> 2.5 min overall).
- **Protected cases are offered a hardship review** when the uplift ranking says wait (design §6.3: the override sits outside the model). Before, a $59 balance with flat probabilities ended "No action today" after a hardship note. Still no review under a hard stop or without call consent.
- **For A + C:** 45% of scored open cases carry a hardship banner, mostly from gold's `hardship_status` (my local gold predates #24); with the 30/90 rule in features only, 31,140 cards (32%) go to specialists. Gold's text rule should match the 30/90 rule.
- **`KEPT_HOLDOUT_SALT`:** mine is still the `.env.example` placeholder. Every machine must use one value (it decides who is in the hold-out); pick one before the demo, set it everywhere, then rerun `kept score`.
- Uplift models convert inputs themselves (fixed `pay_frequency` levels, bools/None to float), so a serving `FeatureVector` scores the same as a warehouse row.

## Open questions
- **paid_14d source (§9, D + A, by G2). Proposal for Satvik, from counts on the raw data (3 Oct):**
  `paid_14d` = any dated payment in (decision, decision + 14 days], from the union of:
  1. `contact_history` at the contact's time: `payment_taken_flag` (20,072), `link_payment_flag` (26,581), `app_payment_after_contact_flag` (38,084). All products.
  2. `promises_to_pay.paid_date` for `kept` / `partially_kept` (117,549 dated). All products.
  3. `loan_instalments.paid_date` (14.2M dated; `partially_paid` rows have no date). Personal, auto, LOC, mortgage.
  4. `transactions` debits with `txn_type` `card_payment` / `loan_payment` and a `target_account_id` (≈1.17M; customer sample only): confirms a payment, never denies one.
  5. `card_statements.first_payment_after_due_date` where set (136K): late card payments only.
  Gaps: on-time card payments outside the transactions sample have only cycle-level `payments_amount`; overdraft has monthly snapshots only. Proposed: label those rows only when a source above fires, mark the rest `paid_14d_known = false`, and leave them out of training rather than guess.
  **Ask for A:** keep these five tables in silver with their dates, and the three `contact_history` flags.
- **Still needs other tracks:** `kept train` (real features + labels, after G2), `kept score` and real `kept serve` (A's `DuckDBC360Reader`, G3/G4), `kept nightly` (every track's subcommands), hardship programmes on the banner (C's `eligible_programs`).
- **G0 contract proposal:** `GoldenCustomer` should carry `hard_stop_flags: frozenset[HardStop]` (A already computes it in `kept.data.gold.hard_stop_flags`). Today gold only has a yes/no `collections_hold`, so the context builder labels an unexplained hold INSOLVENCY. Additive change across the four golden-record copies (plan §8), A's files.

- **For C:** SetFit fills only `hardship_signal`; promise, dispute, cease and third-party are never set, so those text features are false. 41% of open cases (39,398) have a possible-hardship note in the last 90 days (gold already has hardship on 34,940 of them).
- **For A:** 96 of 2,000 sampled open cases (4.8%) have no `time_zone` in gold, so calls fail closed for them.
- Backfilled extractions all carry `extracted_at` = the backfill run (3 Oct), so the context builder's "fresh notes" path counts every backfilled note on a case, not only the last 90 days: 865 more open cases (0.9%) read POSSIBLE than the features say, in the protective direction. It goes away once the features' as_of passes the backfill date.
- **Batch scoring needs one shared read-only connection:** each reader opens the warehouse per call (K5), about 60 ms each, so a card takes about 0.3 s; `kept score` (G3) should read the case rows, gold and extractions in bulk.

## Log
- 4 Oct: `kept score` 96,000 cards in 152 s; hardship review for protected cases; MLflow sqlite.
- 3 Oct: C's G3 asks done: real services and `kept serve`, live add-note, extractions route + cease confirm, 30/90 rule, Qini vs legacy in `kept train`.
- 3 Oct: 11 account/payroll/cash-flow features wired and checked on real data; WAIT arm rebuilt (hold-out delays contact); honest Qini: calls only; regularised uplift params; margin 0.02.
- 3 Oct: close-call margin 0.05 from bootstrap stability; engine fixed for the real model's five arms (300/300 real cards).
- 3 Oct: C's extractions loaded; text features on real data; context builder on A's real reader 2,000/2,000; G2 checks done on Track D's side.
- 3 Oct: G2 on real gold: gold from Satvik's crosswalk (matches his export), features + Feast on real gold, training rows + features, `kept features` and `kept train` handlers, first real training run.
- 3 Oct: G1: bronze + silver built on real data here; dbt features 13/13 on real silver, 96,000 open cases, parity 200/200. Stop message posted.
- 3 Oct: after the Phase 1 merge (NEXT_STEPS §4): README run steps; paid_14d proposal for A; G0 PR #10 reviewed (dbt pre-hook bug blocking, ExtractionStore needs for_case); extraction confirm/edit panel and programme chips on the case card (demo-backed until G0 merges).
- 3 Oct: Radix redesign, product flows, two-step Red release, 3D landing; all pushed to track-d / PR #2.
- 3 Oct: Phases 3-5 parallel tasks done against fakes; Next.js frontend; demo server.
- 3 Oct: dataset downloaded and laid out under data/; Phase 2 parallel tasks done; continuing into later phases against fakes.
- 3 Oct: PR to main held until the other tracks finish Phase 1 (Shreyas's call).
- 3 Oct: Phase 1 parallel tasks done; rebased onto force-pushed main (4b21af6).
