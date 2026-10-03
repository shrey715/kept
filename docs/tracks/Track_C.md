# Track C: Text features + compute

Person: Akshat Srivastava · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 1 (parallel tasks done)
- Working on: G0 contract PR (`docs/NEXT_STEPS.md` §3), then Phase 2
- Waiting on: owners' reviews of the G0 PR; B's hosted Ask model choice

## Done
- `PresidioRedactor` (early provider): EN + FR spaCy, Canadian SIN/postal, non-Luhn cards, phones, context-gated bank accounts and DOBs, jargon allow-list, idempotent. `tests/text/test_redact.py` 16 pass.
- `evaluate.py`: `binary_metrics`, `text_feature_gate`, `cohens_kappa`, `adjudicate`. Eval tests pass.
- Public labels (500 notes, 500 transcripts) in `data/labels/`; mapping + 30% holdout in `kept/text/labels.py`. `tests/text/test_labels.py` pass.
- `text.extractions` shape draft (S4): `dbt/models/text/sources.yml`.
- Compute machine: torch 2.14.1+cu130, CUDA on the RTX 5070 Ti; SetFit smoke run on GPU (1.5 s); LiteLLM -> `ollama/gemma3:12b-it-qat` works (~1 s warm, 28 s cold).
- `make test-contract` green, `make lint` clean, track_c: 25 passed, rest stubbed for later phases.

## Decisions and changes from the plan
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
- Extraction confirm panel: D builds it in `web/`, C builds the route (`docs/NEXT_STEPS.md` §4).
- A: 4,636 agent notes have mojibake (`appel�`, `F�VR.`), mostly French. Data quality report item; worth fixing in silver before redaction/extraction.
- Team: shared handover folder (§1a) for Parquet outputs; needs a Drive folder link.
- Rare labels: cease_request has 4 (notes) / 5 (transcripts) positives and third_party_present 9 / 8 in the public 500. The F1 gate on those is very noisy; discuss at G0.

## Log
- 15:30 Merged all PRs (#2–#6) into main: fixed B's CI (sqlglot importorskip), resolved D's `cli.py` conflict, pinned dbt-duckdb<1.10. Wrote `docs/NEXT_STEPS.md` for all tracks.
- 14:55 Phase 1 parallel tasks done; checks green. Waiting for G0.
- 14:45 SetFit GPU smoke run and Ollama call OK. setfit bumped.
- 14:35 PyPI throttled (~90 KB/s/conn): fetched torch/cuDNN with aria2c, verified hashes, installed.
- 14:25 Voice pack unzipped (2,000 WAVs) into `data/raw/files/voice`. Noted D's Next.js UI switch.
- 14:15 Release unzipped and linked into `data/`; labels profiled and mapped.
- 13:55 Dataset download restarted with HF login; draft PR opened.
- 13:27 Branch `track-c` created; GPU visible; started install and dataset download.
