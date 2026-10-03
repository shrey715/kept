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
- S4 adds `<field>_char_start` / `<field>_char_end` so Evidence round-trips exactly. A + D: review at G0.
- Release hardship reasons are finer than `StatedReason`: illness/disability -> medical, ei_waiting -> job_loss, rate_reset/separation/disaster_evacuation -> other (`kept/text/labels.py` REASON_MAP). Adding enum members would be an additive contract change if the team wants it.
- 30% of public labels held out from prompt tuning by a stable id hash.
- Release copied into `data/` as hard links: `raw/` = release `data/*` + `files/`, `labels/`, `benchmark/`, `policy/` = `files/docs`. A owns the official layout (K3).
- F1 is computed from counts (2tp / (2tp+fp+fn)) so the 0.80 boundary is exact, not float-rounded.

## Open questions
- Local extraction model (§1b, §9): `gemma3:12b-it-qat` (8.9 GB) is already on the machine and fits 16 GB VRAM; `gemma4:26b` (17 GB) does not fit fully. Proposing gemma3:12b at G0.

## Log
- 14:15 Release unzipped and linked into `data/`; labels profiled and mapped.
- 13:55 Dataset download restarted with HF login; draft PR opened.
- 13:27 Branch `track-c` created; GPU (RTX 5070 Ti, 16 GB) visible; started `uv sync --all-extras` and dataset download.
