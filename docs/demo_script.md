# Demo video script (deliverable 6: up to 5 minutes, real data, unlisted link)

Target length **4:45** (hard limit 5:00 including any title card). Driver: Satvik (screen and voice).
Machine: Akshat's (`make serve` real mode + `make web`, Ollama running, tonight's `kept nightly` finished).
The brief asks to "show your system working on real data from the dataset", so the whole recording is on real
data: the guided demo page (`/demo`) switches to the real case `CS-2026-820205` by itself when the API is not
in `--demo` mode. Never record in `--demo` mode.

## How this script is built to score

The judges score five things (Build Phase instructions): technical quality and a working demo 30%, business
understanding 20%, presentation and storytelling 20%, innovative ideas 15%, team work 15%. They also check four
rules: a plain-English reason for every decision, a human can review anything that affects a customer, no
protected attributes, hardship flagged. Every beat below says which of these it proves, and the rule is shown on
screen, not only said.

One story, told once: *an agent opens a case, Kept knows who the customer really is, what they said on their
last call and when they get paid, proposes the action most likely to help, sized to a promise they can keep,
a person releases it, and everything is logged.*

| Beat | Time | Proves |
|---|---|---|
| 1 Hook and problem | 0:00 to 0:25 | business (20%), story (20%) |
| 2 One customer, one ID | 0:25 to 1:05 | technical (30%) |
| 3 Ask, with a refusal | 1:05 to 1:40 | technical, rule: no protected attributes |
| 4 The next best action | 1:40 to 2:20 | technical, innovation (15%), rule: plain-English reasons |
| 5 A new note changes everything | 2:20 to 3:15 | the demo moment: technical, innovation, rule: hardship flagged |
| 6 Two people release it, on the record | 3:15 to 3:50 | rule: a human reviews, audit |
| 7 Does it work, is it fair, what is it worth | 3:50 to 4:25 | business (20%), technical |
| 8 Close and team | 4:25 to 4:45 | team work (15%), story |

## The script

Spoken text is in quotes (about 600 words, 4:45 at a calm 135 words a minute with the clicks and one short
wait for the live note). **Screen** says what is visible; **Do** says what to click.

### 1. Hook and problem, 0:00 to 0:25
**Screen:** landing page, slow scroll to the title and tagline. A caption: "Kept: promises customers can keep".
"A customer falls a few days behind. Today they get a generic call at a time that suits the bank, for an amount
they can't pay, a week before their pay arrives. That is how a small delay becomes a roll into a worse bucket.
Kept is a next best action for collections that dates the promise to payday, sizes it to what they can
afford, puts safety rules first, and lets a person release every action."

### 2. One customer, one ID, 0:25 to 1:05
**Do:** open `/demo`, sign in as compliance (the guide does this), step 1.
**Screen:** the convergence graphic, then the golden ID, "Weakest match in the cluster", the list of source keys.
Caption (lower third, appears at the numbers): "3,840,513 source keys → 1,052,300 customers · 298 of 300 reviewed links correct".
"This is the CIBC collections release: 31 tables, five product systems, and no shared customer ID. We resolve
3.84 million source keys into 1.05 million real customers: exact keys first, then a probabilistic match on name,
date of birth, phone and postal code. Here is one customer's records from different systems, joined, with the
weakest link in the match shown. A cluster that would hold two national IDs is held for a steward instead of
guessed. We checked 300 links by hand: 298 were right, 99.3 percent."

### 3. Ask, with a refusal, 1:05 to 1:40
**Do:** step 2. Both questions load by themselves. Open the SQL or sources on the first answer (one click).
Then press the suggestion button on the refusal.
**Screen:** the answer with its cited numbers and SQL, then the amber "Refused" box and its suggestion.
"Ask is the second layer. A metric question, promise kept rate by product, is answered from certified SQL, and
every number in the answer has to be in the result rows, so the SQL and sources are on screen. Now a protected
attribute: kept rate by gender. It refuses, explains why, and offers a question it can answer. On the
development benchmark it answers 94 percent correctly and refuses every question it should."
(Replace 94 with the final number if Abhishek's 19:00 run changes the claim; say "development benchmark" only
if the test-split score is not yet in the README. Do not say a number the README does not show.)

### 4. The next best action, 1:40 to 2:20
**Do:** step 3, as the agent. Hover one reason.
**Screen:** the card: action, calling window, three reasons, the Kept sizing (due date, amount), the release tier.
"Now the agent opens the case. Safety rules run first, with no AI: hard stops, consent, the customer's own
calling hours, the seven-day contact cap. Then a model estimates who actually changes behaviour if contacted,
not who would have paid anyway. Then Kept sizing: due the day after payday, within spare cash. And three
plain-English reasons for the action. Nothing is sent until a person releases it."

