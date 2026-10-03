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
