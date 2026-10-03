# data/

Nothing in here is committed except this README and the `.gitkeep` files (see `.gitignore`).
Customer data never goes into git.

| Folder        | What goes here                                                          | Owner   |
|---------------|-------------------------------------------------------------------------|---------|
| `raw/`        | The 31 source tables exactly as the organisers give them: CSV (small tables), Parquet by year (history: `transactions/year=2025/...`), JSON (`call_transcripts`), WAV (`voice_samples`) | Track A |
| `warehouse/`  | `kept.duckdb` (bronze, silver, gold, features, quarantine, steward) and `audit.duckdb` | Track A |
| `exports/`    | Parquet exports partitioned by `as_of_date` (C360, features)            | Track A / D |
| `quarantine/` | Rows silver couldn't parse, with the reason                             | Track A |
| `labels/`     | 300 notes labelled twice (text F1 gate), 300 reviewed match pairs       | Track C / A |
| `benchmark/`  | The organisers' Collections Ask benchmark questions                     | Track B |
| `policy/`     | Policy documents and the LanceDB index built from them                  | Track B |
| `models/`     | Local model artefacts (SetFit); uplift models live in MLflow (`mlruns/`) | Track C / D |

The table list, columns, sensitivity labels and relationships are in
`docs/CIBC Hackathon - Data Dictionary.xlsx`; `tests/contracts/test_data_dictionary.py`
keeps our contract in step with it.

## How the release goes into `data/` (K3)

Download and unzip the release as in `docs/TEAM_PLAN.md` §3 (Q1), then, from inside
`maple_collections_release/`, with `$K` = this repo's `data/` folder:

```bash
cp -a data/. $K/raw/                                   # 31 tables: *.csv and <table>/year=YYYY/*.parquet
mkdir -p $K/raw/files && cp -a files/transcripts files/docs $K/raw/files/   # file_path columns resolve from raw/files/
cp -a files/docs/. $K/policy/                          # policy documents for Track B
cp labels/agent_notes_labels_public_500.csv labels/call_transcripts_labels_public_500.csv $K/labels/
cp labels/benchmark_*.csv data/benchmark_questions.csv $K/benchmark/
# Track C only, after unzipping the voice pack: cp -a files/voice $K/raw/files/
```

Then `uv run kept land` lands `raw/*.csv` and each `raw/<table>/` Parquet folder as
`bronze.<table>` in `warehouse/kept.duckdb`: every column VARCHAR (leading zeros and `NA`
codes survive), plus `_source_file`, `_extracted_at`, `_loaded_at`. `raw/files/` is not landed
(transcript JSON and policy documents are read by Tracks C and B).
