# The problem, told properly

What the deck and the talk open with, before Kept is mentioned. Every Maple Bank number is from the release and links
to the report that computes it.

## Why collections matters

**For the bank.** An account that falls behind is a loss in waiting. The bank must hold provisions against it, pay
people to work it, and, if it keeps rolling, write it off. At Maple Bank, about **194,515 cases a year** enter
collections at 1–30 days past due, carrying **$63.9M** overdue. About half (**48.8%**) roll into a worse bucket within
30 days, and **rolling is the only road to a charge-off**: 2.5% of rolled cases end up written off, at **$12,523** on
average. A case that doesn't roll never charges off. ([business case](reports/business_case.pdf) §1)

**For the customer.** A missed payment means fees, interest, a mark on the credit file, and calls. A broken promise is
worse than none: the customer tried, failed, and is now marked as someone who breaks promises, which makes the next
conversation harder for both sides.

**For the regulator.** Canadian banks collect under rules that are about *how*, not just *whether*:

- **Provincial collection rules** (for example Ontario's Collection and Debt Settlement Services Act): calls only
  between 7 a.m. and 9 p.m. Monday to Saturday and 1–5 p.m. on Sunday, never on statutory holidays, and at most three
  contacts in seven days after the first conversation, unless the customer agrees to more.
- **The FCAC** expects banks to treat customers in financial difficulty fairly, appropriately and accessibly. Its 2023
  guideline on mortgages in exceptional circumstances asks for proactive outreach and relief options, and quarterly
  reporting on what was offered.
- **The National Do Not Call List** doesn't cover debt-collection calls (they aren't telemarketing), so the bank's own
  rules are the only thing standing between a customer and too many calls.

Maple Bank's own record against its rules: **5,328** contacts made outside calling hours and **290** contact-cap
breaches in the release (5,081 and 121 cases). Each is a complaint, or a regulator's question, waiting to happen.

## Jane

*A composite, not a real customer: every fact about her is typical of the release.*

Jane works shifts and is paid every second Friday. Her card is 12 days past due. On a Monday an agent reaches her, and
she agrees to pay $140, "as soon as I can". The agent books the promise for **Wednesday**, two days before her payday,
because the system offers the next few days. On Wednesday her account has $40 in it. The promise breaks.

Now Jane is "a customer who breaks promises". She gets more calls, at worse times. She has also mentioned twice, in
notes nobody reads again, that her shifts were cut in August. Nobody connects the two. Her card rolls to 31–60 days.

Jane isn't unusual. On the bank's own randomised cases, a promise due **0–2 days after payday** is kept **52.9%** of the
time and pays **59.8%** of the promised money; one due **8+ days after** (when the pay has already gone) is kept
**46.7%** of the time and pays **50.9%** ([evidence](reports/evidence.md) §2).

## The root causes, not the symptoms

| Root cause | Evidence from the bank's own data | Kept's layer that fixes it |
|---|---|---|
| **Wrong timing**: promises fall due before payday | +4.6 pts kept and **+6.1 pts of the promised money paid** when due 0–2 days after payday rather than 8+, within days-past-due bands on randomised cases ([evidence](reports/evidence.md) §2) | **Kept sizing**: the due date lands 1–2 days after payday, the amount within spare cash; the pay page asks the customer when the bank doesn't know |
| **Wrong person**: contact goes where payment was likely anyway | The bank's four randomised strategy cells can't be told apart on cure or roll rate; its "no contact" holdout was mostly contacted ([evidence](reports/evidence.md) §1) | **Uplift model**: contact whoever a contact *changes*. Estimated off-policy: 38.6–42.0% paid in 14 days, against 32.4–32.5% for the bank's strategy on the same decisions ([evidence](reports/evidence.md) §4) |
| **Hardship found late**: it sits in free text | Jane's "shifts cut" lives in notes and calls. Kept reads them, redacted first, with **recall 1.00** on held-out notes and calls, and from the recording itself ([extraction gate](reports/extraction_gate.md), [voice](reports/voice_wer.md)) | **Text layer**: a hardship signal with the exact quote turns the card protective, and a specialist reviews before anything is sent |
| **Fragmented identity**: five systems, no shared key | 3.84M source keys for **1,052,300** people; precision 99.3% by hand, recall 99% on planted duplicates ([quality report](../QUALITY_REPORT.pdf), [identity recall](reports/identity_recall.md)) | **Data product**: one golden record per person, so the agent sees the payday from the deposit account and the note from last week |

## Jane with Kept

Kept sees her payday in her deposit account (or, if the bank doesn't know it, asks her on the payment page). It
proposes **$70 on her payday, twice**, inside what she can spare. The note about her shifts flags
possible hardship with the exact words, so the card turns protective: a hardship specialist looks first, and a second
person releases. Every step is in a tamper-evident audit trail. Jane keeps the promise; her card doesn't roll.

## Sources

- Ontario collection rules (calling hours, contact limits): [Hoyes Michalos](https://www.hoyes.com/blog/what-can-a-collection-agency-do-to-me-top-collection-rules/), [Spergel](https://www.spergel.ca/?p=4990). Check the Act on e-Laws Ontario before quoting it as law.
- FCAC Guideline on Existing Consumer Mortgage Loans in Exceptional Circumstances (2023): [FCAC](https://www.canada.ca/en/financial-consumer-agency/news/2023/06/financial-consumer-agency-of-canada-guideline-on-existing-consumer-mortgage-loans-in-exceptional-circumstances.html), [supervisory highlight](https://www.canada.ca/en/financial-consumer-agency/programs/research/guideline-mortgage-loans.html).
- National Do Not Call List and debt collection: [DNCL consumer FAQ](https://lnnte-dncl.gc.ca/en/Consumer/FAQ), [CRTC](https://crtc.gc.ca/eng/phone/telemarketing/exempt.htm).
