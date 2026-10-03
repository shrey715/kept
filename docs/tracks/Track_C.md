# Track C: Text features + compute

Person: Akshat Srivastava · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: G2 integrated on C's machine (all four G2 PRs merged, rebuild on real data done)
- Working on: D's follow-ups (decisions pending with Akshat)
- Waiting on: G2 sign-off; D's account/deposit features (0% filled online)

## Done
- **G2 integration (3 Oct, C's machine):** merged #25 (6fac669) → #24 (9791576) → #28 (e6389db) → #27 (4220553); #26 left for G3. #25 went before #24 because #24 refs our `cashflow_observations`. No conflicts (cli.py auto-merged with every handler; `text:` keeps D's UTC pre-hook). Rebuild: gold 1,052,300 rows (40/40), `kept gate` PASS incl. hardship-text (11,464 golden IDs rest on text), `scripts/g2_hardship_check.py` 3/3 PASS, `text_signals.written_at` = `note_ts_utc` for all 760,594 notes (0 mismatches in UTC), features 96,000 cases in Feast, training rows 323,560, `kept train` Qini call 0.077 / sms 0.051 / email 0.051 / push 0.018 (all > 0 vs WAIT). Feast: real case → FeatureVector, unknown id → KeyError. Tests: 1,109 passed, 10 failed = A's parity (7) and steward (3) stubs.
- **Backfill (Phase 3, G2 input):** SetFit (`setfit-v1`, bge-small) trained on 1,604 LLM labels (601 none / 893 possible / 110 clear; 2 power cuts stopped labelling at 1,619 of 1,999). **Hardship gate on held-out public labels passed here: notes F1 0.869 / recall 0.977, transcripts F1 0.988 / recall 0.988.** `text.extractions`: 785,594 rows (760,594 notes + 25,000 calls), 154,007 with hardship, 0 duplicate ids, the 50 LLM rows kept; `text.text_signals` rebuilt. Hand-over file: `data/exports/extractions/extractions_880b98c_20261003.parquet` (9.4 MB). Model: `data/models/setfit/setfit-v1_880b98c/`.
- Phase 4: `/extractions/{source_id}/confirm` (#20), `kept extract` (#22), `eligible_programs`; demo frontend installed and smoke-tested on this machine (pnpm 11.23.0, `kept serve --demo` + `pnpm dev`).
- Deliverables drafted: `docs/architecture.{dot,png,pdf}`, `docs/deck_outline.md`.
- G1 (C): full Splink run → crosswalk v1: 3,840,513 keys → 1,052,300 golden IDs, largest cluster 12, held 5,491 (~0.5%, above A's ~0.3% estimate). `data/exports/identity_crosswalk/*_4ac9c37-20261003-full-train5.*`. PR #14 (A's files, with Akshat's OK): DuckDB memory cap + spill, train on 1/5 DOB sample and score all, lean prediction pull, pair ordering in SQL, lean clustering objects. Three earlier attempts were OOM-killed.
- Phase 3 code (subagent, PR #15): `combine`, cash-flow rule, `SetFitBackfill`; hardship 41 + backfill 3 tests pass.
- G1 (C): extraction on 50 real non-label notes through `PresidioRedactor` + `LiteLLMGateway` (local gemma3:12b) into `text.extractions`: 50/50 stored, ~4 s/note; audit log has 50 LLM events with metadata only, no raw note text.
- Heavy run: all notes + transcripts redacted (redactor v5): 785,594 rows = 760,594 notes + 25,000 transcripts, 411 s on 4 processes; leak scan over every row finds 0 cards, phones, emails, SINs, postal codes, DOBs. `data/exports/redacted_notes/redacted_notes_eb00686_20261003.parquet`.
- Prompt v4 on the notes tuning split: 6/7 features pass (hardship 0.86 r 1.00, promise 0.90, date 0.84, amount 0.96, dispute 0.80, third party 1.00); cease 0.60 (3 positives).
- Warehouse on this machine: `kept land` (31 bronze tables, 2 min), silver (`dbt build --select silver`, 38 pass, 4 min).
- G0 contract PR #10 merged (text schema, `ExtractionStore` + `for_case`, `Services` fields, `hard_stop_flags`, free LLM settings, §9 statuses).
- Phase 2: `extract.py` (`resolve_day_of_month`, `locate_quote`, `LLMExtractor`, `confirm`, `transcript_text`): all extract/eval tests pass. `DuckDBExtractionStore` (`kept/text/store.py`) round-trips (`tests/text/test_store.py`).
- Eval harness `scripts/eval_extraction.py`; batch redaction `scripts/redact_all.py` (256K distinct notes, ~255 notes/s/process).
- Prompt v2 on the notes tuning split (~350): hardship 0.85 (recall 1.0), promise 0.93, amount 0.97, third party 0.88 pass; date 0.70, dispute 0.39, cease 0.60 fail. v3 fixes in progress.
- `PresidioRedactor` (early provider): EN + FR spaCy, Canadian SIN/postal, non-Luhn cards, phones, context-gated bank accounts and DOBs, jargon allow-list, idempotent. `tests/text/test_redact.py` 16 pass.
- `evaluate.py`: `binary_metrics`, `text_feature_gate`, `cohens_kappa`, `adjudicate`. Eval tests pass.
- Public labels (500 notes, 500 transcripts) in `data/labels/`; mapping + 30% holdout in `kept/text/labels.py`. `tests/text/test_labels.py` pass.
- `text.extractions` shape draft (S4): `dbt/models/text/sources.yml`.
- Compute machine: torch 2.14.1+cu130, CUDA on the RTX 5070 Ti; SetFit smoke run on GPU (1.5 s); LiteLLM -> `ollama/gemma3:12b-it-qat` works (~1 s warm, 28 s cold).
- `make test-contract` green, `make lint` clean, track_c: 25 passed, rest stubbed for later phases.

## Decisions and changes from the plan
- Backfilled extractions all carry `extracted_at` = the backfill run time (3 Oct), not the note's time; point-in-time readers must use `text_signals.written_at` (the note's own time).
- Cash-flow hardship enters gold at **G2** (Akshat, 3 Oct): `hardship.cashflow_observations` (C, PR #25) is one more branch of A's `int_hardship_observations` (PR #24). Merge order at G2: #25 first, then #24.
- Promised amounts are scored within $1: notes write whole dollars ("$21") while labels hold the promise record's cents (21.03). Gold dates for "next payday" come from payroll data, not the text, so they stay misses.
- The LLM returns dates as written (`MM-DD`, `day:N`, `weekday:x`, ISO); code resolves them against the note's local date. A month-day value whose quote names no month is read as a day of month.
- Redactor v3 keeps a spaCy PERSON/LOCATION span only if it has a Titlecase non-month word: notes' typos, months and ALL-CAPS phrases were being redacted. Limit: an ALL-CAPS name passes (notes have almost none; transcripts use Titlecase).
- Track D moved the UI (S7) from one static HTML page to Next.js + Tailwind in `web/` (D's call, 3 Oct). What it means for C: the demo runs on this machine (Phase 6), so it needs Node + pnpm and `kept serve` runs two processes (FastAPI + Next). Node 22.22.2 and npm 10.9.7 are here; pnpm is not. When `web/` lands on main: install pnpm, `pnpm install` in `web/` (~350 MB), and run the full demo here once before G4. C's `/extractions/{source_id}/confirm` stays a FastAPI route; the Next page calls it.
- Redactor also loads `fr_core_news_lg` (Akshat chose lg over md): 14% of notes are French and the English NER redacted French words as names. French is picked per note by a word-list heuristic (`looks_french`), so the `Redactor` interface is unchanged. Anyone running the redactor needs both spaCy models; both are on Hugging Face (`spacy/en_core_web_lg`, `spacy/fr_core_news_lg`), which is much faster than GitHub here.
- Custom CREDIT_CARD pattern without Luhn: 3,822 notes carry synthetic 16-digit cards that fail Luhn and leaked through Presidio's built-in recognizer.
- `setfit>=1.1` in the `text` extra (uv.lock: setfit 1.0.3 -> 1.2.0, datasets 2.14.4 -> 5.0.1): datasets 2.14 crashes on pyarrow 25. Only the `text` extra changes.
- S4 adds `<field>_char_start` / `<field>_char_end` so Evidence round-trips exactly. A + D: review at G0.
- Release hardship reasons are finer than `StatedReason`: illness/disability -> medical, ei_waiting -> job_loss, rate_reset/separation/disaster_evacuation -> other (`kept/text/labels.py` REASON_MAP).
- 30% of public labels held out from prompt tuning by a stable id hash.
- Release copied into `data/` as hard links: `raw/` = release `data/*` + `files/` (incl. voice), `labels/`, `benchmark/`, `policy/` = `files/docs`. A owns the official layout (K3).
- Proposed local extraction model for G0: `ollama/gemma3:12b-it-qat` (already on the machine, ~10.6 GB VRAM).

## Open questions
- (D) SetFit fills only `hardship_signal`; for history `promise_intent`, `dispute`, `cease_request`, `third_party_present` are written as nothing-found (False, confidence 0), so the features read "false" instead of "unknown". Proposal: `text_signals` emits NULL for those four on `setfit:` rows (one SQL change in our model). Awaiting Akshat.
- (D) Hardship load: a SetFit threshold doesn't help (probabilities saturate: notes flagged 36.9% at t=0.5 vs 35.6% at 0.95; held-out precision 0.78→0.81, recall 0.977 either way). Open cases with a text hardship note in 90 days: 41% (39,398); ≥1 in 30 d **and** ≥2 in 90 d: 19% (18,301). Gold status of open cases is 32% CONFIRMED (agent-coded source data), 19% POSSIBLE, so most Red reviews come from confirmed hardship, not text. Proposal: text-only POSSIBLE needs recent + repeated mentions (D's rule/feature). Awaiting Akshat.
- (D) Online features: account/deposit features (max_dpd, days_in_bucket, balance_at_risk, payroll, spare cash, trends) are 0% filled for 500 random open cases; promise_* 0%.
- Extraction confirm panel: D builds it in `web/`, C builds the route (`docs/NEXT_STEPS.md` §4).
- A: 4,636 agent notes have mojibake (`appel�`, `F�VR.`), mostly French. Data quality report item; worth fixing in silver before redaction/extraction.
- Team: shared handover folder (§1a) for Parquet outputs; needs a Drive folder link.
- Rare labels: cease_request has 4 (notes) / 5 (transcripts) positives and third_party_present 9 / 8 in the public 500. The F1 gate on those is very noisy; discuss at G0.

## Log
- 21:45 G2 integration done on C's machine: 4 PRs merged, rebuild green, report to Akshat.
- 20:55 Cash-flow observations built (20,380 golden customers, matches the Python rule); moved into G2 with A's #24.
- 20:30 Backfill done and verified; gate passed on this machine. Two power cuts (19:1x, 20:0x): labels file intact both times; git objects repaired after the first.
- 17:50 Crosswalk v1 done (attempt 4). Phase 3 code PR #15.
- 17:34, 17:38, 17:43 Splink full run OOM-killed (16 GB, 23 GB, 20 GB cap) — fixed step by step.
- 17:30 PR #11 merged. G1: 50-note real extraction OK, redaction run clean, silver built here, full Splink running.
- 16:30 G0 merged. Phase 2: extractor, store, eval harness, prompt v2/v3, redactor v3.
- 15:30 Merged all PRs (#2–#6) into main: fixed B's CI (sqlglot importorskip), resolved D's `cli.py` conflict, pinned dbt-duckdb<1.10. Wrote `docs/NEXT_STEPS.md` for all tracks.
- 14:55 Phase 1 parallel tasks done; checks green. Waiting for G0.
- 14:45 SetFit GPU smoke run and Ollama call OK. setfit bumped.
- 14:35 PyPI throttled (~90 KB/s/conn): fetched torch/cuDNN with aria2c, verified hashes, installed.
- 14:25 Voice pack unzipped (2,000 WAVs) into `data/raw/files/voice`. Noted D's Next.js UI switch.
- 14:15 Release unzipped and linked into `data/`; labels profiled and mapped.
- 13:55 Dataset download restarted with HF login; draft PR opened.
- 13:27 Branch `track-c` created; GPU visible; started install and dataset download.
