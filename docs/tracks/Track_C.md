# Track C: Text features + compute

Person: Akshat Srivastava · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 1
- Working on: `PresidioRedactor` (early provider for G0)
- Waiting on: `uv sync --all-extras` (torch) to run tests; voice zip still downloading

## Done
- `text.extractions` shape draft (S4): `dbt/models/text/sources.yml`, for review at G0
- Public labels loaded into `data/labels/`; mapping in `kept/text/labels.py` (tests pending the install)
- `evaluate.py`: `binary_metrics`, `text_feature_gate`, `cohens_kappa`, `adjudicate` (tests pending the install)

## Decisions and changes from the plan
- Track D moved the UI (S7) from one static HTML page to Next.js + Tailwind in `web/` (D's call, 3 Oct). What it means for C: the demo runs on this machine (Phase 6), so it needs Node + pnpm and `kept serve` runs two processes (FastAPI + Next). Node 22.22.2 and npm 10.9.7 are here; pnpm is not. When `web/` lands on main: install pnpm, `pnpm install` in `web/` (~350 MB), and run the full demo here once before G4. C's `/extractions/{source_id}/confirm` stays a FastAPI route; the Next page calls it.
- S4 adds `<field>_char_start` / `<field>_char_end` so Evidence round-trips exactly. A + D: review at G0.
- Release hardship reasons are finer than `StatedReason`: illness/disability -> medical, ei_waiting -> job_loss, rate_reset/separation/disaster_evacuation -> other (`kept/text/labels.py` REASON_MAP). Adding enum members would be an additive contract change if the team wants it.
- 30% of public labels held out from prompt tuning by a stable id hash.
- Release copied into `data/` as hard links: `raw/` = release `data/*` + `files/`, `labels/`, `benchmark/`, `policy/` = `files/docs`. A owns the official layout (K3).
- F1 is computed from counts (2tp / (2tp+fp+fn)) so the 0.80 boundary is exact, not float-rounded.

## Open questions
- D: does the Next.js card page include the extraction confirm/edit panel for `/extractions/{source_id}/confirm` (Phase 4), or does C build that component in `web/`? Plan §5 Phase 4 lists only C's API handler.
- Local extraction model (§1b, §9): `gemma3:12b-it-qat` (8.9 GB) is already on the machine and fits 16 GB VRAM; `gemma4:26b` (17 GB) does not fit fully. Proposing gemma3:12b at G0.

## Log
- 14:25 Voice pack unzipped (2,000 WAVs) into `data/raw/files/voice`. Restarted stalled `uv sync`. Noted D's Next.js UI switch.
- 14:15 Release unzipped and linked into `data/`; labels profiled and mapped.
- 13:55 Dataset download restarted with HF login; draft PR opened.
- 13:27 Branch `track-c` created; GPU (RTX 5070 Ti, 16 GB) visible; started `uv sync --all-extras` and dataset download.
