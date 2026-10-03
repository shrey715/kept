# Fairness report (Track B)

Cases scored: 96,000. Compared by protected attribute from `gold.c360_restricted` (compliance only). Four-fifths rule: the lowest group's rate over the highest group's, flagged under 0.8. Groups under 50 cases are not compared.

Outcomes: **any contact action**: action is neither empty nor 'wait'; **call**: action is 'call'; **hardship review**: action is 'hardship_review'.

## Lowest / highest ratio

| attribute | any contact action | call | hardship review | cases with the attribute blank |
|---|---|---|---|---|
| accessibility_needs_flag | 0.99 | 0.95 | 0.97 | 3,458 (0% get a contact action) |
| accessibility_type | 0.93 | 0.64 FLAG | 0.82 | 93,394 (76% get a contact action) |
| ccb_deposit_flag | 1.00 | 0.90 | 0.98 | 51,136 (74% get a contact action) |
| citizenship_status | 0.99 | 0.83 | 0.98 | 4,391 (17% get a contact action) |
| customer_accent_region | 0.86 | 0.57 FLAG | 0.82 | 94,786 (76% get a contact action) |
| dependants_count | 0.94 | 0.87 | 0.82 | 30,681 (70% get a contact action) |
| gender_code | 0.98 | 0.74 FLAG | 0.99 | 4,389 (17% get a contact action) |
| household_size | 0.98 | 0.79 FLAG | 0.93 | 30,741 (70% get a contact action) |
| marital_status | 0.96 | 0.69 FLAG | 0.76 FLAG | 10,685 (54% get a contact action) |
| newcomer_program_flag | 1.00 | 0.97 | 0.98 | 3,458 (0% get a contact action) |
| vulnerability_type | 0.91 | 0.36 FLAG | 0.91 | 82,304 (77% get a contact action) |

## Rates by group

### accessibility_needs_flag

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| False | 89,936 | 78.8% | 3.4% | 40.5% |
| True | 2,606 | 78.2% | 3.6% | 39.3% |
| *(blank, not compared)* | 3,458 | 0.0% | 0.0% | 0.0% |

### accessibility_type

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| braille | 93 | 79.6% | 4.3% | 37.6% |
| extra_time | 412 | 79.6% | 4.1% | 40.0% |
| hearing_impaired | 581 | 78.1% | 3.8% | 40.6% |
| large_print | 789 | 75.8% | 3.0% | 38.4% |
| plain_language | 519 | 79.2% | 3.3% | 36.6% |
| tty_relay | 212 | 81.1% | 4.7% | 44.8% |
| *(blank, not compared)* | 93,394 | 75.9% | 3.3% | 39.0% |

### ccb_deposit_flag

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| False | 32,212 | 78.3% | 4.8% | 42.5% |
| True | 12,652 | 78.0% | 5.4% | 43.4% |
| *(blank, not compared)* | 51,136 | 74.1% | 1.9% | 35.7% |

### citizenship_status

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| citizen | 71,256 | 78.8% | 3.5% | 40.5% |
| permanent_resident | 13,479 | 78.6% | 3.4% | 40.0% |
| study_permit | 2,882 | 79.0% | 3.6% | 40.4% |
| work_permit | 3,992 | 79.5% | 3.0% | 41.0% |
| *(blank, not compared)* | 4,391 | 17.0% | 0.5% | 8.8% |

### customer_accent_region

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| atlantic | 152 | 87.5% | 3.9% | 68.4% |
| bc | 175 | 84.0% | 5.1% | 65.1% |
| franco_ontarian | 67 | 91.0% | 3.0% | 68.7% |
| newcomer_english | 154 | 78.6% | 5.2% | 56.5% |
| prairie | 164 | 86.0% | 4.3% | 64.6% |
| southern_ontario | 502 | 82.9% | 3.2% | 62.5% |
| *(blank, not compared)* | 94,786 | 75.9% | 3.3% | 38.7% |

### dependants_count

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| 0 | 44,208 | 79.0% | 3.5% | 40.5% |
| 1 | 17,852 | 78.6% | 3.5% | 40.3% |
| 2 | 3,004 | 78.3% | 3.0% | 40.0% |
| 3 | 239 | 83.3% | 3.3% | 49.0% |
| 4 | 16 | n/a (too few) | n/a (too few) | n/a (too few) |
| *(blank, not compared)* | 30,681 | 69.8% | 3.1% | 35.7% |

