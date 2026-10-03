# Track A: Data and IDs

Person: Satvik Rao · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 1
- Working on: nothing, Phase 1 parallel tasks are done
- Waiting on: gate G0 (all four tracks' Phase 1)

## Done
<!-- One line per finished task: what, which tests pass, PR/commit. -->
- Contract loader (`load_data_contract`, `table_columns`, `columns_with`, `ask_blocked_columns`): `tests/contracts` + contract tests in `tests/data/test_contract_and_ingest.py` pass. Not committed yet.
- `connect`, `land_file`, `land_directory` and `kept land`: ingest tests pass; real run landed 31 bronze tables in 4 min, row counts equal the release README, `dbt/models/bronze/sources.yml` lists the same 31 names.
- Raw layout written in `data/README.md` (K3); release copied into `data/raw`, `policy`, `labels`, `benchmark`.
- Contract checked against DC-COLL-001 (owner, refresh, quality rules, allowed/not-allowed uses): all covered. No change needed.
- `make test-contract` green (92 passed), `ruff` and `mypy` clean on changed files.

## Decisions and changes from the plan
- `ask_blocked_columns` takes the part after the first dot of each `directPiiColumns` entry, so
  `call_transcripts.turn.text` adds `turn.text` (never matches a real column; `turns` is blocked anyway).

- The release has `call_transcripts.csv` (call-level) plus separate JSON files; only the CSV lands in bronze. The `turns` JSON stays in `data/raw/files/transcripts/` for Track C. The `_source_file` column holds the absolute path on the machine that landed it.

## Open questions
<!-- Each with what the docs say about it (file and section). -->
- Ground-truth IDs, autopay/PAD accounts at other FIs: TEAM_PLAN §9, to ask the organisers.

## Log
<!-- Newest first: time, what happened. -->
- 2026-10-03: Phase 1 parallel tasks done; stopped for G0.
- 2026-10-03: Phase 1 started. Dataset download started into `../maple_data` (voice zip excluded); uv installed.
