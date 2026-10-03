# Team plan: who builds what, and how the parts connect

Source of truth for the design: `docs/SharpeShooters_SystemDesign.pdf`.
Source of truth for the data: `docs/CIBC Hackathon - Data Dictionary.xlsx`.

We split the work into four tracks, matching the four columns of the design's 36-hour build plan (§10).
Each track owns its packages and tests. Tracks talk to each other **only** through
`src/kept/contracts/` (the fixed API), so nobody waits on anybody: until a
neighbour's code is real, test against the fakes in `tests/fakes.py`.

## Tracks

| Track | Design column | Owns (code) | Owns (tests) | Extra |
|---|---|---|---|---|
| **A: Data and IDs** | Layer 1 + parity test | `kept/data/**`, `kept/common/db.py`, `kept/contracts/data_contract.py`, `kept/features/parity.py`, `dbt/models/{bronze,silver,gold}`, `soda/`, `contracts/*.yaml`, `/steward` routes | `tests/data`, `tests/features/test_parity.py` | `make setup-a` |
| **B: Ask** | Layer 2 | `kept/ask/**`, `kept/common/llm.py` (LLM gateway), `/ask` route | `tests/ask`, `tests/common/test_llm_gateway.py` | `make setup-b` |
| **C: Text features** | Layer 3 text + fairness | `kept/text/**`, `kept/hardship/**`, `kept/governance/{lineage,fairness}.py`, `/extractions` route | `tests/text`, `tests/hardship`, `tests/governance/test_lineage_and_fairness.py` | `make setup-c` |
| **D: Model and UI** | Layer 3 SQL features + Layer 4 + app | `kept/features/{definitions,store}.py`, `feature_repo/`, `dbt/models/features`, `kept/nba/**`, `kept/app/**`, `kept/common/audit.py`, `kept/governance/access.py` | `tests/features`, `tests/nba`, `tests/app`, `tests/common/test_audit.py`, `tests/governance/test_access.py` | `make setup-d` |

Write your name next to a track when you pick it:

- Track A: ______
- Track B: ______
- Track C: ______
- Track D: ______

Track D is the heaviest. If it falls behind, hand `kept/features/` (dbt features + Feast)
to Track A after hour 18: A already owns the parity test, and the package is self-contained.

## Timeline (design §10)

| Hours | A: Data and IDs | B: Ask | C: Text features | D: Model and UI |
|---|---|---|---|---|
| 0–3 | land tables (`ingest`), contract loader, **fill TBCs below** | metrics + benchmark loaders, scorecard | redaction, label 300 notes ×2 | labels, rules, app skeleton, audit log |
| 3–10 | cleaning, traps, exact links, Splink | router, SQL guard | extraction prompt + eval gate | hard stops, permission gate, dbt features |
| 10–18 | gold C360, quality checks + report | answer card (service) | LLM labels, SetFit backfill | Feast, uplift model, legacy code mapping |
| 18–26 | steward review screen | policy search (LanceDB) | live extraction, hardship programmes | Kept sizing, ranking, SHAP |
| 26–32 | parity test | full benchmark | fairness + lineage tests | NBA card, release gate |
| 32–36 | everyone: end-to-end demo (raw keys → C360 → Ask → a new note flips hardship → the NBA changes), video, deck | | | |

What to cut if we fall behind (design §10): the semantic layer first, then voice, then
the similar-cases line. We don't cut ID matching, refusals, the safety rules or the release gate.

## How the parts connect

```
           contracts/c360_customer.odcs.yaml  (allow-lists, protected attrs, PII lists)
                          │ DataContract
   A ──── gold.c360_customer / C360Reader ──────────────┬──────────────┐
   │                                                    │              │
   │                                  C ── Redactor ──▶ B (Ask)        │
   │                                  C ── TextExtractor ─▶ D (features: hardship, cease, promise)
   │                                                                   │
   └── parity_report ◀── FeatureProvider (offline vs online) ── D ── NBAEngine / ReleaseGate ──▶ app
                                       LLMGateway (B) + AuditLog (D) used by everyone
```

