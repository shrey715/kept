# Best-hour call booking

Written by `scripts/best_hour_replay.py` on the 59,603 outbound calls on randomly assigned cases from 2026-08-15 to the end of the data (30 days), booked day by day through
`kept.nba.ranking.CallCapacity`, the class the nightly batch uses. Nothing here changes the default nightly run: the booking is behind `kept score --best-hour` (or `KEPT_BEST_HOUR=1`) and is off unless asked for.

## What it does

With the switch off, a call goes into the **earliest** half-hour slot with capacity inside the customer's calling hours. With it on, the call goes into the slot with the
highest predicted chance of reaching the right party, among the free slots **on the same local day as the earliest one** (never a later day), inside the customer's hours
and the operating hour's capacity, Sunday rules unchanged; ties go to the earlier slot. When it moves a call, the card says so in one line, with the model's numbers
("Booked 18:00: this customer is likelier to answer then (62% chance of reaching them, against 41% at 07:00)"; the line goes in the card's why-not text).

**Predictor shipped: a per-case LightGBM** (`data/exports/models/best_hour.pkl`, `kept train-best-hour`): P(right-party contact | local hour, weekday, the 17 model inputs of the uplift model).
Its inputs are registry inputs only (no language, postal code, accent, age or other protected attribute or proxy; `tests/nba/test_best_hour.py` runs `assert_no_denied`). Fitted on
calls before 2026-08-15, it scores AUC 0.717 on the later calls (the study's version with three extra context inputs that are not in the serving vector scored 0.729, `uplift_improvement.md`).
A per-case model was servable cleanly, so the fall-back observed-rate table was not needed.

## Result (a prediction, not a measured payment gain)

**Headline, against what the bank actually did, at today's team volume: predicted right-party contact 43.4% to 45.1%, +1.6 [+1.5, +1.8] points** (95% case-bootstrap interval).
"What the bank did" is the hour every one of these calls was actually made at, valued by the same model. Team volume is what the team handled per weekday and hour (average over the window's dates, rounded up): the booking may not use more evening hours than the team works today.

Other baselines, each named:

- **Against Kept's current earliest-slot booking** (40.8%): +4.2 [+3.9, +4.5] points at team volume. That baseline is itself worse than the bank's own timing (40.8% against 43.4%): the earliest free hour is the first hour of the day, the least answered, so today's booking loses contact the bank's calls had.
- **With the full recorded capacity** (`silver.channel_capacity`, as `kept score` reads it; far above the calls made, so it is only real if the team staffs the evening capacity it has on paper): 57.0%, +13.6 [+13.4, +13.8] points against the bank's hours and +26.5 [+26.4, +26.7] against the earliest-slot booking (30.5%).
- The study (`uplift_improvement.md`) estimated +7.4 points against the hours as booked with a simpler capacity model (each evening hour capped by the total handled over the window, extra context inputs, no booking class). This replay is the more careful one and gets less (+1.6 [+1.5, +1.8] at team volume); likely reasons, not separated: the cap here is per date, calls are booked one at a time through the real booking class, capacity is in bank time while calls are in customer time, and the model here has only inputs available at serving (AUC 0.717, the study's 0.729).

| Booking | Predicted right-party contact | Observed hourly rate, same bookings | Calls moved off their earliest slot |
|---|---:|---:|---:|
| The bank: hours actually called at | 43.4% | 47.8% |  |
| Team volume, switch off (earliest slot) | 40.8% | 45.3% |  |
| **Team volume, switch on** | 45.1% | 49.8% | 84% |
| Recorded capacity, switch off | 30.5% | 35.9% |  |
| Recorded capacity, switch on | 57.0% | 61.3% | 100% |

The last column re-values the same bookings with the observed right-party rate by hour before the cutoff, with no per-case model: +2.0 points against the bank's hours (47.8%; their actual outcome was 43.9%) at team volume.

**This is a large operational change.** With the switch on, **84% of calls** are booked into a different hour than the earliest free one (100% at recorded capacity), and the day's hour mix shifts toward the late afternoon and evening, as below. Agents' shifts, not the model, decide whether those hours exist.

Share of calls by local hour:

| Hour (customer-local) | The bank's hours | Team volume, off | Team volume, on | Recorded, off | Recorded, on |
|---:|---:|---:|---:|---:|---:|
| 5:00 | 0% | 0% | 0% | 0% | 0% |
| 7:00 | 0% | 5% | 10% | 31% | 0% |
| 8:00 | 5% | 7% | 4% | 56% | 0% |
| 9:00 | 7% | 8% | 1% | 7% | 0% |
| 10:00 | 8% | 7% | 1% | 2% | 0% |
| 11:00 | 8% | 8% | 10% | 2% | 0% |
| 12:00 | 7% | 7% | 13% | 1% | 3% |
| 13:00 | 7% | 8% | 4% | 0% | 0% |
| 14:00 | 7% | 8% | 5% | 0% | 2% |
| 15:00 | 7% | 8% | 5% | 0% | 3% |
| 16:00 | 8% | 9% | 7% | 0% | 3% |
| 17:00 | 10% | 9% | 23% | 0% | 73% |
| 18:00 | 11% | 8% | 12% | 0% | 13% |
| 19:00 | 10% | 6% | 5% | 0% | 3% |
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

## Limits

- It is a **predicted** right-party-contact gain. Hour was not randomised. The model picks the hour it scores highest and is then scored by itself, which flatters the gain; the observed-hourly-rate column
  is the check that does not use the per-case model, and the within-customer comparison in the study (evening calls reach the same customer 24 points more often) is the check against "who gets called when".
  A pilot cell (best-hour booking on half the calls, the rest as today) would measure it.
- Right-party contact is the outcome, not payment: the study found contact itself barely moves payment, so a payment gain is not claimed.
- Evening capacity is a staffing question. The recorded capacity book is generous; the team-volume book assumes no more evening staff than today.
- Calls are replayed in decision order within a day; the nightly orders by balance, so who gets the scarce hours differs.
- Every customer record allows calls from 07:00, but almost no call was ever made before 08:00 local, so the model has little data there (it treats 07:00 like 08:00); the earliest-slot booking uses 07:00.
