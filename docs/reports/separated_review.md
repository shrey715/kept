# Review: hardship reviews for separated customers

The fairness report found separated customers get a hardship review on 51% of their cards against 39–40% for every
other marital status (ratio 0.76, a flag). Marital status is a protected attribute: the model never sees it (scrambling
it changes 0 of 96,000 cards). So where does the gap come from? Read on tonight's cards (12 Oct) from `nba.cards`,
`silver.int_open_case`, `silver.collections_cases` and the golden record.

| | Separated | Everyone else |
|---|---:|---:|
| Hardship reviews tonight | 4,390 | 33,078 |
| Hardship stated as **separation** itself | **441 (10.0%)** | 44 (0.1%) |
| Customer carries the **vulnerability flag** | **694 (15.8%)** | 3,458 (10.5%) |
| Source: coded by an agent | 63.6% | 59.0% |
| Source: no hardship on the case (notes, cash flow or the flag) | 28.2% | 32.9% |
| Source: the customer's own form | 5.5% | 5.6% |
| Source: the bank's model | 2.7% | 2.5% |

**What the sample shows.** 50 separated customers' hardship-review cards, picked at random: 29 carry an agent-coded
hardship, 11 the vulnerability flag, 7 separation as the stated hardship, 3 a signal from notes or cash flow. Every one
traces to something a person recorded or the customer said, not to a score.

**Reading.** Separation is a money shock, and the bank's own hardship policy names it as one. Separated customers say so,
agents record it, and the vulnerability flag is more common among them. The protective treatment follows the evidence on
the case, which is the design: hardship only ever protects a customer. We'd keep the flag with compliance and re-check the
ratio monthly.

Reproduce: the queries are in the fairness work on branch history (`scripts/fairness_report.py` for the ratios; the
source split is `nba.cards` joined to `silver.int_open_case.hardship_source`, `silver.collections_cases.hardship_reason`
and `gold.c360_customer.vulnerability_flag`, compliance roles only).
