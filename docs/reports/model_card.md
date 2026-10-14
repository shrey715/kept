# Model card: the promise model and the uplift model

Written by `scripts/model_card.py` on 2026-10-14 from held-out data the models never saw (the JSON behind the Portfolio page's models panel is `data/exports/reports/model_card.json`).

## Promise model: will this promise be kept?

LightGBM on six point-in-time features, isotonic-calibrated; trained on promises due before 2026-07-15, tested on the 50,653 due after.

| Measure | Value |
|---|---:|
| AUC | 0.610 |
| Brier score | 0.221 |
| Kept rate in the test window | 35.4% |

Alone it ranks promises less well than the bank's own score (AUC 0.702); combined with it, 0.728 (`docs/reports/evidence.md` §3). A first version scored 0.92 because one feature, `amount_ratio`, encoded the outcome; it was removed.

**Calibration (predicted against observed, by score bin)**

| Predicted | Observed | Promises |
|---:|---:|---:|
| 14.4% | 9.2% | 273 |
| 26.6% | 24.8% | 9,489 |
| 35.9% | 32.3% | 23,044 |
| 45.3% | 39.3% | 10,834 |
| 55.5% | 50.3% | 3,672 |
| 63.8% | 57.7% | 2,563 |
| 74.2% | 67.4% | 760 |

**What drives it (share of mean |TreeSHAP|)**

| Feature | Share |
|---|---:|
| Days from promise to due date | 44.7% |
| Days past due when promised | 42.5% |
| Broken promises, prior 90 days | 3.6% |
| Days from last payday to due date | 3.2% |
| Share of past promises kept | 3.1% |
| Days from due date to next payday | 2.8% |

## Uplift model: which action changes the outcome?

A LightGBM T-learner: one model per action against waiting, on paid-within-14-days; trained on decisions before 2026-08-15, tested on the 141,350 after.

| Measure | Value |
|---|---:|
| Qini, any contact against waiting | 0.0008 |
| Spread of Qini over 30 random rankings | 0.0005 |

The signal is small and the gate treats it that way: a challenger replaces the champion only if it beats it by more than the noise on held-out decisions (`docs/reports/tuning.md`: a 40-candidate search did not).

**Strongest inputs per action (mean |TreeSHAP|, percentage points)**

| Action | Inputs |
|---|---|
| call | Cash-flow trend (1.2), Similar cases recovered (1.0), Answer rate (1.0), Similar cases' promises kept (1.0), Days past due (0.7) |
| sms payment link | Similar cases recovered (2.3), Similar cases' promises kept (1.5), Cash-flow trend (1.2), Answer rate (0.8), Card utilisation trend (0.7) |
| email | Similar cases recovered (3.9), Cash-flow trend (1.9), Payment-link use (1.0), Similar cases' promises kept (0.8), Days past due (0.7) |

## Limits

- Actions were not randomised except across the bank's strategy cells, so uplift is estimated, not measured; the pilot's randomised due-date cell is how it gets measured.
- Protected attributes are not model inputs; the fairness and invariance checks are in `docs/reports/fairness_report.pdf`.