### 5. A new note changes everything, 2:20 to 3:15
**Do:** step 4. The note box is pre-filled ("Customer says shifts were cut at the plant since August..."). Click
add. While it runs (about 4 s warm), keep talking. When the card changes, hover the evidence quote.
**Screen:** the card before, the note, the evidence quote highlighted, the card after: Red, "hardship review".
Caption: "No quote, no value".
"Here is the moment that matters. The customer says shifts were cut. The agent logs it. The note is
redacted first, then a local model, free and running on our own machine, extracts hardship, and it must give the
exact words as evidence: no quote, no value. We didn't rebuild anything. The card changes now: hardship is
possible, aggressive actions drop out, and the case turns Red, meaning a hardship specialist reviews before
anything else happens."

### 6. Two people release it, on the record, 3:15 to 3:50
**Do:** step 5: approve as the hardship specialist, then as the team lead. Step 6: the audit trail.
**Screen:** the two approvals, then the audit timeline with the recommendation, hardship change and both approvals.
"Red needs two people. The specialist approves first, the team lead second, and every safety rule is checked
again at release, so a stale card can't go out. And everything is on the record: the recommendation, the
hardship change with its evidence, both approvals, who and when."

### 7. Does it work, is it fair, what is it worth, 3:50 to 4:25
**Do:** cut to deck slide 9 (or the README results table), then the business case front page.
**Screen:** Qini and fairness bars, then the headline numbers of the business case.
"On the bank's own history, promises dated right after payday get 62 percent of the promised money paid against
52 percent. Our uplift model beats the bank's current strategy on calls. All 96,000 open cases are scored
overnight in about seven minutes, with a card for each. Every protected group gets contact actions at 0.86 to
1.00 of the others, and protected attributes are never model inputs: CI checks that. Projected, the base case is
2.2 million dollars a year, pays back in about two months, and a permanent five percent holdout will measure it."

### 8. Close and team, 4:25 to 4:45
**Screen:** the architecture diagram or deck slide 10 with the four track names.
"Real data, safety rules before any model, text redacted before any AI, and a human on every action. Kept was
built by four people on four tracks: data and identity, the Ask, text and extraction, and the decision engine,
with over 330 commits and gated integration. Promises customers can keep."

## Before recording (10 minutes, on Akshat's machine)

- Pull main, `make serve` (real) and `make web`; open `http://localhost:3000/demo`; browser 1080p, one clean
  window, zoom so card text is readable, notifications off, no terminal or `.env` visible.
- `ollama list` shows the extraction model; send a throwaway note on a different case first so the live note takes about 4 s,
  not 15 s cold. Same `KEPT_HOLDOUT_SALT` as tonight's nightly.
- `CS-2026-820205` must be in its "before" state (push, Green). A leftover note changes the card: remove it first
  (Akshat did this on 3 Oct, ask him how) before the take.
- Ask has a free-tier rate limit: ask the two demo questions once beforehand to warm the cache, and don't record
  while Abhishek's 19:00 benchmark is running.
- Names on screen are masked by role; keep it that way.

## Recording and editing

- Dry-run the whole thing twice with a stopwatch. Over 4:50 means cut: first the "development benchmark" sentence in
  beat 3, then half of beat 7. Never speed up the voice.
- Record each beat as its own take (about 40 seconds each), screen at 1080p, voice recorded with a headset
  mic in a quiet room, no music under speech. Cut the takes together; keep cuts hard and clean.
- Burn in short captions (the numbers and "No quote, no value") and subtitles for the whole voice: judges may
  watch muted.
- Upload as **unlisted** (YouTube or Drive), open the link in a private window to check it plays with sound,
  and check the length is under 5:00. Put the link in the form.
- Do not show customer text from the dataset beyond the demo note and the masked card; no real-looking
  personal data fills the screen.

## The 40% Red question (to settle today; draft wording)

If asked why so many cards are Red: Red means "a hardship specialist reviews before anything is sent". 32% of
open cases already carry a confirmed hardship code from agents in the source data and 19% more are possible. A
protected customer gets a hardship review instead of a collection call, so the share is the protection working,
not the model being cautious. A rule for customers already on a plan would cut it and is the next step.
Shreyas and Akshat own the final line; put it into the deck and this paragraph once agreed.

## Numbers used (all from the repo; re-check before recording)

| Claim | Source |
|---|---|
| 31 tables, 3,840,513 keys, 1,052,300 golden IDs, 298 of 300 reviewed links correct (99.3%) | README Results, `kept gate` Q3-review-precision |
| Ask 94% accuracy on the dev split, refusal recall 100% | README Results; update after the 19:00 run |
| 785,594 notes and calls redacted, 0 leaks | README Results |
| 96,000 cards a night, about 7 minutes; card loads in 0.21 s | README Results |
| Promises dated to payday 62% vs 52% of the money paid; base case $2.2M a year ($1.0M to $4.2M), about 2 months to pay back | `docs/reports/business_case.pdf` (a projection, say so) |
| Fairness ratios 0.86 to 1.00 across protected groups | `docs/reports/fairness_report.pdf` |
| 330+ commits from all four of us | `git shortlog -sn` on main |

## If something goes wrong on camera

- Live extraction slow or fails: say nothing over the error, cut the take, retake beat 5 alone.
- Ask refuses a question it should answer: use another chip from the Ask page.
- The card does not flip: the note was already on the case; remove it and retake.
- A step shows an error: refresh `/demo` (it reloads each step's data) and retake that beat only.
