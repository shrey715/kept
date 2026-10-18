# Best-hour call booking

Written by `scripts/best_hour_replay.py` on the 59,603 outbound calls on randomly assigned cases from 2026-08-15 to the end of the data (30 days), booked day by day through
`kept.nba.ranking.CallCapacity`, the class the nightly batch uses. **The booking is on by default**: `kept score` uses it whenever `data/exports/models/best_hour.pkl` exists, and the nightly run trains that model when it is missing or a week old (`kept train-best-hour --if-older-than 7`). `--no-best-hour` (or `KEPT_BEST_HOUR=0`) goes back to the earliest-slot booking.

## What it does

With the switch off, a call goes into the **earliest** half-hour slot with capacity inside the customer's calling hours. With it on, the call goes into the slot with the
highest predicted chance of reaching the right party, among the free slots **on the same local day as the earliest one** (never a later day), inside the customer's hours
and the operating hour's capacity, Sunday rules unchanged; ties go to the earlier slot. When it moves a call, the card says so in one line, with the model's numbers
("Booked 18:00: this customer is likelier to answer then (62% chance of reaching them, against 41% at 07:00)"; the line is the card's `booking_text`, shown under the call window).

**Predictor shipped: a per-case LightGBM** (`data/exports/models/best_hour.pkl`, `kept train-best-hour`): P(right-party contact | local hour, weekday, the 17 model inputs of the uplift model).
Its inputs are registry inputs only (no language, postal code, accent, age or other protected attribute or proxy; `tests/nba/test_best_hour.py` runs `assert_no_denied`). Fitted on
calls before 2026-08-15, it scores AUC 0.717 on the later calls (the study's version with three extra context inputs that are not in the serving vector scored 0.729, `uplift_improvement.md`).
A per-case model was servable cleanly, so the fall-back observed-rate table was not needed.

## Result (a prediction, not a measured payment gain)

**Headline, against what the bank actually did, at today's team volume: predicted right-party contact 43.4% to 45.1%, +1.7 [+1.5, +1.9] points** (95% case-bootstrap interval).
"What the bank did" is the hour every one of these calls was actually made at, valued by the same model. Team volume is what the team handled per weekday and hour (average over the window's dates, rounded up): the booking may not use more evening hours than the team works today.

Other baselines, each named:

- **Against Kept's current earliest-slot booking** (40.8%): +4.3 [+4.0, +4.6] points at team volume. That baseline is itself worse than the bank's own timing (40.8% against 43.4%): the earliest free hour is the first hour of the day, the least answered, so today's booking loses contact the bank's calls had.
- **With the full recorded capacity** (`silver.channel_capacity`, as `kept score` reads it; far above the calls made, so it is only real if the team staffs the evening capacity it has on paper): 57.1%, +13.6 [+13.5, +13.8] points against the bank's hours and +26.6 [+26.4, +26.7] against the earliest-slot booking (30.5%).
- The study (`uplift_improvement.md`) estimated +7.4 points against the hours as booked with a simpler capacity model (each evening hour capped by the total handled over the window, extra context inputs, no booking class). This replay is the more careful one and gets less (+1.7 [+1.5, +1.9] at team volume); likely reasons, not separated: the cap here is per date, calls are booked one at a time through the real booking class, capacity is in bank time while calls are in customer time, and the model here has only inputs available at serving (AUC 0.717, the study's 0.729).

| Booking | Predicted right-party contact | Observed hourly rate, same bookings | Calls moved off their earliest slot |
|---|---:|---:|---:|
| The bank: hours actually called at | 43.4% | 47.8% |  |
| Team volume, switch off (earliest slot) | 40.8% | 45.4% |  |
| **Team volume, switch on** | 45.1% | 49.7% | 84% |
| Recorded capacity, switch off | 30.5% | 35.9% |  |
| Recorded capacity, switch on | 57.1% | 61.3% | 99% |

The last column re-values the same bookings with the observed right-party rate by hour before the cutoff, with no per-case model: +2.0 points against the bank's hours (47.8%; their actual outcome was 43.9%) at team volume.

**This is a large operational change.** With the switch on, **84% of calls** are booked into a different hour than the earliest free one (99% at recorded capacity), and the day's hour mix shifts toward the late afternoon and evening, as below. Agents' shifts, not the model, decide whether those hours exist.

Share of calls by local hour:

| Hour (customer-local) | The bank's hours | Team volume, off | Team volume, on | Recorded, off | Recorded, on |
|---:|---:|---:|---:|---:|---:|
| 5:00 | 0% | 0% | 0% | 0% | 0% |
| 7:00 | 0% | 6% | 10% | 31% | 0% |
| 8:00 | 5% | 7% | 4% | 56% | 0% |
| 9:00 | 7% | 7% | 2% | 7% | 0% |
| 10:00 | 8% | 7% | 1% | 2% | 0% |
| 11:00 | 8% | 8% | 10% | 2% | 0% |
| 12:00 | 7% | 7% | 13% | 1% | 3% |
| 13:00 | 7% | 8% | 4% | 0% | 0% |
| 14:00 | 7% | 8% | 5% | 0% | 2% |
| 15:00 | 7% | 8% | 5% | 0% | 2% |
| 16:00 | 8% | 9% | 7% | 0% | 3% |
| 17:00 | 10% | 9% | 23% | 0% | 73% |
| 18:00 | 11% | 8% | 13% | 0% | 12% |
| 19:00 | 10% | 6% | 4% | 0% | 3% |
| 20:00 | 6% | 3% | 0% | 0% | 0% |
| 21:00 | 0% | 0% | 0% | 0% | 0% |
| 22:00 | 0% | 0% | 0% | 0% | 0% |

Checks, switch on (every booked call; calls with no free slot within a week keep their first slot and are not counted):

| Check | Team volume | Recorded capacity |
|---|---:|---:|
| Calls outside the customer's permitted hours | 0 | 0 |
| Capacity overruns (calls above an operating hour's units) | 0 | 0 |
| Calls moved to a later day than their earliest bookable slot | 0 | 0 |
| Calls left unbooked (no free slot in a week) | 0 | 0 |

## Fairness of the booking

**Team volume**, switch on against the earliest-slot booking, calls on randomly assigned cases from the cutoff; groups of at least 200 calls (protected attributes and proxies from `gold.c360_restricted`, aggregates only). Low-to-high across groups:

| Attribute | Groups | Calls moved | Gain in predicted RPC vs earliest (pts) | Booked from 17:00 | Gap in predicted RPC between groups, earliest -> booked (pts) | At least as good as earliest, observed rates (lowest / highest) |
|---|---:|---:|---:|---:|---:|---:|
| accessibility_needs_flag | 2 | 84% to 85% | +14.6 to +15.5 | 39% to 43% | 1.1 -> 0.8 | 1.00 |
| accessibility_type | 4 | 83% to 89% | +14.4 to +16.3 | 42% to 46% | 1.8 -> 2.8 | 1.00 |
| ccb_deposit_flag | 2 | 84% to 84% | +15.0 to +15.2 | 39% to 41% | 0.1 -> 0.7 | 0.86 |
| citizenship_status | 4 | 83% to 86% | +14.3 to +15.4 | 38% to 43% | 0.3 -> 1.3 | 0.98 |
| customer_accent_region | 5 | 78% to 88% | +12.3 to +18.7 | 28% to 47% | 7.6 -> 5.9 | 1.00 |
| dependants_count | 3 | 84% to 86% | +14.4 to +15.0 | 38% to 40% | 0.2 -> 0.5 | 0.89 |
| gender_code | 4 | 83% to 89% | +13.8 to +16.1 | 35% to 43% | 3.1 -> 1.0 | 0.99 |
| household_size | 5 | 84% to 85% | +14.3 to +14.8 | 38% to 40% | 1.5 -> 1.1 | 0.99 |
| marital_status | 7 | 83% to 85% | +14.0 to +15.1 | 37% to 41% | 1.4 -> 0.7 | 0.91 |
| newcomer_program_flag | 2 | 83% to 84% | +14.6 to +14.6 | 39% to 39% | 1.1 -> 0.5 | 1.00 |
| vulnerability_type | 5 | 84% to 87% | +14.3 to +15.1 | 39% to 41% | 0.6 -> 1.2 | 0.91 |

Groups whose predicted RPC at the booked slot is below what the bank's own hours gave them by more than two standard errors: none.

**Recorded capacity**, switch on against the earliest-slot booking, calls on randomly assigned cases from the cutoff; groups of at least 200 calls (protected attributes and proxies from `gold.c360_restricted`, aggregates only). Low-to-high across groups:

| Attribute | Groups | Calls moved | Gain in predicted RPC vs earliest (pts) | Booked from 17:00 | Gap in predicted RPC between groups, earliest -> booked (pts) | At least as good as earliest, observed rates (lowest / highest) |
|---|---:|---:|---:|---:|---:|---:|
| accessibility_needs_flag | 2 | 99% to 99% | +26.2 to +26.6 | 89% to 89% | 0.1 -> 0.5 | 1.00 |
| accessibility_type | 4 | 99% to 100% | +25.0 to +27.5 | 88% to 94% | 1.5 -> 3.6 | 1.00 |
| ccb_deposit_flag | 2 | 99% to 99% | +26.9 to +27.2 | 89% to 89% | 0.5 -> 0.3 | 0.99 |
| citizenship_status | 4 | 99% to 100% | +26.5 to +26.8 | 88% to 89% | 0.2 -> 0.4 | 1.00 |
| customer_accent_region | 5 | 100% to 100% | +27.4 to +30.7 | 89% to 91% | 3.8 -> 6.6 | 1.00 |
| dependants_count | 3 | 99% to 100% | +26.6 to +27.0 | 88% to 88% | 0.2 -> 0.3 | 1.00 |
| gender_code | 4 | 99% to 100% | +26.1 to +27.8 | 88% to 92% | 1.3 -> 0.7 | 1.00 |
| household_size | 5 | 99% to 100% | +25.9 to +27.0 | 87% to 89% | 0.7 -> 1.8 | 1.00 |
| marital_status | 7 | 99% to 100% | +26.5 to +26.7 | 88% to 89% | 0.6 -> 0.7 | 1.00 |
| newcomer_program_flag | 2 | 99% to 99% | +26.6 to +26.7 | 87% to 89% | 0.7 -> 0.7 | 1.00 |
| vulnerability_type | 5 | 99% to 100% | +26.0 to +27.1 | 89% to 91% | 0.5 -> 0.7 | 1.00 |

Groups whose predicted RPC at the booked slot is below what the bank's own hours gave them by more than two standard errors: none.

**Reading, team volume.** The booking never leaves a group worse off than the earliest slot by its own model (every group's share is 100% by construction) and, judged by each group's own observed hourly rates, the lowest share of calls booked into a slot at least as good as the earliest, against the highest, is 0.86 (ccb_deposit_flag): no attribute is under the four-fifths line of 0.80. Booking widens the gap in predicted RPC between groups on 5 of 11 attributes, most on accessibility_type (1.8 to 2.8 points). The group furthest below the bank's own hours, in standard errors, is customer_accent_region = prairie (240 calls): -1.6 points (standard error 1.1).

Per group, team volume, switch on (the attributes the fairness card shows, and any attribute that trips a check or has a gap above 3 points):

| Attribute | Group | Calls | Moved | Predicted RPC: earliest | Predicted RPC: booked | Booked from 17:00 | At least as good, model | At least as good, observed |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| accessibility_needs_flag | False | 55,417 | 84% | 30.4% | 45.0% | 39% | 100% | 100% |
| accessibility_needs_flag | True | 1,664 | 85% | 30.2% | 45.8% | 43% | 100% | 100% |
| citizenship_status | citizen | 44,064 | 84% | 30.4% | 45.0% | 39% | 100% | 100% |
| citizenship_status | permanent_resident | 8,015 | 83% | 30.3% | 44.6% | 38% | 100% | 100% |
| citizenship_status | study_permit | 1,789 | 85% | 30.5% | 45.9% | 43% | 100% | 100% |
| citizenship_status | work_permit | 2,600 | 86% | 30.4% | 45.0% | 40% | 100% | 98% |
| customer_accent_region | atlantic | 250 | 80% | 28.7% | 44.1% | 44% | 100% | 100% |
| customer_accent_region | bc | 232 | 88% | 30.0% | 48.7% | 47% | 100% | 100% |
| customer_accent_region | newcomer_english | 219 | 78% | 26.7% | 43.0% | 44% | 100% | 100% |
| customer_accent_region | prairie | 240 | 79% | 30.5% | 42.8% | 28% | 100% | 100% |
| customer_accent_region | southern_ontario | 769 | 85% | 29.7% | 45.1% | 40% | 100% | 100% |
| gender_code | F | 27,539 | 84% | 30.3% | 44.9% | 39% | 100% | 99% |
| gender_code | M | 28,016 | 84% | 30.4% | 45.0% | 39% | 100% | 100% |
| gender_code | U | 523 | 89% | 29.6% | 45.7% | 43% | 100% | 100% |
| gender_code | X | 513 | 83% | 30.8% | 44.6% | 35% | 100% | 100% |
| household_size | 1 | 16,335 | 84% | 30.3% | 44.8% | 40% | 100% | 100% |
| household_size | 2 | 12,647 | 84% | 30.5% | 44.8% | 38% | 100% | 99% |
| household_size | 3 | 7,357 | 84% | 30.5% | 45.3% | 40% | 100% | 99% |
| household_size | 4 | 2,776 | 85% | 30.0% | 44.8% | 40% | 100% | 99% |
| household_size | 5 | 741 | 84% | 29.7% | 44.2% | 40% | 100% | 100% |
| marital_status | common_law | 7,096 | 84% | 30.2% | 45.1% | 40% | 100% | 100% |
| marital_status | divorced | 3,418 | 83% | 30.6% | 45.0% | 39% | 100% | 99% |
| marital_status | married | 17,677 | 84% | 30.4% | 45.0% | 39% | 100% | 99% |
| marital_status | separated | 5,339 | 85% | 30.1% | 44.8% | 39% | 100% | 100% |
| marital_status | single | 15,178 | 84% | 30.5% | 45.2% | 39% | 100% | 100% |
| marital_status | undisclosed | 2,520 | 83% | 30.4% | 44.4% | 37% | 100% | 91% |
| marital_status | widowed | 1,497 | 85% | 30.0% | 45.1% | 41% | 100% | 100% |
| vulnerability_type | domestic_situation | 1,277 | 87% | 29.5% | 44.0% | 39% | 100% | 100% |
| vulnerability_type | financial_hardship | 4,924 | 85% | 29.7% | 44.8% | 41% | 100% | 91% |
| vulnerability_type | mental_health | 1,220 | 85% | 29.4% | 44.2% | 40% | 100% | 100% |
| vulnerability_type | natural_disaster | 931 | 84% | 29.7% | 44.1% | 39% | 100% | 99% |
| vulnerability_type | serious_illness | 1,858 | 84% | 29.2% | 43.6% | 39% | 100% | 99% |

## Limits

- It is a **predicted** right-party-contact gain. Hour was not randomised. The model picks the hour it scores highest and is then scored by itself, which flatters the gain; the observed-hourly-rate column
  is the check that does not use the per-case model, and the within-customer comparison in the study (evening calls reach the same customer 24 points more often) is the check against "who gets called when".
  A pilot cell (best-hour booking on half the calls, the rest as today) would measure it.
- Right-party contact is the outcome, not payment: the study found contact itself barely moves payment, so a payment gain is not claimed.
- Evening capacity is a staffing question. The recorded capacity book is generous; the team-volume book assumes no more evening staff than today.
- The fairness section is a replay on a past window, not a check of tonight's cards. Proposal, not built: a per-group check in the release gate that, each night, reports the share of calls booked into a slot at least as good as the earliest per protected group (and the gap in predicted RPC) and stops the booking switch if a group of 1,000+ calls falls under 0.80 of the best group's. `kept invariance` (tonight's cards must not change when protected attributes are scrambled) has to be run with the booking on, on a machine with the disk for it; it was not run here.
- Calls are replayed day by day, largest balance first, as the nightly does. The nightly books every open case, largest balance first; here only that day's calls compete for the hours.
- Every customer record allows calls from 07:00, but almost no call was ever made before 08:00 local, so the model has little data there (it treats 07:00 like 08:00); the earliest-slot booking uses 07:00.
