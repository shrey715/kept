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

## AI tools we used, and for what

- **Claude Code (D):** pair-programming the Track D code and tests, the web app, and the
  dataset checks behind the legacy-code and random-assignment answers. Every change went through
  the tests and a person's review before merging.

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
