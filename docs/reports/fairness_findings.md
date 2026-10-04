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
