# Kept

A guarded next best action for promises customers can keep.
Team Sharpe Shooters, CIBC Collections Hackathon.

- Design: [`docs/SharpeShooters_SystemDesign.pdf`](docs/SharpeShooters_SystemDesign.pdf)
- Data dictionary: [`docs/CIBC Hackathon - Data Dictionary.xlsx`](docs/)
- **Who builds what, interfaces, TDD workflow: [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md)**

This is a skeleton: every function is a documented stub that raises `NotImplementedError`,
and the tests are the spec. Make them pass.

## Quick start

```bash
make setup          # core + dev tools (uv sync)
make setup-a        # or -b / -c / -d: your track's heavy libraries
make test-contract  # shared API: must always be green
make test-a         # your track: red until you implement it
make progress       # stubs remaining per track
```

Copy `.env.example` to `.env` for LLM keys. Put the organisers' files in `data/raw/`
(see [`data/README.md`](data/README.md)); nothing under `data/` is committed.

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
