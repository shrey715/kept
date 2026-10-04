# Business case: promises dated to payday

From the release's own history (`scripts/business_case.py`; timing from `scripts/payday_timing.py`).
Descriptive, not causal: the gap may partly reflect who gets which due date. The 5% hold-out measures
the real effect after launch.

| promise due | promises | share of promised money paid |
|---|---|---|
| 0-2 days after payday | 8,359 | 62.5% |
| 3-7 days after payday | 7,553 | 60.9% |
| 8+ days after payday | 16,045 | 51.5% |

- Resolved promises due in the 12 months to 28 Sep 2026: **$41,741,848** promised.
- Where the payday is known, 24% of the promised money fell 3-7 days after payday and 50% 8+ days after.
- Kept dates promises 1-2 days after payday. If those promises were paid like the 0-2-day group: **+$2,458,413 a year** ($2,295,444 from the 8+ day group, $162,969 from 3-7), 5.9% more of the promised money.

Not counted: fewer wasted contacts from uplift targeting (Qini 0.0073 vs 0.0017 for calls) and lower
roll rate, both measured on the hold-out after launch.
