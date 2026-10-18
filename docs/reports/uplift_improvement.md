# Uplift model: why it scores low, and what improves it

Written from `scripts/uplift_diagnostics.py` and `scripts/uplift_learners.py --improve`, on the full release (rebuilt on 17 Oct from the released data, the published identity crosswalk and Track C's extractions). Branch `model/uplift-improve`. Nothing here changes the live decisions: no model was promoted and `data/exports/models/uplift.pkl` is the reproduced champion.

## The short version

1. **On decision-time information, the live uplift model's call ranking is the weakest rule tested.** Counting extra clean payments (account-sourced, no contact flags) within 14 days against waiting, on the decisions from 15 Aug, restricted to the population where both contacted and waiting decisions exist, per 1,000 decisions: the depth-3 policy tree **+13.4** [+9.3, +17.3], treating every call decision **+11.7** [+4.5, +18.1], the live model's top rows at the same share as the tree **+6.2** [+1.1, +10.5]. The bank's own recommendation field is left out of this comparison on purpose: it is a look-ahead field, not a decision-time rule (see "The bank's recommendation is not a decision-time rule"). The DR nuisance models use the context inputs, which favours the tree.
2. **The live model's gate numbers are noisier than the gate says.** The gate's noise (0.0003) is the spread under random rankings. Retraining the same model on the same rows with a different seed moves the call Qini between +0.0023 and +0.0063 and the any-contact Qini between -0.0003 and +0.0018.
3. **Two artefacts inflated the early results.** Payments flagged on the contact row (a link or app payment after an SMS or email) exist only for contacted decisions and leave no trace in transactions, so the old label credits SMS and email with about +5.5 points that no other source confirms. And the contact-attempt rows compare contact days with a weekly grid of quiet days, which have almost no overlap at 30+ days past due; they show a strong "heterogeneity" (calibration slope 1.0, t = 12 to 26) that mostly disappears in a fairer row design (slope 0.0 to 0.5, t = 0 to 4).
4. **Adding what the bank knew at the moment of deciding to the existing model improves it on the rows it was built for.** The best-scoring is the live T-learner with ten extra context inputs. It is recorded as the next challenger, not promoted: it was not the candidate picked on validation, it does not carry over to the cleanest evaluation set, and the ten inputs are not in the feature registry or the serving path.
5. **Timing is where the clear win is.** Calls placed at 17:00 to 20:59 reach the customer 21 points more often than calls at 08:00 to 16:59 among comparable calls, and 24 points more within the same customer. Moving the best-suited calls into the evening, with the evening volume capped at what the team handles today, is predicted to add 7.4 points of right-party contact (16.3 uncapped).
6. **Skipping contact for predicted self-curers is a pilot hypothesis, not a result.** The model ranks self-curers well (AUC 0.80), but the bank's randomised holdout cell is too small and too contacted to show it costs nothing.

## Baseline reproduced

`uv run kept train` on the rebuilt warehouse, cutoff 2026-08-15, seed 0: 355,485 rows to fit, **141,350 test decisions (the published count)**.

| Gate metric, test decisions | Published (3 Oct) | Reproduced, seed 0 | Reproduced, seeds 0 to 3 (mean, sd) |
|---|---:|---:|---:|
| Qini, calls | +0.0073 | +0.0040 | +0.0041, 0.0017 |
| Qini, any contact | +0.0008 | +0.0002 | +0.0005, 0.0009 |
| Gate noise (calls, any) | 0.0003, 0.0003 | 0.0003, 0.0003 | |

| Seed | Gate Qini, calls | Gate Qini, any contact | Noise (calls, any) |
|---|---:|---:|---:|
| 0 | +0.0040 | +0.0002 | 0.0003, 0.0003 |
| 1 | +0.0063 | +0.0018 | 0.0003, 0.0003 |
| 2 | +0.0037 | +0.0003 | 0.0003, 0.0003 |
| 3 | +0.0023 | -0.0003 | 0.0003, 0.0004 |
Mean over the four seeds: calls +0.0041 (sd 0.0017), any contact +0.0005 (sd 0.0009).

The published numbers sit above what a rebuild gives. The rebuild uses the published crosswalk and extractions, but the warehouse, dependency versions and the model seed differ; the seed spread alone covers most of the gap. Everything below compares candidates against the **seed-averaged** champion, trained as the live model is (five arms, 17 inputs, the old rows).

Rolling windows for the same model (expanding fit window, 3 seeds, bootstrap SD resamples whole cases). 15 Jul to 15 Aug is the validation window used to pick candidates, so the mean that excludes it is shown:

| Window | Decisions | Calls: mean over 3 seeds [min, max] | Any contact: mean [min, max] | Bootstrap SD |
|---|---:|---|---|---:|
| 15 May to 15 Jun | 43,410 | +0.0033 [+0.0032, +0.0034] | +0.0010 [+0.0009, +0.0012] | 0.0005 / 0.0005 |
| 15 Jun to 15 Jul | 65,024 | +0.0010 [+0.0002, +0.0023] | +0.0007 [+0.0005, +0.0009] | 0.0005 / 0.0005 |
| 15 Jul to 15 Aug (validation) | 103,235 | +0.0013 [+0.0003, +0.0025] | +0.0013 [+0.0012, +0.0015] | 0.0004 / 0.0004 |
| 15 Aug to 14 Sep | 141,350 | +0.0047 [+0.0037, +0.0063] | +0.0008 [+0.0002, +0.0018] | 0.0004 / 0.0004 |
Mean of the three non-validation windows: calls +0.0030, any contact +0.0008.

The sign never flips, but in two windows a seed puts the call Qini at or near zero, and any-contact is 1.4 to 3.2 bootstrap SDs above zero in every window.

## Step 0: is there an effect to find?

Method (`src/kept/nba/causal.py`): doubly robust (AIPW) pseudo-outcomes from LightGBM outcome and propensity models, cross-fitted in 5 folds with whole cases kept together; 95% intervals resample cases; propensities clipped at [0.05, 0.95]. Rows with an estimated propensity outside that range are dropped ("overlap population").

### The bank chose, and WAIT is not comparable

| Arm | Decisions | Paid (old label) | Pending promise | Contacted in prior 7 days | Covered |
|---|---:|---:|---:|---:|---:|
| call | 125,246 | 38.4% | 37.2% | 66.5% | 82.8% |
| email | 47,790 | 48.8% | 13.9% | 38.2% | 77.8% |
| push | 9,333 | 47.0% | 12.9% | 25.1% | 78.4% |
| sms_payment_link | 45,695 | 48.4% | 17.5% | 43.9% | 78.8% |
| wait | 268,771 | 38.9% | 15.9% | 49.8% | 82.2% |

Calls go to cases with a pending promise (37% against 16% for waiting) and to cases already contacted in the last week (67% against 50%); those cases pay anyway. The bank's choice is easy to predict:

| Arm vs wait | AUC, 17 inputs | AUC, + context | Rows outside [0.05, 0.95] (17 inputs) |
|---|---:|---:|---:|
| call | 0.942 | 0.955 | 36% |
| sms_payment_link | 0.866 | 0.892 | 45% |
| email | 0.862 | 0.892 | 46% |

The driver is days past due (73% of the propensity model's gain): calls go to cases beyond 30 days past due (38% to 58% of decisions there, 4% to 6% below), while WAIT rows are spread over every stage. The WAIT group is a synthetic comparison: part of it is a population the bank would never have called. Of the 17 inputs, `max_dpd`, `days_in_bucket` and `answer_rate` carry almost all of it.

### The label: payments flagged on the contact

For SMS and email, 12.8% and 12.7% of decisions carry a link or app payment flag on the contact row; for calls 0.9%. WAIT cannot carry one. Those payments leave no trace in the account records: among SMS and email contacts with a flag, a card or loan payment transaction within two days occurs in 3.7% to 4.1% (waiting: 4.1%), and within 14 days in 32.5% to 35.3% (waiting: 30.2%). Cure within 30 days is no higher for flagged contacts than for comparable unflagged ones (email +0.3 points [-1.0, +1.2], SMS -0.1 [-1.0, +0.8], call -1.0 [-2.8, +1.1]). So the flagged payments may be real money or an artefact of the data; the account data cannot say. This report therefore gives SMS and email as bounds: the clean outcome (account-sourced records only, covered cases, no contact flags) is the lower bound, the old label the upper bound. For calls (0.9% flagged) the clean outcome is the primary measure.

### Effects and heterogeneity

Rows are either **contact attempts** (the live design: one row per outbound contact, WAIT from a weekly grid of quiet days) or **case landmarks** (new: a weekly landmark per case; contacted if the first mapped contact falls in the next two days, WAIT if there was none; the 14-day outcome starts two days after the landmark; the case must be open then). A first version of the weekly design counted a whole week and gave negative effects for every arm and outcome (clean payment: call -1.9, SMS -3.2, email -3.5 points; cure -2.4 to -2.7). That was immortal time: a case that cures early in the week is not contacted for the rest of it, so WAIT contained early cures. The landmark version fixes it.

Effects are in points of probability (dollars: mean dollars per decision; waiting pays about $150 to $170). "BLP slope" is the best-linear-predictor test of an out-of-fold DR-learner's predictions against the pseudo-outcomes: a slope near 1 with a large t means the predictions carry real, calibrated heterogeneity; near 0, none.

| Rows | Outcome | Arm | Overlap kept (arm / wait) | Effect, untrimmed | Effect on overlap [95% CI] | BLP slope (t) | OOF DR Qini |
|---|---|---|---|---:|---:|---:|---:|
| case landmarks | any payment, contact flags included | call | 89% / 39% | +0.9 | +1.1 [+0.5, +1.6] | 0.32 (3) | +0.0031 |
| case landmarks | any payment, contact flags included | sms payment link | 63% / 36% | +0.4 | +1.1 [+0.1, +2.2] | 0.08 (1) | +0.0009 |
| case landmarks | any payment, contact flags included | email | 73% / 43% | -0.9 | -0.3 [-1.2, +0.6] | 0.24 (2) | +0.0040 |
| case landmarks | clean payment | call | 89% / 39% | +2.0 | +1.6 [+0.9, +2.2] | 0.27 (2) | +0.0030 |
| case landmarks | clean payment | sms payment link | 63% / 36% | +0.7 | +3.1 [+1.9, +4.3] | -0.03 (-0) | -0.0002 |
| case landmarks | clean payment | email | 73% / 42% | -0.3 | +1.4 [+0.4, +2.4] | 0.30 (3) | +0.0047 |
| case landmarks | clean dollars paid | call | 89% / 39% | +11.4 | +7.1 [-1.9, +16.1] | 0.29 (1) | +5.1838 |
| case landmarks | clean dollars paid | sms payment link | 63% / 36% | +10.9 | +24.1 [+10.4, +35.9] | -0.03 (-0) | -1.6277 |
| case landmarks | clean dollars paid | email | 73% / 42% | +0.5 | +12.1 [+1.2, +24.3] | 0.12 (1) | +4.1052 |
| case landmarks | cured within 30 days | call | 89% / 39% | -0.0 | -0.0 [-0.5, +0.4] | 0.53 (4) | +0.0037 |
| case landmarks | cured within 30 days | sms payment link | 62% / 36% | +0.5 | +1.7 [+0.8, +2.4] | 0.17 (1) | +0.0025 |
| case landmarks | cured within 30 days | email | 74% / 44% | +0.5 | +0.8 [+0.1, +1.5] | 0.42 (4) | +0.0045 |
| contact attempts | any payment, contact flags included | call | 56% / 61% | -0.3 | -0.0 [-0.4, +0.4] | 1.00 (12) | +0.0081 |
| contact attempts | any payment, contact flags included | sms payment link | 84% / 53% | +6.3 | +5.6 [+5.1, +6.1] | 1.03 (16) | +0.0119 |
| contact attempts | any payment, contact flags included | email | 81% / 55% | +5.9 | +5.4 [+4.9, +5.9] | 0.98 (17) | +0.0134 |
| contact attempts | clean payment | call | 53% / 59% | -0.1 | +0.2 [-0.2, +0.7] | 0.98 (12) | +0.0098 |
| contact attempts | clean payment | sms payment link | 83% / 51% | +0.8 | +0.5 [-0.1, +1.1] | 0.92 (13) | +0.0125 |
| contact attempts | clean payment | email | 79% / 51% | +0.3 | +0.7 [+0.2, +1.2] | 0.97 (16) | +0.0147 |
| contact attempts | clean dollars paid | call | 53% / 59% | +9.1 | +14.3 [+9.0, +20.2] | 0.59 (4) | +8.1734 |
| contact attempts | clean dollars paid | sms payment link | 83% / 51% | +11.5 | +5.4 [-1.0, +11.9] | 0.71 (5) | +11.7871 |
| contact attempts | clean dollars paid | email | 79% / 51% | +5.3 | +5.6 [-0.4, +12.1] | 0.83 (7) | +11.6038 |
| contact attempts | cured within 30 days | call | 64% / 61% | -0.7 | -1.0 [-1.3, -0.8] | 1.20 (19) | +0.0085 |
| contact attempts | cured within 30 days | sms payment link | 86% / 55% | -0.2 | -0.4 [-0.7, +0.0] | 0.99 (16) | +0.0097 |
| contact attempts | cured within 30 days | email | 83% / 57% | +0.1 | -0.1 [-0.5, +0.3] | 0.96 (16) | +0.0101 |

What this says:

- **Average effects are small.** On clean payment the call effect is +0.2 points [-0.2, +0.7] on contact attempts and +1.6 [+0.9, +2.2] on landmarks; on cure within 30 days -1.0 and 0.0. Dollars for calls: +$14 [+9, +20] on attempts, +$7 [-2, +16] on landmarks (not confirmed). SMS and email on clean payment: +0.5 and +0.7 on attempts, +3.1 and +1.4 on landmarks; including the contact flags: about +5.5 on attempts. SMS and email are therefore "between about +0.5 and +5.5 points" on the attempt rows, with the upper end resting on payments the account data does not show.
- **The strong heterogeneity is a property of the contact-attempt rows.** Slopes of 1.0 with t = 12 to 26 appear on every binary outcome there, including cure, and fall to 0.0 to 0.5 (t = 0 to 4) on landmarks. Heterogeneity is not reliably found; at best it is weak for calls (clean payment t = 2, cure t = 4).
- **Overlap is the other cost.** On attempts, 53% to 64% of call decisions survive trimming; on landmarks only 36% to 44% of waiting decisions do. Every estimate above is for that population, not for all cases.

Decision rule applied: heterogeneity not reliably found, so the fixed rows (Track 1.1) and a bounded learner comparison were done, with self-cure and best-hour (Track 2.1, 2.2) as the main deliverables.

## Track 1: candidate models

**Rows and inputs.** `dbt/models/features/training_weeks.sql` (landmarks), `context_features.sql` (context; it started as `decision_context.sql` and now lives in `case_features`, so the nightly serves the same inputs, and it matches the old table on all 708,678 decisions and 402,064 landmarks), `macros/payment_events.sql` (labels, shared with `training_rows.sql`, whose `paid_14d` is unchanged: 0 differences in 708,678 rows). The context is what the bank knew a second before deciding: a pending promise and its due date, outbound contacts in the last 7 and 30 days, right-party contacts in the last 30 days, days since the last contact, the last contact's outcome (right party; promise made), a payment in the last 7 days, and the weekday. The label models (`training_rows`, `training_weeks`) are disabled in the nightly build; the context is part of `case_features` in both builds. No language, accent, postal code, age or other proxy is an input; `tests/nba/test_causal.py::test_study_features_are_clean` runs `assert_no_denied` and checks the contract's protected and proxy lists against every input.

**Candidates** (12): (T-learner on the 17 inputs, T-learner on 17 + context, DR-learner on 17 + context, R-learner on 17 + context) x three training sets (old rows with the old label; contact attempts with the clean label on covered cases; landmarks with the clean label on covered cases). The DR- and R-learners use cross-fitted nuisance models, drop rows outside the overlap range from the second stage, and use a small LightGBM (7 leaves, 1,000 minimum rows, L2 20) fixed before seeing any result. Three seeds each.

**Evaluation, agreed before running.** Fit before the window, score on the window: DR Qini per arm (call, SMS link, email) with nuisance models fitted on the fit window that no candidate uses, rows trimmed to overlap, mean over 3 seeds; in brackets, the candidate minus the champion in SDs of that difference over case-bootstrap resamples. The primary set is contact attempts on the clean label. Selection on validation (fit before 15 Jul, scored 15 Jul to 15 Aug), then one test (fit before 15 Aug, scored from 15 Aug). The gate's own metric (old rows, old label, the live definition and noise) is shown beside it. A candidate replaces the live model only if it beats the champion by more than twice the noise on the primary metric and does not lose beyond noise on the gate metric.

Validation, primary set:

| Candidate | call | sms link | email | mean | gate: calls | gate: any contact |
|---|---:|---:|---:|---:|---:|---:|
| T-learner, 17 inputs on old rows (attempts, any payment) | -0.0017 | +0.0026 | +0.0043 | +0.0017 | +0.0013 | +0.0013 |
| T-learner, 17 + context on old rows (attempts, any payment) | +0.0022 (+4.2) | +0.0038 (+1.0) | +0.0073 (+2.7) | +0.0044 | +0.0026 | +0.0018 |
| DR-learner, 17 + context on old rows (attempts, any payment) | +0.0041 (+3.1) | +0.0071 (+2.6) | +0.0064 (+1.2) | +0.0059 | -0.0022 | +0.0015 |
| R-learner, 17 + context on old rows (attempts, any payment) | +0.0046 (+3.6) | +0.0060 (+1.9) | +0.0068 (+1.5) | +0.0058 | -0.0015 | +0.0021 |
| T-learner, 17 inputs on attempts, clean payment (covered) | +0.0013 (+2.2) | +0.0057 (+1.8) | +0.0050 (+0.4) | +0.0040 | -0.0009 | +0.0016 |
| T-learner, 17 + context on attempts, clean payment (covered) | +0.0045 (+4.2) | +0.0083 (+2.7) | +0.0101 (+2.8) | +0.0076 | -0.0009 | +0.0018 |
| DR-learner, 17 + context on attempts, clean payment (covered) | +0.0044 (+3.7) | +0.0076 (+2.8) | +0.0094 (+2.6) | +0.0071 | -0.0002 | +0.0036 |
| R-learner, 17 + context on attempts, clean payment (covered) | +0.0049 (+4.2) | +0.0074 (+2.6) | +0.0088 (+2.3) | +0.0070 | -0.0000 | +0.0020 |
| T-learner, 17 inputs on landmarks, clean payment (covered) | -0.0006 (+0.8) | +0.0024 (-0.1) | +0.0014 (-1.3) | +0.0011 | -0.0013 | -0.0003 |
| T-learner, 17 + context on landmarks, clean payment (covered) | +0.0032 (+3.3) | +0.0039 (+0.8) | +0.0046 (+0.1) | +0.0039 | -0.0019 | -0.0006 |
| DR-learner, 17 + context on landmarks, clean payment (covered) | +0.0022 (+2.4) | +0.0031 (+0.3) | +0.0030 (-0.7) | +0.0027 | -0.0013 | +0.0000 |
| R-learner, 17 + context on landmarks, clean payment (covered) | +0.0023 (+2.4) | +0.0023 (-0.1) | +0.0025 (-0.9) | +0.0024 | -0.0012 | +0.0009 |

Selected on validation (highest mean over arms among non-champions): **T-learner, 17 + context, on contact attempts with the clean label**.

Test, primary set (contact attempts, clean label):

| Candidate | call | sms link | email | mean | gate: calls | gate: any contact |
|---|---:|---:|---:|---:|---:|---:|
| T-learner, 17 inputs on old rows (attempts, any payment) | +0.0006 | +0.0034 | +0.0033 | +0.0024 | +0.0047 | +0.0008 |
| T-learner, 17 + context on old rows (attempts, any payment) | +0.0067 (+6.4) | +0.0075 (+5.8) | +0.0073 (+4.8) | +0.0072 | +0.0047 | +0.0005 |
| DR-learner, 17 + context on old rows (attempts, any payment) | +0.0044 (+3.5) | +0.0068 (+3.3) | +0.0054 (+2.0) | +0.0055 | +0.0009 | +0.0014 |
| R-learner, 17 + context on old rows (attempts, any payment) | +0.0052 (+3.7) | +0.0073 (+3.8) | +0.0054 (+1.8) | +0.0060 | +0.0011 | +0.0016 |
| T-learner, 17 inputs on attempts, clean payment (covered) | +0.0012 (+0.7) | +0.0013 (-2.2) | +0.0033 (+0.1) | +0.0019 | +0.0030 | +0.0040 |
| T-learner, 17 + context on attempts, clean payment (covered) | +0.0043 (+3.3) | +0.0070 (+3.6) | +0.0073 (+3.5) | +0.0062 | +0.0010 | +0.0012 |
| DR-learner, 17 + context on attempts, clean payment (covered) | +0.0055 (+4.7) | +0.0058 (+2.2) | +0.0057 (+1.9) | +0.0056 | +0.0016 | +0.0056 |
| R-learner, 17 + context on attempts, clean payment (covered) | +0.0048 (+3.5) | +0.0062 (+2.7) | +0.0059 (+2.0) | +0.0056 | +0.0009 | +0.0033 |
| T-learner, 17 inputs on landmarks, clean payment (covered) | +0.0019 (+1.5) | +0.0020 (-1.2) | +0.0033 (-0.0) | +0.0024 | +0.0047 | -0.0018 |
| T-learner, 17 + context on landmarks, clean payment (covered) | +0.0053 (+5.0) | +0.0040 (+0.5) | +0.0054 (+1.6) | +0.0049 | +0.0010 | +0.0003 |
| DR-learner, 17 + context on landmarks, clean payment (covered) | +0.0024 (+1.6) | +0.0032 (-0.1) | +0.0024 (-0.7) | +0.0026 | +0.0023 | +0.0019 |
| R-learner, 17 + context on landmarks, clean payment (covered) | +0.0026 (+1.7) | +0.0029 (-0.4) | +0.0035 (+0.1) | +0.0030 | +0.0021 | +0.0031 |

Test, old rows and old label (the upper bound for SMS and email):

| Candidate | call | sms link | email | mean | gate: calls | gate: any contact |
|---|---:|---:|---:|---:|---:|---:|
| T-learner, 17 inputs on old rows (attempts, any payment) | +0.0033 | +0.0059 | +0.0064 | +0.0052 | +0.0047 | +0.0008 |
| T-learner, 17 + context on old rows (attempts, any payment) | +0.0080 (+7.7) | +0.0099 (+4.5) | +0.0113 (+5.4) | +0.0097 | +0.0047 | +0.0005 |
| DR-learner, 17 + context on old rows (attempts, any payment) | +0.0046 (+1.4) | +0.0088 (+2.6) | +0.0077 (+1.1) | +0.0070 | +0.0009 | +0.0014 |
| R-learner, 17 + context on old rows (attempts, any payment) | +0.0045 (+1.4) | +0.0091 (+2.7) | +0.0074 (+0.8) | +0.0070 | +0.0011 | +0.0016 |
| T-learner, 17 inputs on attempts, clean payment (covered) | +0.0011 (-4.0) | -0.0006 (-6.0) | +0.0019 (-3.8) | +0.0008 | +0.0030 | +0.0040 |
| T-learner, 17 + context on attempts, clean payment (covered) | +0.0052 (+2.4) | +0.0043 (-1.3) | +0.0062 (-0.2) | +0.0052 | +0.0010 | +0.0012 |
| DR-learner, 17 + context on attempts, clean payment (covered) | +0.0050 (+2.1) | +0.0055 (-0.3) | +0.0050 (-1.1) | +0.0052 | +0.0016 | +0.0056 |
| R-learner, 17 + context on attempts, clean payment (covered) | +0.0044 (+1.4) | +0.0054 (-0.4) | +0.0048 (-1.2) | +0.0049 | +0.0009 | +0.0033 |
| T-learner, 17 inputs on landmarks, clean payment (covered) | +0.0032 (-0.1) | -0.0011 (-5.8) | +0.0027 (-2.7) | +0.0016 | +0.0047 | -0.0018 |
| T-learner, 17 + context on landmarks, clean payment (covered) | +0.0056 (+2.8) | +0.0024 (-2.6) | +0.0051 (-0.9) | +0.0044 | +0.0010 | +0.0003 |
| DR-learner, 17 + context on landmarks, clean payment (covered) | +0.0019 (-1.3) | +0.0014 (-3.1) | +0.0015 (-4.0) | +0.0016 | +0.0023 | +0.0019 |
| R-learner, 17 + context on landmarks, clean payment (covered) | +0.0015 (-1.5) | +0.0002 (-3.8) | +0.0029 (-2.7) | +0.0015 | +0.0021 | +0.0031 |

Test, landmarks with the clean label (the cleanest design):

| Candidate | call | sms link | email | mean | gate: calls | gate: any contact |
|---|---:|---:|---:|---:|---:|---:|
| T-learner, 17 inputs on old rows (attempts, any payment) | +0.0001 | +0.0041 | -0.0013 | +0.0010 | +0.0047 | +0.0008 |
| T-learner, 17 + context on old rows (attempts, any payment) | +0.0015 (+1.0) | +0.0026 (-0.8) | +0.0017 (+1.4) | +0.0019 | +0.0047 | +0.0005 |
| DR-learner, 17 + context on old rows (attempts, any payment) | +0.0015 (+0.7) | +0.0020 (-0.8) | -0.0000 (+0.5) | +0.0011 | +0.0009 | +0.0014 |
| R-learner, 17 + context on old rows (attempts, any payment) | +0.0020 (+1.0) | +0.0031 (-0.4) | -0.0001 (+0.5) | +0.0017 | +0.0011 | +0.0016 |
| T-learner, 17 inputs on attempts, clean payment (covered) | +0.0031 (+2.4) | +0.0025 (-0.7) | +0.0005 (+1.0) | +0.0020 | +0.0030 | +0.0040 |
| T-learner, 17 + context on attempts, clean payment (covered) | +0.0019 (+1.0) | +0.0013 (-1.1) | +0.0047 (+2.2) | +0.0026 | +0.0010 | +0.0012 |
| DR-learner, 17 + context on attempts, clean payment (covered) | +0.0024 (+1.1) | +0.0016 (-1.0) | +0.0010 (+1.0) | +0.0017 | +0.0016 | +0.0056 |
| R-learner, 17 + context on attempts, clean payment (covered) | +0.0027 (+1.3) | +0.0026 (-0.5) | +0.0019 (+1.3) | +0.0024 | +0.0009 | +0.0033 |
| T-learner, 17 inputs on landmarks, clean payment (covered) | +0.0018 (+1.1) | +0.0020 (-0.8) | +0.0016 (+1.1) | +0.0018 | +0.0047 | -0.0018 |
| T-learner, 17 + context on landmarks, clean payment (covered) | +0.0041 (+2.2) | +0.0027 (-0.5) | +0.0024 (+1.3) | +0.0031 | +0.0010 | +0.0003 |
| DR-learner, 17 + context on landmarks, clean payment (covered) | +0.0018 (+0.8) | +0.0021 (-0.8) | +0.0017 (+1.2) | +0.0019 | +0.0023 | +0.0019 |
| R-learner, 17 + context on landmarks, clean payment (covered) | +0.0028 (+1.3) | +0.0011 (-1.2) | +0.0018 (+1.3) | +0.0019 | +0.0021 | +0.0031 |

**Result.** The selected candidate beats the champion on the primary metric (+3.3, +3.6, +3.5 SDs) but **loses on the gate's call Qini** (+0.0010 against +0.0047; the champion's own seed SD is 0.0011, the gate noise 0.0003), so it is not promoted. Nothing is promoted.

**Next challenger, recorded in advance.** The T-learner on 17 + context inputs, trained on the old rows with the old label (the live model's design plus ten inputs), was second on validation. Its numbers: validation primary +4.2, +1.0 and +2.7 SDs better than the champion on calls, SMS and email, gate calls +0.0026 against +0.0013, any contact +0.0018 against +0.0013; test primary +0.0067, +0.0075, +0.0073 against +0.0006, +0.0034, +0.0033 (+6.4, +5.8, +4.8 SDs), gate calls +0.0047 against +0.0047 and any contact +0.0005 against +0.0008 (inside the noise). It would pass the stated rule on test. It is not promoted because it was not the validation pick, so promoting it now would mean choosing on test. It needs the ten context inputs added to `feature_registry.py` (with a `FeatureVector` field, a dbt definition in `case_features.sql` and a Feast field each, and the lineage test), then a retrain on the next data window. The confirmation plan is to run the live gate on the next window with this model as the challenger and promote only if it passes there.

**Why not more weight on it.** The gains are largest on the evaluation sets built like the training rows. On the landmark set no candidate is above +2.2 SDs and SMS and email show no gain. The DR evaluation uses the same context inputs in its nuisance models, which favours candidates that use them. The gate metric itself is the old, biased treated-versus-untreated comparison.

**DR- and R-learners did not beat the T-learner** with the same inputs on the cleaner outcome (test, primary: calls +0.0055 and +0.0048 against +0.0043 for the T-learner; SMS +0.0058 and +0.0062 against +0.0070; email +0.0057 and +0.0059 against +0.0073). With a signal this small, correcting for the bank's choices costs as much variance as it removes bias.

## Track 2: other framings

### Best time to call (2.2)

LightGBM on outbound calls to randomly assigned cases: right-party contact from the 17 inputs, context, weekday and the local hour. Fit before 15 Aug (117,186 calls), scored on 59,603 after.

| Measure | Value |
|---|---:|
| AUC without the hour | 0.685 |
| AUC with the hour | 0.729 |
| Observed: evening (17 to 20h) minus day (8 to 16h), comparable calls (deciles of the no-hour score) | +20.9 pts [+20.1, +21.8] |
| Observed: evening minus day inside the same customer (18,067 customers) | +24.0 pts [+23.6, +24.8] |
| Predicted right-party contact, as booked | 43.5% |
| Predicted, each call at its best allowed hour (uncapped) | 59.8% (lift +16.3 pts) |
| Predicted, evening hours capped at today's volume per weekday and hour | 50.9% (**lift +7.4 pts** [+7.2, +7.5]) |

Observed rate by hour (outbound calls, all cases):

| Hour | Calls | Right-party contact |
|---|---:|---:|
| 5:00 | 168 | 38.7% |
| 6:00 | 21 | 38.1% |
| 8:00 | 8,103 | 33.9% |
| 9:00 | 11,804 | 29.3% |
| 10:00 | 13,873 | 29.6% |
| 11:00 | 13,902 | 36.0% |
| 12:00 | 11,810 | 41.6% |
| 13:00 | 13,028 | 39.3% |
| 14:00 | 12,894 | 40.1% |
| 15:00 | 12,689 | 41.7% |
| 16:00 | 14,516 | 46.7% |
| 17:00 | 17,544 | 62.8% |
| 18:00 | 19,031 | 63.5% |
| 19:00 | 17,737 | 61.2% |
| 20:00 | 9,635 | 56.2% |
| 21:00 | 15 | 40.0% |
| 22:00 | 19 | 42.1% |

The headline is the observed gap and the capacity-respecting +7.4 points; the +16.3 is the same model with no capacity limit. The capped plan gives the 21,672 evening slots booked today to the cases that gain most and puts every other call in the day. `channel_capacity` lists 11,463 call units a day in the 17:00 to 21:00 band against 2,042 used, so even the uncapped plan fits the recorded capacity; the team's staffing is the real limit. Every proposed hour is inside the customer's calling window (all 1,017,885 customers have 07:00 to 21:00; the script asserts it) and the weekday is not changed, so the Sunday rule in `kept.nba.rules` is not touched. The model is predictive, hour was not randomised, and the within-customer comparison is the check against "who gets called when". Not built: booking through `CallCapacity` and a card change; that is a decision for the team.

### Self-cure (2.1)

LightGBM on the 17 inputs for the first landmark of each randomly assigned case (day 1), outcome: cured within about 30 days. Fit on cases opened before 1 Jun (isotonic calibration on the last fifth of them), scored on 26,489 after.

| Measure | Value |
|---|---:|
| AUC (time split) | 0.800 |
| AUC, out of fold over every case | 0.773 |
| Brier, calibrated / raw / constant rate | 0.159 / 0.191 / 0.195 |

Predicted against observed by score decile (time split):

| Decile | Predicted | Observed | Cases |
|---|---:|---:|---:|
| 1 | 5.0% | 1.4% | 4,465 |
| 2 | 11.5% | 4.8% | 1,976 |
| 3 | 21.9% | 9.6% | 1,819 |
| 4 | 31.3% | 19.9% | 6,865 |
| 5 | 36.6% | 24.6% | 1,573 |
| 6 | 41.9% | 35.5% | 3,367 |
| 7 | 47.7% | 53.1% | 1,952 |
| 8 | 52.4% | 56.1% | 2,032 |
| 9 | 55.6% | 64.5% | 2,440 |

It ranks cases well (AUC 0.80) and beats the constant rate on Brier, but it is not well calibrated out of period: it over-predicts in the lower deciles (11.5% predicted, 4.8% observed in the second) because the case mix drifts. Treat the ranking as usable and the probabilities as needing a refresh each retrain.

The bank's randomised `no_contact_holdout` cell, compared with worked cells (champion, challenger A and B), on the same model out of fold over every case. Cure within about 30 days, held out against worked:

| Group | Cases (held / worked) | Cure (held / worked) | Difference, pts [95% CI] | Attempts per case (held / worked) |
|---|---:|---:|---:|---:|
| top 50% | 1,387 / 26,943 | 61.4% / 61.1% | +0.2 [-2.4, +2.9] | 1.66 / 2.19 |
| top 30% | 844 / 16,154 | 62.3% / 62.9% | -0.6 [-4.0, +2.8] | 1.65 / 2.15 |
| top 20% | 556 / 10,776 | 62.4% / 63.7% | -1.3 [-5.5, +2.8] | 1.69 / 2.12 |
| top 10% | 276 / 5,390 | 64.5% / 67.4% | -2.9 [-8.7, +2.9] | 1.69 / 2.05 |
| bottom 50% | 1,455 / 26,874 | 18.2% / 19.7% | -1.5 [-3.5, +0.6] | 2.39 / 2.88 |

Difference in differences, top half minus bottom half: **+1.7 pts [-1.6, +5.0]**. For predicted self-curers the held-out cases cure no worse (top half +0.2 points, but the interval runs from -2.4 to +2.9), and the bottom half is -1.5 [-3.5, +0.6]. The data cannot separate the two halves, so "contact adds nothing for self-curers and something for the rest" is not shown. The check is also weaker than it looks: the holdout was mostly contacted anyway (73.5% any contact, `evidence.md` section 1), so it compares 1.7 attempts with 2.2, not zero with some, and it understates any effect of skipping contact entirely. **Skipping or delaying contact for predicted self-curers is a pilot hypothesis.**

What it would be worth, if the hypothesis holds (about 530 new cases a day, all cases, last 12 months). "Delayed" uses the contact difference seen in the holdout; "skipped" is an extrapolation to no contact at all, the number to test in a pilot:

| Share of new cases | Contacts saved per night (delayed) | Cost saved per year (delayed) | Contacts saved per night (skipped) | Cost saved per year (skipped) |
|---|---:|---:|---:|---:|
| top 50% | 138 | $13,925 | 579 | $101,816 |
| top 30% | 80 | $6,922 | 342 | $59,955 |
| top 20% | 45 | $2,586 | 225 | $38,983 |

### Policy tree (2.4) and call split (2.5)

A depth-3 tree on out-of-fold DR scores per arm (clean payment, covered cases, overlap rows), fitted before 15 Aug, valued on the decisions after it: the DR gain of the rows the rule treats, per 1,000 decisions in the test population, and extra payers per 1,000 contacts.

| Arm | Rule | Share treated | Gain per 1,000 decisions [95% CI] | Extra payers per 1,000 contacts |
|---|---|---:|---:|---:|
| call | tree (depth 3) | 44% | +13.4 [+9.3, +17.3] | +30.7 |
| call | live model, same share | 44% | +6.2 [+1.1, +10.5] | +14.2 |
| call | treat everyone | 100% | +11.7 [+4.5, +18.1] | +11.7 |
| call | not comparable: `nba_recommendation_last` is look-ahead | 48% | +22.6 [+18.1, +26.8] | +47.4 |
| sms payment link | tree (depth 3) | 58% | +12.4 [+7.6, +17.6] | +21.3 |
| sms payment link | live model, same share | 58% | +8.1 [+3.3, +12.7] | +13.9 |
| sms payment link | treat everyone | 100% | +4.2 [-1.8, +9.8] | +4.2 |
| sms payment link | not comparable: `nba_recommendation_last` is look-ahead | 15% | -10.9 [-14.9, -7.4] | -73.5 |
| email | tree (depth 3) | 31% | +3.0 [-1.1, +7.4] | +9.7 |
| email | live model, same share | 31% | +3.7 [+0.3, +8.3] | +11.8 |
| email | treat everyone | 100% | +1.0 [-5.6, +7.2] | +1.0 |
| email | not comparable: `nba_recommendation_last` is look-ahead | 0% | +0.0 [+0.0, +0.0] | +0.0 |

The "not comparable" rows score `collections_cases.nba_recommendation_last`, which is the last next-best-action shown to the agent as of the 28 Sep snapshot, so it encodes how each case ended (next section). They are kept only to show what the field does when used as a rule; no conclusion about the bank's targeting rests on them. The comparison that holds is among decision-time rules: the tree beats the live model on calls and SMS at the same share (calls +13.4 against +6.2; the live model's top 44% adds less than treating every call decision, +11.7), and the tree is readable: for calls it treats cases with no contact in the last 7 days whose promise falls due within about 5 days and whose cohort keeps promises; the rules for SMS and email lean on days since the last contact and cohort rates. Leaf values and thresholds are in `data/exports/reports/uplift_policy.json`. The DR nuisance models use the same context inputs as the tree, which favours the tree; email shows no rule above the noise.

Call split: 45.5% of calls reach the right party. Against waiting, the DR effect on clean payment is -0.4 pts [-1.2, +0.2] for calls that reached the customer and -0.4 [-0.9, +0.2] for those that did not, on 31% and 38% of rows after trimming. Neither is distinguishable from zero, and reaching the customer is not randomised, so no split of the call effect is claimed.

Not done: payday timing as the action (2.3; `evidence.md` section 2 already measures it, and the rows here have no payday-dating lever); a dollar call-versus-WAIT model (the dollar effect was not confirmed on landmarks); a causal forest.

## The bank's recommendation is not a decision-time rule

`collections_cases.nba_recommendation_last` is, per the data dictionary, the last next-best-action shown to the agent: one value per case, as of the snapshot. On randomly assigned cases it maps onto the case's final state (`select ... from silver.collections_cases where assignment_method = 'random' group by nba_recommendation_last`):

| `nba_recommendation_last` | Cases | Open | Cured |
|---|---:|---:|---:|
| sms_payment_link | 97,716 | 11.4% | 87.3% |
| (none) | 29,348 | 26.3% | 72.7% |
| call_evening | 8,840 | 100.0% | 0.0% |
| call_daytime | 4,868 | 100.0% | 0.0% |
| offer_hardship_plan | 2,917 | 100.0% | 0.0% |
| send_letter | 2,884 | 100.0% | 0.0% |

Cases whose last recommendation is a call, a hardship plan or a letter never cured; cases whose last recommendation is an SMS link mostly did. As a targeting rule at the time of a decision it looks ahead. An earlier draft of this report read the +22.6 per 1,000 it scores as "the bank beats the live model"; that conclusion is withdrawn. The bank's targeting is not evaluated here.

**Pre-existing issue, same field.** The gate's legacy comparison (`qini_legacy_*` in `src/kept/nba/train.py`, which scores `nba_recommendation_last` as a 0/1 targeting rule), the published "model vs legacy" numbers (for example the Qini against legacy in the deck) and the "The bank's strategy" column of `docs/reports/uplift_learners.md` use this field, so those comparisons share the look-ahead. The gate's champion-versus-challenger decision does not use it (`promote` reads only the models' own Qini). No gate code was changed here.

## What this means (options, not decisions)

- **Whom to call:** among decision-time rules the live call ranking is below both treating every call decision and the tree. The bank's own targeting cannot be assessed from this data, because its recommendation field is look-ahead; an assessment would need a recommendation logged at decision time. Timing (best hour, payday dating) is where the evidence is stronger (`evidence.md` section 2 and the hour result above).
- **Next uplift challenger:** the T-learner with ten context inputs, once the inputs are in the registry, through the live gate on the next window.
- **Pilot:** delay contact for predicted self-curers in one randomised cell; the holdout cell cannot answer it.
- **The gate:** it compares treated with untreated directly and its noise ignores seeds and case clustering. A seed-averaged DR metric on the clean outcome, with case-bootstrap noise, is a fairer companion (`scripts/uplift_learners.py --improve` computes both).

## Limits

- Every causal number is for the overlap population and assumes the 17 inputs plus context capture what drove the bank's choice. Overlap on the landmark rows is poor for the waiting group (36% to 44% kept).
- The clean outcome counts only covered cases (a loan account or an account in the transactions sample, 57% to 83% of decisions) and misses payments recorded only as contact flags. Dollars take the largest of three source totals so nothing is counted twice; they are a floor.
- The landmark design conditions on the case being open two days after the landmark.
- Row-based DR Qini in bootstrap resamples treats the nuisance models as fixed.
- Self-cure probabilities drift out of period; the holdout comparison is underpowered and measures delay, not absence.
- The hour result is a model plus observational checks; capacity is taken from the recorded `channel_capacity` and from the volume the team handled.
- The warehouse was rebuilt on 17 Oct from the release; absolute numbers differ from the 3 Oct reports (the published call Qini is +0.0073, the rebuild gives +0.0041 on average over seeds).

## The gate after this study

`kept train` (`src/kept/nba/train.py`) no longer judges a challenger by one seed against the random-ranking noise. The champion (refitted with its own recipe and input columns) and the challenger are each fitted at three seeds and scored as the mean over them. The margin is twice the case-bootstrap SD of the paired challenger-minus-champion difference (`causal.case_bootstrap` over `causal.gate_qini`), for calls and for any contact; the old random-ranking noise is still reported (`noise_*`). A challenger is promoted only if it beats the champion by more than that margin on calls or any contact, is not worse by more than it on the other, and is not worse by more than twice the bootstrap SD of the paired doubly robust Qini on the clean outcome (`paid_clean_14d`, covered cases; nuisance models fitted before the cutoff) for calls or any contact. Both models are also valued against what the bank did with `causal.policy_value` on the clean outcome. The legacy recommendation field is no longer scored (it is look-ahead). Numbers of the last run: `data/exports/reports/train_gate.json`. `kept train --champion <live.pkl> --out <scratch.pkl>` tries a challenger without touching the live model.

## Reproduce

```bash
# data (release unzipped to kept_dl/rel3, hard-linked into data/raw)
uv sync --inexact --extra data --extra model
uv run kept land && uv run kept build --silver-only && uv run kept match --train-sample-mod 5
uv run kept build --gold-only --crosswalk <published identity_crosswalk_4ac9c37-20261003-full-train5.parquet>
uv run kept features --training      # training_rows (+ clean outcome), training_weeks, case_features (with the context)
uv run kept train                    # the reproduced champion (cutoff 2026-08-15)
uv run python scripts/uplift_diagnostics.py --part 1   # Step 0, old rows: overlap, effects, heterogeneity, rolling windows
uv run python scripts/uplift_diagnostics.py --part 2   # overlap x clean outcome, both row sets, four outcomes, flag tie-breaker
uv run python scripts/uplift_diagnostics.py --part 3   # self-cure and best hour
uv run python scripts/uplift_diagnostics.py --part 4   # policy trees and the call split
uv run python scripts/uplift_diagnostics.py --part 5   # gate Qini for seeds 0 to 3
uv run python scripts/uplift_learners.py --improve --warehouse data/warehouse/kept.duckdb   # the 12 candidates
```

Outputs are written to `data/exports/reports/uplift_*.json` (not committed). Tests: `tests/nba/test_causal.py`.
