# The promise model: calibration, and what a wider model needs

Written by `scripts/promise_study.py`. Intervals and settings as in `evidence.md` §8. Nothing here is tuned on the held-out window.

## Calibration

The kept rate fell from about 63% to about 35% between April and August 2026 and the trees were fitted on the long history, so the card's "N% chance it's kept" was too high. Recipes compared on a validation window (calibrate to 15 Jun, score 15 Jun to 15 Jul); the kept rate was still falling in it:

| Recipe | Mean predicted minus observed, points | Worst band gap, points | Brier |
|---|---:|---:|---:|
| isotonic, 60 days (before) | +10.9 | 12.2 | 0.239 |
| isotonic, 30 days | +6.9 | 8.3 | 0.232 |
| logistic, 60 days | +10.9 | 12.8 | 0.240 |
| logistic, 30 days | +7.0 | 9.6 | 0.233 |
| logistic, 21 days | +5.8 | 8.5 | 0.231 |
| logistic, 14 days (shipped) | +4.6 | 7.8 | 0.230 |

The shortest window wins on the validation window, so the shipped recipe is a logistic map on the last 14 days. Held-out window (promises from 15 Jul 2026), scored once:

| | Mean predicted minus observed, points | Worst band gap, points | Brier | AUC |
|---|---:|---:|---:|---:|
| before (isotonic, 60 days) | +4.1 | 6.9 | 0.221 | 0.610 |
| after (logistic, 14 days) | +0.3 | 6.5 | 0.220 | 0.611 |

By band, held-out (predicted / observed, promises):

| Before | After |
|---|---|
| 14.4% / 9.2% (273) | 8.5% / 14.9% (830) |
| 26.6% / 24.8% (9,489) | 16.3% / 19.4% (1,515) |
| 35.9% / 32.3% (23,044) | 25.7% / 28.4% (13,658) |
| 45.3% / 39.3% (10,834) | 34.8% / 32.9% (18,003) |
| 55.5% / 50.3% (3,672) | 44.2% / 40.9% (11,361) |
| 63.8% / 57.7% (2,563) | 54.5% / 55.9% (4,465) |
| 74.2% / 67.4% (760) | 63.9% / 67.7% (814) |

By month of the promise, held-out (predicted / observed):

| Month | Before | After |
|---|---|---|
| 2026-07 | 41.3% / 35.9% | 37.6% / 35.9% |
| 2026-08 | 40.8% / 35.5% | 37.0% / 35.5% |
| 2026-09 | 35.7% / 34.8% | 31.8% / 34.8% |

What is left is not the level but the shape: since the fall, promises due soon are kept more than the trees expect and promises due in a month less (days to due flattened), which a two-number map cannot follow. The mean gap closes (the first table), the worst band gap barely moves, and the model now runs a little low in the last month. Weighting recent promises in the trees, or fitting them closer to the cutoff, scored worse on the validation window in a trial not repeated here, so the trees are unchanged. `kept train-promises --cutoff <date>` moves the calibration window forward as promises resolve; it is not a nightly step.

## The wide model, and what serving can supply

The §8 model (79 inputs) on the same split: AUC **0.697** on 12,820 test promises; the six inputs the card uses, fitted the same way: **0.614**. A subset ships only if it keeps most of that gain (0.083).

Each group added to the six alone:

| Group | AUC | Share of the gain |
|---|---:|---:|
| balance, contacts and payroll (the case features Kept already serves, in the wide model's own definitions) | 0.652 | 46% |
| monthly account snapshots (utilisation, payment cover, balance and delinquency slopes) | 0.670 | 68% |
| card statements | 0.653 | 47% |
| deposit transactions, last 45 days (without the benefits category, a proxy) | 0.652 | 46% |
| customer record (tenure, declared income, employment, income verified) | 0.642 | 33% |
| loan instalments | 0.625 | 13% |
| bureau pull | 0.624 | 11% |
| promise details and history, month and weekday | 0.630 | 19% |

Cumulatively, cheapest first:

| Inputs | Count | AUC | Share of the gain |
|---|---:|---:|---:|
| balance, contacts and payroll (the case features Kept already serves, in the wide model's own definitions) | 14 | 0.652 | 46% |
| monthly account snapshots (utilisation, payment cover, balance and delinquency slopes) | 23 | 0.681 | 81% |
| card statements | 34 | 0.683 | 83% |
| deposit transactions, last 45 days (without the benefits category, a proxy) | 44 | 0.691 | 93% |
| customer record (tenure, declared income, employment, income verified) | 48 | 0.693 | 96% |

**Not shipped.** What `FeatureVector` carries today reaches under half of the gain (first row above). Most of it needs inputs the serving path does not have: the point-in-time features for a promise are not the point-in-time features for a decision, so they need their own dbt spine (one row per promise at its creation, the training side) and the same SQL at `as_of` for the cases being proposed a promise (the serving side), then registry entries, `FeatureVector` fields, Feast and parity for each, as the ten context inputs got. The monthly account snapshots are the piece that matters (the cumulative table): with them the model keeps most of the gain; the rest adds a few points of it each. The card's sentence would not change. Excluded on purpose: the deposit-transaction benefits category (a proxy for benefit receipt) and anything on the contract's protected or proxy lists.
