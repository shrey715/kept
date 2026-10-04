# Data quality report

Contract: `kept-c360-customer` v1.0.0. Written 2026-10-03 23:56 UTC from the warehouse by `scripts/quality_report.py`: the record counts are queried; the few match-quality figures in the handling column (79% to 98%, 5,498 held clusters) are from Track A's checks, recorded in `docs/tracks/Track_A.md`.

## 1. The gate on the golden record

The five contract rules (Q1-Q5), plus the hardship-text and review-precision checks, run on the real gold table by `kept gate`:

Gate: **PASS**

| Rule | Status | Detail |
|---|---|---|
| Q1-unique-ids | PASS | 1,052,300 golden IDs unique; every active source key maps to one |
| Q2-linkage | PASS | 98.66% of account keys linked; every open case resolves |
| Q3-match-safety | PASS | every auto link scores >= 0.95; no cluster holds two national IDs |
| Q3-review-precision | PASS | precision 99.3% on 300 reviewed predicted links; 300 of 300 pairs reviewed |
| Q4-contact-safety | PASS | 0 violations |
| Q5-freshness | PASS | published 0.1h after the source extract |
| Q5-row-count | PASS | 1,052,300 rows, +0.0% vs the last load |
| hardship-text | PASS | 785,594 extractions; 11,464 golden IDs rest on them |

## 2. Issues found in the source data

| Issue | Where | Records affected | How we handled it |
|---|---|---|---|
| Agent notes with lost characters (U+FFFD) | `agent_notes.note_text` | 4,636 (0.61% of 760,594) | Not recoverable: the original characters are gone. Left as is; the redactor and extractor read the surrounding words, which are intact. |
| CRM records deleted upstream (CDC) but still in the extract | `customers.is_deleted` | 2,115 (0.21% of 1,020,000) | Left out of silver (the current version is deleted); listed in quarantine.customers. |
| A customer with two CRM records | `customers (crm_customer_id)` | 20,434 (2.01% of 1,017,885) | Linked by the same national ID, CRM's own duplicate pointer, or Splink (name, DOB, phone, postal code); one golden ID each. The count is CRM records beyond the first of each golden ID. |
| Card phone numbers masked in the source (519555xxx42) | `card_accounts.cardholder_phone_raw` | 384,422 (58.25% of 660,000) | Cannot be normalised to a phone number: left null in the cleaned column and listed in quarantine.card_accounts. Cards link on name, DOB and postal code instead. |
| CRM phone numbers cut to 9 digits | `customers.primary_phone_raw` | 4,936 (0.48% of 1,020,000) | Not a valid number: left null in the cleaned column, listed in quarantine.customers. |
| CRM date of birth keyed as DD/MM or MM/DD (cannot be told apart) | `customers.dob_raw` | 128,980 (12.71% of 1,014,974) | Never guessed (reading every slash date day-first misreads 16% of them). CRM also holds a clean date_of_birth, which is used; the raw value only fills gaps when it is unambiguous. Cards, whose format is fixed DD-MM-YYYY, are read day-first. |
| month_end_date in three formats (ISO, DD/MM/YYYY, YYYYMMDD) | `account_monthly_snapshot.month_end_date` | 1,255,152 (9.99% of 12,569,692) | A plain date cast silently dropped these (1.25M values). Silver reads all three; a month-end day is always above 12, so the DD/MM form is unambiguous. |
| Province written as Ont., B.C., Alta., PQ, Quebec ... | `customers.province_code` | 10,689 (1.05% of 1,017,993) | Mapped to the two-letter code (normalize_province); gold would otherwise break the contract. |
| A ratio too large for its declared type | `deposit_accounts.income_to_debt_service_ratio_est` | 13,969 (2.94% of 474,866) | The data dictionary says decimal(8,4); values go above 9999.9999. Silver uses a wider decimal. The magnitudes look like a unit problem upstream: not used by any feature. |
| contact_history.channel renamed to channel_v2 on 26 Sep | `contact_history.channel, channel_v2` | 31,428 (1.17% of 2,688,337) | Silver coalesces the two into channel (the dictionary name). |
| Loan borrower names in two orders (First Last / Last First) | `loan_accounts.borrower_name_raw` | 82,028 (20.28% of 404,500) | The token CRM uses more as a surname is the surname (silver.int_name_lexicon). Without it, loan names matched other systems 79% of the time; with it, 98%. |
| Autopay / pre-authorised-debit account at another bank (not one of our deposit accounts) | `card_accounts.autopay_source_account, loan_accounts.pad_source_account` | 302,549 (64.70% of 467,602) | Ignored for linking: there is nothing at our bank to link to. Left untouched in silver. |
| National Do Not Call flag set | `customers.national_dncl_flag` | 355,697 (34.94% of 1,017,885) | Never blocks collections contact (the list covers telemarketing, not collections). Internal do-not-call and cease flags do. |
| Delinquency buckets finer than the contract's top bucket (121-150, 151-180, 180+) | `collections_cases.current_bucket` | 14,409 (3.92% of 367,229) | Silver keeps the source label. Gold derives its bucket from days past due, with one 121+ bucket (the shared contract). |
| Card cycles_delinquent far from days past due (cycles are not days) | `card_accounts.cycles_delinquent, dpd` | 673 (1.41% of 47,872) | Gold and features use dpd, never cycles_delinquent. |
| Contact rows whose case is not in collections_cases (orphans; the example contract allows < 1%) | `contact_history.case_id` | 26,864 (1.00% of 2,688,337) | Counted and kept in silver; nothing joins them to a case. |
| Duplicate primary keys in the source tables | `customers, contact_history, promises_to_pay, agent_notes` | 0 (0.00% of 4,707,746) | None found when this report was written (the count above is the proof). |
| Transactions cover a customer sample and 13 months only | `transactions` | 106,914 (13.71% of 780,000) | Missing stays missing: features from transactions are null, not 0, outside the sample. |
| Keys that no rule or model could link (singletons, or held apart) | `gold.c360_customer` | 64,092 (6.09% of 1,052,300) | Each keeps its own golden ID with status 'unlinked'. 5,498 clusters were held (two national IDs, or more than 12 keys) and go to the steward queue. |

## 3. What the cleaning rules are

Every rule is a tested function in `kept.data.clean` / `kept.data.traps` (names, dates, phones, postal codes, provinces, snapshots, SCD2, schema drift). Values a rule cannot read are never guessed: they are left null in the cleaned column and listed in `quarantine.<table>` with the reason.

## 4. What we do not know

- **Matching precision against ground truth.** The organisers gave no ground-truth IDs. We report instead: Splink re-finds 99.9% of the exact links; no auto-linked cluster holds two national IDs; a steward reviews a random sample of 300 predicted links (target 98%).
- **Notes and transcripts** are read by a model trained on the public labels; its accuracy is Track C's F1 gate, not measured here.
