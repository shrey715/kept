# Track C: Text features + compute

Person: Akshat Srivastava · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 1
- Working on: `PresidioRedactor` (early provider for G0)
- Waiting on: `uv sync --all-extras` and the dataset download on the compute machine

## Done
- `evaluate.py`: `binary_metrics`, `text_feature_gate`, `cohens_kappa`, `adjudicate` (tests pending the install)

## Decisions and changes from the plan
- F1 is computed from counts (2tp / (2tp+fp+fn)) so the 0.80 boundary is exact, not float-rounded.

## Open questions
- Local extraction model (§1b, §9): `gemma3:12b-it-qat` (8.9 GB) is already on the machine and fits 16 GB VRAM; `gemma4:26b` (17 GB) does not fit fully. Proposing gemma3:12b at G0.

## Log
- 13:55 Dataset download restarted with HF login; draft PR opened.
- 13:27 Branch `track-c` created; GPU (RTX 5070 Ti, 16 GB) visible; started `uv sync --all-extras` and dataset download.
