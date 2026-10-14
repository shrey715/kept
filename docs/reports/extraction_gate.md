# Text extraction: the release gate

The local model (Qwen3.8-27B on llama.cpp since 15 October; Gemma 3 12B on Ollama before), prompt `extract-v4` plus the
cease rule, on the release's public labels. Every text is redacted first, and every positive value must quote the text
it came from. Gate: F1 ≥ 0.80, hardship recall ≥ 0.90. The holdout split was used only to check, not to tune.

    uv run python scripts/eval_extraction.py --source notes --split holdout
    uv run python scripts/eval_extraction.py --source transcripts --split holdout
    uv run python scripts/eval_extraction.py --source transcripts --calls whisper   # or --calls release

## Holdout: every field passes, on both models

| Field | Notes F1 (149), Qwen | Gemma | Recall, Qwen | Calls F1 (149), Qwen | Gemma | Recall, Qwen |
|---|---:|---:|---:|---:|---:|---:|
| Hardship | **0.88** | 0.84 | **1.00** | **0.99** | 0.99 | **1.00** |
| Promise to pay | **0.88** | 0.88 | 0.95 | **0.99** | 0.97 | 1.00 |
| Promised date | **0.91** | 0.84 | 0.83 | 0.95 | 0.96 | 0.90 |
| Promised amount | **0.96** | 0.93 | 0.92 | **1.00** | 1.00 | 1.00 |
| Dispute | 0.86 | 0.86 | 1.00 | **1.00** | 0.93 | 1.00 |
| Cease request | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Third party present | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Qwen is the default: as good or better on every notes field, and on calls level or better except promised date (0.95
against 0.96). It also lets one model serve the Ask, the briefs and extraction on the 16 GB GPU (Gemma on Ollama and
Qwen on llama.cpp don't fit together). About 3.6 s a note and 4.1 s a call with two requests at once.

Every text gets a usable reply: the local model decodes straight to the JSON schema (each field's value typed), so it
can't return a malformed field. Before that, 10 of the 149 calls broke the schema and were left out. Cease and third
party have only 1–2 positives in each holdout, so treat those two F1s as "no misses", not as a precise rate.

## Cease: what the model got wrong, and the fix

The model never missed a labelled cease request, in any split. It failed the gate on false alarms, of two kinds:

- **Anger about call frequency**: "Stop calling me every day! This is harassment.", "Arretez de m'appeler tous les
  jours!". The labels treat these as complaints for a supervisor, not a request to stop all contact.
- **The insolvency stay**: "says filed bankruptcy … cease contact noted". Contact stops, but because the law says so
  (insolvency has its own hold flag in Kept), not because the customer asked.

Telling the model so in the prompt didn't move it, so a small rule on the model's own quote does
(`kept.text.extract._cease`, tested in `tests/text/test_extract_and_eval.py`). Before the rule, cease F1 on the calls
holdout was 0.20 (8 false alarms); after, 1.00 with no new misses. Every cease is still confirmed by an agent before it
blocks contact.

## From the recording, not the transcript

The 48 labelled calls that have a recording, read by the same extraction from the release's transcript and from
Whisper's own transcript of the audio (`docs/reports/voice_wer.md`):

| Field | Release transcript F1 | Whisper transcript F1 |
|---|---:|---:|
| Hardship | 1.00 | **0.98** (recall 1.00) |
| Promise to pay | 1.00 | 0.90 |
| Promised amount | 0.97 | 1.00 |
| Promised date | 0.96 | 0.88 |
| Dispute | 0.86 | 0.86 |

Every hardship in these calls is caught straight from the audio. Dates suffer most: the Whisper transcript has no
speaker labels, so "the 15th" is sometimes the agent's suggestion, not the customer's promise. Transcribing the agent and
customer channels separately is the next step.