### gender_code

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| F | 44,538 | 78.9% | 3.5% | 40.4% |
| M | 45,242 | 78.7% | 3.4% | 40.5% |
| U | 895 | 79.1% | 3.9% | 40.1% |
| X | 936 | 80.3% | 2.9% | 40.5% |
| *(blank, not compared)* | 4,389 | 17.0% | 0.6% | 8.8% |

### household_size

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| 1 | 25,745 | 78.5% | 3.3% | 39.7% |
| 2 | 21,644 | 78.9% | 3.3% | 40.3% |
| 3 | 11,967 | 78.7% | 3.4% | 40.6% |
| 4 | 4,374 | 78.7% | 3.7% | 40.9% |
| 5 | 1,226 | 77.9% | 3.8% | 40.3% |
| 6 | 303 | 76.9% | 3.0% | 38.0% |
| *(blank, not compared)* | 30,741 | 70.3% | 3.2% | 36.4% |

### marital_status

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| common_law | 11,205 | 79.0% | 3.3% | 39.3% |
| divorced | 5,489 | 79.6% | 4.1% | 39.4% |
| married | 28,778 | 79.2% | 3.5% | 39.7% |
| separated | 8,587 | 76.7% | 2.8% | 51.0% |
| single | 24,618 | 78.8% | 3.5% | 38.6% |
| undisclosed | 4,000 | 78.8% | 3.7% | 39.0% |
| widowed | 2,638 | 76.8% | 3.4% | 39.2% |
| *(blank, not compared)* | 10,685 | 53.8% | 2.5% | 27.4% |

### newcomer_program_flag

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| False | 84,026 | 78.8% | 3.4% | 40.5% |
| True | 8,516 | 78.9% | 3.6% | 39.8% |
| *(blank, not compared)* | 3,458 | 0.0% | 0.0% | 0.0% |

### vulnerability_type

| group | cases | any contact action | call | hardship review |
|---|---|---|---|---|
| bereavement | 246 | 68.3% | 1.2% | 67.1% |
| cognitive_decline | 166 | 71.1% | 0.6% | 70.5% |
| domestic_situation | 1,584 | 72.3% | 1.5% | 70.8% |
| financial_abuse | 111 | 74.8% | 0.9% | 73.9% |
| financial_hardship | 6,088 | 72.1% | 1.7% | 70.4% |
| mental_health | 1,701 | 71.2% | 1.2% | 70.0% |
| natural_disaster | 1,286 | 71.2% | 1.3% | 69.8% |
| serious_illness | 2,514 | 71.9% | 1.5% | 70.4% |
| *(blank, not compared)* | 82,304 | 76.7% | 3.6% | 33.8% |

## Findings (read by hand from the 4 Oct nightly, `nba_cards_90ef96c_20261004`)

Input: Akshat's full nightly (96,000 cards, with the text and cash-flow hardship in gold) and Satvik's
`gold.c360_restricted` (1,052,300 customers). Protected attributes are used here only to check the
recommendations; they are never model inputs (`lineage_violations` checks that in CI).

1. **No protected group is treated materially differently.** The share of cases that get a contact action
   is within 1 to 7% across every group of gender, citizenship, household size, dependants, benefits, and
   accessibility needs (ratios 0.93 to 1.00; marital status 0.96, accent region 0.86 on groups of 67 to 502).
2. **Most "FLAG" cells are on `call`, a rare action (about 3% of cases).** A ratio of two small rates is
   noisy: gender `call` is 3.5% (F), 3.4% (M), 3.9% (U) and 2.9% (X, 936 cases). Nothing there needs action.
3. **Vulnerable customers are routed to hardship review by design.** Every `vulnerability_type` group gets a
   hardship review about 70% of the time against 34% for everyone else, and a call about 1% of the time
   against 3.6%. That is the intended protection (hardship review replaces a collection call), so the gap
   is a feature. Separated customers also get hardship review more often (51% against about 39%), which
   compliance may want to look at: it follows the hardship signals, not the marital status itself.
4. **Customers whose protected attributes are blank get far fewer contact actions** (17% for blank gender,
   0% for the 3,458 cases with a blank accessibility or newcomer flag, against about 79% for known groups).
   These are not a protected group: they are customers with thin data, and nearly all of them are cases
   where waiting, insolvency, cease or the hold-out applies. It is a data-coverage question for Track A,
   not a fairness gap, but it is worth knowing that missing data goes with no action.
5. **Sparse attributes** (`accessibility_type`, `vulnerability_type`, `customer_accent_region`) are only
   filled for a few percent of customers, so their groups are small and their ratios least reliable.
