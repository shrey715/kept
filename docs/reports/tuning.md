# Uplift model: hyperparameter search

40 candidates (the defaults plus 39 random draws), compared on decisions from 15 Jul to 15 Aug (inside the training period); the best was refit on everything before 15 Aug and judged once on the test decisions after it, by the nightly's own gate.

    uv run python scripts/tune_uplift.py

## On the test decisions

| Model | Qini, calls | noise | Qini, any contact | noise |
|---|---:|---:|---:|---:|
| Champion (live) | 0.0073 | 0.0003 | 0.0008 | 0.0003 |
| Tuned challenger | 0.0029 | 0.0003 | -0.0006 | 0.0003 |

**Gate: worse than the champion beyond noise: champion kept.** The champion stays; the search is on record so nobody has to rerun it.

## Best settings (validation window)

```json
{
 "num_leaves": 15,
 "min_child_samples": 100,
 "learning_rate": 0.1,
 "n_estimators": 100,
 "reg_lambda": 20.0,
 "colsample_bytree": 1.0
}
```

## Every candidate (validation score: Qini over noise, calls plus any contact)

| # | score | num_leaves | min_child_samples | learning_rate | n_estimators | reg_lambda | colsample_bytree |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10.86 | 15 | 100 | 0.1 | 100 | 20.0 | 1.0 |
| 2 | 9.99 | 7 | 600 | 0.1 | 100 | 5.0 | 1.0 |
| 3 | 9.14 | 15 | 600 | 0.02 | 100 | 5.0 | 1.0 |
| 4 | 9.10 | 15 | 100 | 0.1 | 100 | 1.0 | 0.8 |
| 5 | 9.05 | 31 | 600 | 0.1 | 100 | 5.0 | 0.8 |
| 6 | 9.03 | 15 | 300 | 0.02 | 100 | 5.0 | 1.0 |
| 7 | 9.00 | 15 | 200 | 0.02 | 100 | 5.0 | 0.8 |
| 8 | 8.69 | 15 | 300 | 0.02 | 100 | 1.0 | 1.0 |
| 9 | 8.51 | 7 | 100 | 0.02 | 400 | 1.0 | 1.0 |
| 10 | 8.50 | 31 | 300 | 0.05 | 100 | 0.0 | 1.0 |
| 11 | 8.47 | 7 | 200 | 0.02 | 400 | 0.0 | 0.8 |
| 12 | 8.34 | 15 | 300 | 0.02 | 400 | 0.0 | 1.0 |
| 13 | 8.27 | 15 | 300 | 0.02 | 200 | 20.0 | 0.6 |
| 14 | 7.45 | 7 | 600 | 0.1 | 400 | 5.0 | 1.0 |
| 15 | 6.92 | 31 | 600 | 0.05 | 400 | 1.0 | 1.0 |
| 16 | 6.54 | 15 | 100 | 0.1 | 200 | 0.0 | 1.0 |
| 17 | 6.01 | 15 | 200 | 0.1 | 400 | 20.0 | 1.0 |
| 18 | 5.81 | 31 | 600 | 0.1 | 200 | 1.0 | 1.0 |
| 19 | 5.49 | 31 | 200 | 0.1 | 200 | 20.0 | 1.0 |
| 20 | 5.34 | 7 | 300 | 0.02 | 100 | 0.0 | 1.0 |
| 21 | 5.08 | 7 | 600 | 0.05 | 400 | 1.0 | 0.8 |
| 22 | 4.35 | 31 | 600 | 0.1 | 200 | 0.0 | 0.6 |
| 23 | 3.95 | 7 | 300 | 0.02 | 100 | 20.0 | 0.8 |
| 24 | 3.76 | 31 | 600 | 0.05 | 400 | 5.0 | 0.6 |
| 25 | 3.70 | 7 | 100 | 0.1 | 100 | 1.0 | 0.6 |
| 26 | 3.62 | 31 | 100 | 0.02 | 400 | 1.0 | 0.6 |
| 27 | 3.38 | 7 | 600 | 0.02 | 200 | 0.0 | 0.6 |
| 28 | 3.24 | 7 | 300 | 0.05 | 100 | 5.0 | 0.8 |
| 29 | 2.43 | 63 | 600 | 0.02 | 200 | 20.0 | 0.8 |
| 30 | 1.90 | 7 | 300 | 0.1 | 100 | 5.0 | 0.8 |
| 31 | 1.64 | 63 | 600 | 0.1 | 400 | 5.0 | 1.0 |
| 32 | 1.21 | 31 | 300 | 0.1 | 400 | 1.0 | 1.0 |
| 33 | 0.90 | 31 | 100 | 0.1 | 200 | 1.0 | 0.6 |
| 34 | 0.84 | 31 | 100 | 0.05 | 400 | 5.0 | 0.6 |
| 35 | 0.59 | 63 | 100 | 0.1 | 200 | 5.0 | 0.6 |
| 36 | -0.01 | 7 | 200 | 0.1 | 100 | 0.0 | 1.0 |
| 37 | -0.71 | 63 | 100 | 0.05 | 400 | 5.0 | 1.0 |
| 38 | -0.84 | 31 | 100 | 0.1 | 100 | 0.0 | 1.0 |
| 39 | -1.10 | 31 | 300 | 0.1 | 200 | 1.0 | 1.0 |
| 40 | -2.74 | 63 | 100 | 0.1 | 100 | 20.0 | 0.6 |
