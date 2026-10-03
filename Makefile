.PHONY: help setup setup-a setup-b setup-c setup-d setup-all test test-contract test-a test-b test-c test-d progress lint fmt typecheck dbt-build serve

help:  ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

# ----------------------------------------------------------------- setup
setup:  ## core + dev tools (enough for contracts and unit tests)
	uv sync

setup-a:  ## Track A: Data and IDs (dbt, Splink, Soda)
	uv sync --extra data

setup-b:  ## Track B: Collections Ask (sqlglot, LanceDB, LiteLLM)
	uv sync --extra ask

setup-c:  ## Track C: text features (Presidio, SetFit, Fairlearn) + spaCy model
	uv sync --extra text
	uv run python -m spacy download en_core_web_lg

setup-d:  ## Track D: features + models + app (Feast, LightGBM, SHAP, MLflow, FastAPI)
	uv sync --extra model

setup-all:  ## everything (large: pulls torch)
	uv sync --all-extras

# ----------------------------------------------------------------- tests
test:  ## full suite, strict (red until implemented)
	uv run pytest

test-contract:  ## shared API contract tests: must always be green
	uv run pytest -m contract

test-a:  ## Track A tests
	uv run pytest -m track_a
test-b:  ## Track B tests
	uv run pytest -m track_b
test-c:  ## Track C tests
	uv run pytest -m track_c
test-d:  ## Track D tests
	uv run pytest -m track_d

progress:  ## how many tests are still stubbed, per track
	@for t in track_a track_b track_c track_d; do \
		printf "%-8s " $$t; \
		uv run pytest -q --allow-stubs -m $$t -p no:cacheprovider 2>/dev/null | tail -1; \
	done

# ----------------------------------------------------------------- quality
lint:  ## ruff
	uv run ruff check .

fmt:  ## ruff format + autofix
	uv run ruff format . && uv run ruff check --fix .

typecheck:  ## mypy (strict)
	uv run mypy

# ----------------------------------------------------------------- run
dbt-build:  ## build bronze -> silver -> gold -> features
	cd dbt && uv run dbt build --profiles-dir . --project-dir .

serve:  ## run the API
	uv run kept serve  # Track D: wire Services into create_app