| Interface (`kept.contracts.interfaces`) | Provider | Consumers | Fake |
|---|---|---|---|
| `C360Reader` | A | B, C, D | `DictC360Reader` |
| `Redactor` | C | A, B, C | `PassThroughRedactor` |
| `TextExtractor` | C | D | (scripted via `PurposeLLM`) |
| `FeatureProvider` | D | D, A (parity) | `StaticFeatureProvider` |
| `UpliftScorer` | D | D | `ConstantScorer` |
| `CaseContextBuilder` | D (reads A's C360) | D | `FixedContextBuilder` |
| `NBAEngine`, `ReleaseGate` | D | app | fakes in `tests/app/test_api.py` |
| `AskService` | B | app | fake in `tests/app/test_api.py` |
| `LLMGateway` | B | A, B, C | `ScriptedLLM`, `PurposeLLM` |
| `AuditLog` | D | everyone | `InMemoryAuditLog` |

Shared data shapes (`kept.contracts.*`): `GoldenCustomer`, `CrosswalkEntry`, `FeatureVector`,
`TextExtraction`, `RedactedText`, `CaseContext`, `Proposal`, `NBACard`, `ReleaseDecision`,
`AskRequest`/`AskAnswer`/`Refusal`/`Clarification`, `AuditEvent`.
The feature list is `kept.contracts.feature_registry.FEATURES`. Every threshold the design
commits to is in `kept.config`.

## TDD workflow

1. Pick a red test in your track: `make test-b` (or `uv run pytest tests/ask/test_sql_guard.py`).
2. Replace the `raise NotImplementedError` with the smallest code that makes it pass.
3. Keep the contract suite green: `make test-contract` (CI runs it strictly).
4. See where everyone is: `make progress` (counts stubs per track).

CI runs `pytest --allow-stubs`: a test that hits a stub (or is marked `todo`) is
reported as xfail, so main stays green while work is in progress. Any other failure fails CI.
Tests marked `integration` need your track's extra (`make setup-x`) and skip without it.

Tests are the spec. If a test is wrong (the data says otherwise), change it in its
own commit with a one-line reason, and tell the track that consumes the behaviour.

## Changing a contract

Anything in `src/kept/contracts/`, `contracts/*.yaml`, `kept/config.py`, `tests/fakes.py`
or `dbt/models/gold/schema.yml` is shared.

- **Additive** (new optional field, new enum member, new feature): PR + one reviewer from each track that imports it.
- **Breaking** (rename, remove, type change): agree in chat first, bump `CONTRACT_VERSION`, update the fakes in the same PR.
- The four copies of the golden record (ODCS YAML, `GoldenCustomer`, dbt `schema.yml`, the gold SQL stub)
  and the feature registry vs `FeatureVector` are checked by `tests/contracts/`. The contract is also
  checked against the data dictionary (`tests/contracts/test_data_dictionary.py`).

## Day-1 TBCs (resolve and update the tests)

| Item | Owner | Where |
|---|---|---|
| Which `assignment_method` / `test_cell` values mean random assignment (`code_lookups`) | D + A | `kept/nba/uplift.py` |
| Full code lists for `nba_recommendation_last` and `treatment_code` → `Action` | D | `kept/nba/legacy.py` |
| Certified `metric_id` for roll rate; hand-translate certified metrics to SQL | B | `kept/ask/metrics.py` |
| Final Ask table list vs `benchmark_questions.expected_tables` | B + A | `contracts/c360_customer.odcs.yaml` |
| Authoritative payment source per product for `paid_14d` | D + A | `kept/nba/labels.py` |
| Ground-truth IDs for scoring matching? Ask the organisers | A | `kept/data/identity/` |
| Autopay/PAD accounts at other FIs: ignore or quarantine | A | `kept/data/identity/exact.py` |
| Cash-flow rule thresholds, proposal TTL, close-call margin | C, D | `kept/hardship/cashflow_rule.py`, `kept/config.py` |
| Fill `REASON_TEMPLATES` (one fixed sentence per model feature) | D | `kept/nba/explain.py` (test marked `todo`) |

## Data traps the dictionary confirms (tests already cover them)

- Account tables have one row per `snapshot_date`; take the latest (`traps.latest_snapshot`).
- `card_accounts.cycles_delinquent` counts cycles, not days; use `dpd`.
- Bureau `risk_score` scales differ by `risk_score_model`: use percentiles within the model.
- `transactions` covers 13 months for a customer sample only: missing stays missing.
- `customers` is SCD2 with CDC; `duplicate_of_crm_id` is CRM's own incomplete pointer.
- `contact_history.channel` was renamed `channel_v2` on 26 Sep (schema drift).
- `collections_cases` holds each case's latest state: build training rows from snapshots and
  `contact_history`'s at-contact fields, never from the case row's current values.
- `national_dncl_flag` covers telemarketing, not collections: it must not block contact.
- Protected attributes live outside `customers` too: `deposit_accounts.ccb_deposit_flag`,
  `voice_samples.customer_accent_region`.
