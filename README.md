# Kept

A guarded next best action for promises customers can keep.
Team Sharpe Shooters, CIBC Collections Hackathon.

- Design: [`docs/SharpeShooters_SystemDesign.pdf`](docs/SharpeShooters_SystemDesign.pdf)
- Data dictionary: [`docs/CIBC Hackathon - Data Dictionary.xlsx`](docs/)
- **Who builds what, phases, integration gates, interfaces: [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md)**

## Run it

### 1. Prerequisites

| Tool | Version | Who needs it |
|---|---|---|
| Python + [uv](https://docs.astral.sh/uv/) | 3.12, uv ≥ 0.5 | everyone |
| Node + [pnpm](https://pnpm.io/) | Node 22, pnpm ≥ 10 | whoever runs the web app (the demo machine) |
| Google Chrome or Firefox | current | the demo |

### 2. Install

```bash
make setup                 # core + dev tools
make setup-d               # or setup-a / -b / -c / setup-all: your track's libraries
make web-setup             # web app (pnpm install in web/)
```

Copy `.env.example` to `.env` (free LLMs only: a local Ollama model and a free hosted tier).

### 3. Data

Download the release and lay it out under `data/` exactly as [`data/README.md`](data/README.md) says,
then land it: `uv run kept land` (31 bronze tables in `data/warehouse/kept.duckdb`). Nothing under
`data/` is ever committed.

### 4. The demo (no warehouse needed)

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
- **Showing it from another machine on the network:** `cd web && KEPT_DEV_ORIGINS=<this machine's IP> pnpm dev`,
  then open `http://<ip>:3000`. Without it the dev server serves the page but not its scripts.
- **For the live demo**, use the production build (faster, no dev overlay):
  `cd web && pnpm build && KEPT_API_URL=http://127.0.0.1:8000 pnpm start`.
- `uv run kept serve --demo --reload` restarts the API when Python code changes (demo state resets).

### 5. The pipeline on real data

```bash
uv run kept land           # A: raw -> bronze
uv run kept build          # A: dbt bronze -> silver -> gold          (G1/G2)
uv run kept match          # A: exact links + Splink                  (G1)
uv run kept features       # D: dbt features -> Parquet -> Feast      (G2)
uv run kept train          # D: uplift models, logged to MLflow       (after G2)
uv run kept score          # D: a card for every open case            (G3)
uv run kept serve          # D: the API on the real services          (G4)
uv run kept nightly        # everyone: the steps above in order       (G4)
```

Commands marked with a gate land when that gate passes (`docs/TEAM_PLAN.md` §6).

### 6. Tests

```bash
make test-contract         # shared API: always green
make test-d                # one track (a / b / c / d)
make lint typecheck
make progress              # stubs left per track
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
