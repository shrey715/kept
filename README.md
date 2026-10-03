# Kept

A guarded next best action for promises customers can keep.
Team Sharpe Shooters, CIBC Collections Hackathon.

- Design: [`docs/SharpeShooters_SystemDesign.pdf`](docs/SharpeShooters_SystemDesign.pdf)
- Data dictionary: [`docs/CIBC Hackathon - Data Dictionary.xlsx`](docs/)
- **Who builds what, phases, integration gates, interfaces: [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md)**

## Run it

Two ways to run Kept. **The demo** needs nothing but this repo (12 in-memory cases). **The real
system** runs the nightly pipeline over the 1M-customer release, then serves every open case.

### 1. Prerequisites

| Tool | Version | Who needs it |
|---|---|---|
| Python + [uv](https://docs.astral.sh/uv/) | 3.12, uv ≥ 0.5 | everyone |
| Node + [pnpm](https://pnpm.io/) | Node 22, pnpm ≥ 10 | the web app |
| [Ollama](https://ollama.com/) with `gemma3:12b-it-qat` (`ollama pull gemma3:12b-it-qat`, ~9 GB) | current | text extraction (a GPU with ~11 GB VRAM) |
| RAM | 16 GB for serving; **≥ 24 GB for the full nightly** (land peaks at ~7 GB, match at ~15 GB) | the machine that runs `kept nightly` |
| Disk | ~25 GB free (release 7.3 GB, warehouse ~9 GB, exports) | the real system |

### 2. Install

```bash
make setup-all             # every track's libraries (large: pulls torch); or setup + setup-a/-b/-c/-d
make web-setup             # web app (pnpm install in web/)
cp .env.example .env       # then fill it in (below)
```

`.env`, never committed. Free LLMs only:

| Variable | Set it to |
|---|---|
| `KEPT_HOLDOUT_SALT` | **the team's one shared value.** It decides which cases are in the 5% hold-out; every machine must match, and it never changes after go-live |
| `GEMINI_API_KEY` | your own free key (the Ask: `KEPT_ASK_LLM_MODEL=gemini/gemini-3.5-flash-lite`) |
| `KEPT_TEXT_LLM_MODEL`, `OLLAMA_API_BASE` | leave as in `.env.example` (local gemma3 through Ollama) |
| `MLFLOW_TRACKING_URI` | `sqlite:///mlflow.db` (MLflow 3 refuses the old `file:./mlruns`) |
| `KEPT_KILL_SWITCH` | `false`; `true` falls every card back to the current strategy |

### 3. The demo (no warehouse needed)

Two terminals:

```bash
make serve-demo            # API on :8000: the real engine and release gate over 12 demo cases
make web                   # web app on :3000, forwarding /api to the API
```

Open <http://localhost:3000>: the landing tells the story; **Run the guided demo** walks the
six-step script. Personas have direct links, e.g. `/signin?as=agent-7&next=/queue`,
`/signin?as=hs-1&next=/approvals`, `/signin?as=tl-1&next=/approvals`, `/signin?as=c-1&next=/audit`.

- Demo mode runs on a business-hours clock (shown in the header) so releases pass the real
  calling-hours check at any time of day. Restarting the API resets the demo cases.
- **Port 8000 taken** (VS Code often holds it): `uv run kept serve --demo --port 8010` and
  `cd web && KEPT_API_URL=http://127.0.0.1:8010 pnpm dev`.
- **From another machine on the network:** `cd web && KEPT_DEV_ORIGINS=<this machine's IP> pnpm dev`,
  then open `http://<ip>:3000`. Without it the dev server serves the page but not its scripts.
- **For the live demo**, use the production build (faster, no dev overlay):
  `cd web && pnpm build && KEPT_API_URL=http://127.0.0.1:8000 pnpm start`.

### 4. The real system

**Data.** Download the release and lay it out under `data/` exactly as [`data/README.md`](data/README.md)
says. Nothing under `data/` is ever committed. Then put the team's hand-over files in place (Drive folder):

| File | Where | Why |
|---|---|---|
| `extractions_880b98c_20261003.parquet` | `data/exports/extractions/` | the SetFit backfill of all 785,594 notes and calls. **Without it the first nightly would send every note through the live model** |
| `identity_crosswalk_<run>.parquet` (+ `review_pairs_<run>.parquet`) | `data/exports/identity_crosswalk/` | optional: `kept match` keeps these golden IDs stable; without it the first run assigns new ones. The review pairs fill the steward queue |

**First run on a fresh machine** (each step is its own process; about 20 minutes in all):

```bash
uv run kept nightly --skip score   # land -> silver -> match -> gold -> gate -> extract -> features -> parity
uv run kept features --training    # features one second before every past decision (features_train)
uv run kept train                  # uplift model -> data/exports/models/uplift.pkl, metrics in MLflow
uv run kept score                  # a card for every open case -> nba.cards (96,000 in ~2.5 min)
uv run python scripts/build_policy_index.py   # the Ask's policy search (data/policy -> LanceDB), once
```

**Every night after that:** `uv run kept nightly`. It stops at the first failing step, so a blocked
quality gate publishes no features or cards; resume with `--from <step>`, leave a step out with
`--skip <step>` (e.g. `--skip extract` on a machine without Ollama). `kept features` defaults to the
latest 06:00 UTC run, so cards are never stale.

| Step | Command | Owner | What it does |
|---|---|---|---|
| land | `kept land` | A | `data/raw` -> 31 bronze tables |
| silver | `kept build --silver-only` | A | dbt: cleaned silver |
| match | `kept match --train-sample-mod 5` | A | exact links + Splink (trained on a 1-in-5 sample, scores every key) -> crosswalk |
| gold | `kept build --gold-only` | A | crosswalk + extractions -> `gold.c360_customer`, hardship via `hardship.combine` |
| gate | `kept gate` | A | quality rules Q1-Q5; blocks the run on failure |
| extract | `kept extract --new` | C | tonight's new notes -> redaction -> gemma3 -> `text.extractions` |
| features | `kept features` | D | dbt features (point in time) -> Parquet -> Feast online store |
| parity | `kept parity` | A | offline vs online features, ≤ 0.1% mismatch |
| score | `kept score` | D | `nba.cards`: one card per open case, one audit event each |

**Serve it** (the API owns the warehouse while it runs: no batch jobs against it at the same time):

```bash
uv run kept serve          # API on :8000 over the real services
make web                   # or the production build above
```

- `/queue` reads the nightly's cards (an agent sees their own cases); opening a case re-checks it live.
- **Add a note** on a case runs live extraction (Presidio + gemma3, a few seconds) and re-checks the card:
  a hardship note turns it Red. A possible cease request shows a red banner the assigned agent confirms.
- The Ask answers with the free Gemini tier; policy questions cite the section.
- Without Presidio installed (`make setup-c`) adding a note answers 503; everything else works.

### 5. Tests

```bash
make test-contract         # shared API: always green
make test                  # the full suite (1,100+ tests)
make lint typecheck
cd web && pnpm lint && npx tsc --noEmit
```

## What changed from the design, and why

- **UI (D):** a Next.js app with Radix Themes instead of the plan's single static page, so the
  demo covers every role's flow (queue, approvals, audit, Ask) and the guided script. It needs
  Node on the demo machine.
- **Red-tier release in two steps (D):** a hardship specialist approves, then a second person
  releases after a fresh safety recheck, instead of both names on one form. The handoff is real:
  the proposal waits in the second person's inbox.
- **Safety checks run at the proposed contact time (D):** a 06:00 batch would otherwise block
  every call; the release gate rechecks everything again at release.
- **SHAP from LightGBM itself (D):** `pred_contrib` instead of the `shap` package, converted to
  probability points per feature.
- **Feast offline store is `file` (D):** the DuckDB offline store needs `ibis`; the file store reads
  the same Parquet export.

- **Text extraction runs on a local model (C):** `gemma3:12b` through Ollama on the team's GPU,
  not a hosted API: no rate limits, no cost, and note text never leaves the machine. Every value
  needs a verbatim quote from the note, or it is dropped.
- **Cease from text needs an agent's confirmation (C):** cease failed the F1 gate on precision
  (held-out 0.50 notes, 0.20 calls; 1–2 true cases each), so an extracted cease is shown as
  "possible cease: confirm" and only becomes a hard stop once an agent confirms it
  (`/extractions/{id}/confirm`). The other six text features passed the gate.
- **SetFit backfills hardship only (C):** the 785,594 historical notes and calls get a hardship
  signal from SetFit trained on 1,604 LLM labels (held-out recall 0.98 notes, 0.99 calls);
  promises, disputes and cease come from structured tables for history, and from the LLM for new notes.
- **French-aware redaction (C):** 14% of notes are French, so Presidio runs a French spaCy model on
  them; card numbers and DOBs are caught even when the synthetic data mangles them. A scan of all
  785,594 redacted texts finds no leftover cards, phones, emails, SINs, postal codes or DOBs.
- **Splink trained on a 20% sample (A, run by C):** EM over all 3.84M keys didn't finish or fit in
  RAM; training on a 1-in-5 DOB-hash sample and scoring every key gives 1,052,300 golden IDs.
- **Cash-flow hardship from deposit data (C):** late payroll, a 20% pay drop or new EI deposits
  add a possible-hardship observation to gold (`hardship.cashflow_observations`).

- **Ask on a free hosted model (B):** `gemini/gemini-3.5-flash-lite` through LiteLLM, one free key per
  person, because a paid key is not an option. Every question is redacted (Presidio) before any LLM call,
  and each call is logged without the prompt text. The free tier allows 500 requests a day per project, so
  a full benchmark run (about 110 calls) is rationed.
- **Certified SQL for 14 of 15 metrics (B):** the metric definitions' formulas are pseudo-SQL, so each
  certified metric is hand-translated to reviewed SQL and the LLM never writes it. `write_off_rate` is
  not certified: its period bounds only the numerator, and one date column cannot express that. That SQL
  also goes through the SQL guard before it runs.
- **Lookups are voted and repaired (B):** three SQL drafts, the result shared by a majority wins, and a
  draft that will not run gets one repair round in which the model sees the database error. Without it,
  one bad draft left the other two disagreeing and the Ask refused.
- **Policy search is keyword search, not embeddings (B):** LanceDB full-text (BM25) over the 19 policy
  documents: no model download, and only sections current on the asked date are returned, so a superseded
  version is never cited. Policies and procedures outrank FAQs and call scripts when they disagree.
- **Numbers must come from the rows (B):** a narrative whose numbers are not in the result is dropped and
  replaced by "the result is in the table", so the Ask never states a figure the query did not return.
- **Where the reference answers take a shortcut, we follow them (B):** the roll rate reads
  `month_end_date` the way the reference does (it skips the MM/DD/YYYY spelling, 3.3% of rows), and two
  other dev questions group the way the reference does. Everywhere else the Ask computes from cleaned data.
- **Call summaries and incidents (B, with C):** "summarise the most recent call on case X" is answered from
  that call's redacted transcript by Track C's `summarise_call`, before the scope check (which saw "personal
  data" in it); a case with no recorded call gets "there is no recorded call", not a refusal. "Why did X
  change on that day" is answered from the incident reports and the operations-events table (indexed with
  the policies).
- **Fairness report on the real cards (B):** `docs/fairness_report.md` compares recommendations across the
  protected attributes in `gold.c360_restricted` (compliance only); a blank attribute is reported, not
  treated as a group.

## AI tools we used, and for what

- **Claude Code (D):** pair-programming the Track D code and tests, the web app, and the
  dataset checks behind the legacy-code and random-assignment answers. Every change went through
  the tests and a person's review before merging.

- **Claude Code (C):** pair-programming the Track C code, tests and scripts (redaction,
  extraction, backfill, cash-flow rule), running and monitoring the heavy jobs on the GPU machine,
  and keeping the team plan, gates and PRs in step. Every change went through tests and a person's review.
- **gemma3 12B (local, Ollama) (C):** extracts the text features from redacted notes, and labelled
  1,604 notes to train SetFit. Tuned and gated on the release's public labels (30% held out).
- **SetFit (`BAAI/bge-small-en-v1.5`) (C):** the fast classifier that backfills hardship for all history.

- **Claude Code (B):** pair-programming the Track B code and tests, running the benchmark and tuning the
  prompts and certified SQL from what it showed, and writing the scorecard and fairness notes. Every change
  went through the tests and a person's review before merging.
- **Gemini 3.5 Flash-Lite (hosted, free tier) (B):** the Ask's scope check, question routing, SQL drafting
  for lookups, and plain-English narration of results. Its output is checked by code: the SQL guard before
  anything runs, and the grounding check on every number.

## Layout

```text
contracts/c360_customer.odcs.yaml   data contract (ODCS): golden record, quality rules, protected/PII lists
src/kept/
  contracts/      fixed API between tracks: models, enums, Protocols, feature registry
  config.py       every threshold the design commits to
  common/         LLM gateway (LiteLLM), audit log, DuckDB connection
  data/           Layer 1  Data Product Factory: ingest, clean, traps, identity/, gold, quality   (A)
  ask/            Layer 2  Collections Ask: scope, router, metrics, lookup, policy, SQL guard     (B)
  text/           Layer 3  redaction, extraction, SetFit backfill, F1 gate, Whisper               (C)
  hardship/       hardship combination, cash-flow rule, programme eligibility                     (C)
  governance/     lineage CI check, fairness (C); role access and masking (D)
  features/       Layer 3  feature definitions, Feast provider (D); parity (A)
  nba/            Layer 4  rules, uplift, sizing, ranking, explain, tiers, release, engine        (D)
  app/            FastAPI routes for the cards (D, routes per owner)
  cli.py          `uv run kept <step>` for the nightly pipeline
dbt/                bronze -> silver -> gold -> features (DuckDB)
feature_repo/       Feast
soda/               Soda checks, generated from the contract
tests/              mirrors src/; tests/fakes.py has a fake for every interface
data/               local data only (git-ignored)
```

## Stack

DuckDB, dbt, Splink, Soda (Layer 1) · LiteLLM, sqlglot, LanceDB (Layer 2) ·
Presidio, SetFit, Feast (Layer 3) · LightGBM, SHAP, MLflow, FastAPI (Layer 4).
Python 3.12, managed with `uv`; each track's libraries are an optional extra in `pyproject.toml`.
