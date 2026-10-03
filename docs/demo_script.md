# Demo video script (deliverable 6: up to 5 minutes, real data, unlisted link)

Driver: Satvik (screen and voice). Machine: Akshat's (`make serve` + `make web`, real data, Ollama running).
Target length 4:45. The guided demo page (`/demo`, arrow keys move between steps) follows this script
step for step, so the screen never needs a hunt for a page. Dry-run it twice before recording.

## Before recording (10 minutes)

- `kept nightly` has finished tonight; `make serve` (real services, not `--demo`) and `make web`; open
  `http://localhost:3000` in a clean browser window, 1080p, zoom so the card text is readable.
- `ollama list` shows the extraction model loaded (the first live note takes about 15 s cold; send one
  throwaway note on a different case first so the recording shows about 4 s).
- The flip case must still be in its "before" state: `CS-2026-820205` (push, Green) or the case the guided
  demo uses (`CS-2026-118204`). A note left from an earlier dry run changes the card: remove it first
  (Akshat removed his test note on 3 Oct: ask him how), or use the other case.
- Same `KEPT_HOLDOUT_SALT` in `.env` on this machine as the nightly used (today's open call).
- Close everything else: no notifications, no terminal with a token in view, no `.env` on screen.
- Sign-in personas are in the header; names on screen are masked by role, which is what we want in the video.

## Beats

| Time | Screen | Say |
|---|---|---|
| 0:00 to 0:20 | Landing page, slow scroll to the title | "Collections today is generic and often due before payday. Kept is a next best action for collections: it knows who the customer really is, what they said on their last call and when they get paid, it proposes the action most likely to help, sized to a promise they can keep, and a person releases every action." |
| 0:20 to 1:10 | `/demo` step 1, "One customer, one ID" (as compliance). Point at the convergence graphic, the golden ID, "Weakest match in the cluster" and the list of source keys | "Everything runs on the CIBC collections release: 31 tables, five product systems, no shared customer ID. 3.84 million source keys become 1.05 million golden customers. Exact keys first, then a probabilistic match on name, date of birth, phone and postal code. Here are one customer's keys from the different systems, and the weakest link in the match. We hold a cluster for review instead of guessing when it would carry two national IDs, and a steward can approve or cut a link. We checked 300 matched pairs by hand: 298 were right, 99.3%." |
| 1:10 to 1:50 | Step 2, "Ask in plain English" (as analyst). Show answer one with its SQL, then the refusal | "Ask is the second layer. A metric question, promise kept rate by product, is answered from certified SQL and the SQL is shown, not hidden. Now a protected attribute: kept rate by gender. It refuses, says why, and offers a safer question. On the benchmark it answers 83% of in-scope questions and refuses every question it should." Optional if time: type one unseen question the judges might ask. |
| 1:50 to 2:35 | Step 3, "The next best action" (as agent). Card: action, calling window, the three reasons, Kept sizing | "Now the agent opens Jane's case. Safety rules run first: hard stops, consent, calling hours, the seven-day contact cap. Then a model that estimates who actually changes behaviour if contacted, not who would have paid anyway. Then Kept sizing: due the day after payday, within spare cash. Three plain-English reasons, and nothing leaves this screen without a person releasing it." |
| 2:35 to 3:35 | Step 4, "A new note changes everything". Type the note, wait for extraction, show the evidence quote and the new Red card | "Here is the moment that matters. The customer says shifts were cut. The agent logs it. A local model, free and on our own machine, reads the note after it has been redacted, and returns hardship with the exact quote as evidence: no quote, no value. Gold has not been rebuilt; the card flips now. Hardship is possible, aggressive actions drop out, and the case goes Red: a hardship specialist reviews first." |
| 3:35 to 4:15 | Step 5, "Two people release it". Switch persona to the specialist, approve; switch to the team lead, approve | "Red needs two people. The specialist approves first, the team lead second, and the safety rules are checked again at release, so a stale card cannot be sent." |
| 4:15 to 4:40 | Step 6, audit trail | "Every step is on the record: the recommendation, the hardship change with its evidence, both approvals, and who did what when." |
| 4:40 to 4:55 | Back on the title or the architecture slide | "Real data, 96,000 open cases scored overnight, no protected attribute in any model, every text goes through redaction before any model sees it, and every action is human-released. That is Kept." |

Word count of the spoken text is about 520, which at a calm 130 words a minute is 4 minutes of speech and
leaves about 50 seconds for clicks and the live extraction wait. Do not add to it; cut the optional unseen
question first if the dry run runs over.

## The 40% Red question (to settle today; draft wording)

If a judge asks why so many cards are Red: Red means "a hardship specialist reviews before anything is
sent", and 32% of open cases already carry a confirmed hardship code from the agents in the source data
(19% more are possible). A protected customer gets a hardship review instead of a collection call, so the
share is the protection working, not the model being cautious. A rule for customers already on a plan
would cut it and is the next step. Shreyas and Akshat own the final line; update this paragraph when it is
agreed.

## Numbers used (all from the repo; re-check against the final run before recording)

| Claim | Source |
|---|---|
| 3,840,513 keys, 1,052,300 golden IDs, 31 tables | `kept match` summary, `docs/quality_report.md` |
| 298 of 300 reviewed pairs correct, 99.3% | `kept gate`, Q3-review-precision |
| 96,000 cards, Red 40% | `kept score` (`docs/tracks/Track_C.md`, Track_D.md) |
| Ask 83% accuracy, 100% refusal recall on the dev split | `docs/benchmark_scorecard.md`; replace with the final run after 19:00 |
| 785,594 notes and transcripts redacted, 0 leaks | `docs/deck_outline.md` slide 6 |
| No protected group treated materially differently | `docs/fairness_findings.md` |

## If something goes wrong on camera

- Live extraction is slow or fails: say "the model is warming up" and cut the take; do not narrate over an error. Record the flip as its own take and splice it in.
- Ask refuses a question it should answer: use the second example question from the Ask page's chips.
- Card does not flip: the note was probably already on the case; use the other case or remove the note and retake.
- Keep each step as a separate take (about 40 seconds each); the video is cut together, not done in one go.
