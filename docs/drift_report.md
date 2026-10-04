# Feature drift report

Training rows (features_train.case_features): 690,062 · served tonight: 96,000 cases (features as of 2026-10-03 06:00:00+00:00). Written by `kept drift`.

Overall: **DRIFT** · 10 drift · 5 watch · 11 stable. PSI under 0.1 is stable, 0.1 to 0.25 watch, 0.25 or more drift (investigate, then retrain). Missing values are their own bin.

Training rows are every past decision since 2016 and tonight is the open book, so part of any
drift is that difference, not a change in customers.

**Never seen in training** (missing for every training row, so the model learned nothing from them): `payroll_delay_days`, `pay_change_vs_3m_avg`, `estimated_monthly_spare_cash`.

| feature | PSI | status | missing (train) | missing (tonight) |
|---|---|---|---|---|
| cohort_kept_rate | 5.460 | drift | 0% | 0% |
| cohort_recovery_rate | 4.003 | drift | 0% | 0% |
| payroll_delay_days | 1.977 | drift | 100% | 76% |
| pay_change_vs_3m_avg | 1.532 | drift | 100% | 80% |
| estimated_monthly_spare_cash | 1.532 | drift | 100% | 80% |
| contacts_last_7d | 0.784 | drift | 0% | 0% |
| days_to_next_payroll | 0.667 | drift | 76% | 76% |
| days_in_bucket | 0.488 | drift | 40% | 12% |
| balance_at_risk | 0.391 | drift | 0% | 0% |
| max_dpd | 0.350 | drift | 11% | 7% |
| hardship_signal | 0.170 | watch | 50% | 31% |
| dispute_flag | 0.165 | watch | 50% | 30% |
| cease_request_flag | 0.165 | watch | 50% | 30% |
| card_utilisation_trend | 0.161 | watch | 44% | 37% |
| cash_flow_trend | 0.112 | watch | 57% | 53% |
| kept_promise_ratio | 0.065 | stable | 67% | 55% |
| times_30plus_dpd_12m | 0.056 | stable | 11% | 7% |
| answer_rate_after_18h | 0.046 | stable | 69% | 60% |
| answer_rate | 0.038 | stable | 50% | 42% |
| broken_promises_90d | 0.036 | stable | 0% | 0% |
| payment_link_usage | 0.026 | stable | 32% | 25% |
| pay_frequency | 0.000 | stable | 76% | 76% |
| promise_intent | 0.000 | stable | 100% | 100% |
| promised_date | 0.000 | stable | 100% | 100% |
| promised_amount | 0.000 | stable | 100% | 100% |
| third_party_present_flag | 0.000 | stable | 100% | 100% |
