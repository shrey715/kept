# Next steps: G0 and Phase 2 (all tracks)

Written 3 Oct, after every Phase 1 PR was merged. Source of truth for tasks: `docs/TEAM_PLAN.md`
§5 (tasks), §6 (gates), §3a (conventions). This file says where each track stands, what to do
next, how to ship it through GitHub, and **where to stop**. Agents: read this, then your track's
section, then the plan sections it points to.

Deadline: **4 Oct, 9:00 PM IST** (commits after it don't count). Extra benchmark questions: 4 Oct, 7:00 PM.

---

## 1. Where main is

`main` = PRs #1–#6 merged (team plan, A, C, B, D, dbt pin). CI green. With every extra installed:
622 passed, 314 xfailed (stubs for later phases), 0 failures. The four early providers are on
main and importable: `load_data_contract` (A), `LiteLLMGateway` (B), `PresidioRedactor` (C),
`DuckDBAuditLog` (D).

| Track | Done (on main) | Phase now |
|---|---|---|
| **A** Satvik | Contract loader; `connect`, `land_file`, `land_directory`, `kept land` (31 bronze tables, row counts match the README); raw layout in `data/README.md` (K3); contract checked against DC-COLL-001 | Phase 1 done → **G0** |
| **B** Abhishek | `LiteLLMGateway`; metrics + certified SQL (14/15 metrics, several match dev gold); benchmark load/score/write; Phase 2: scope, router, SQL guard, privacy | Phases 1–2 done → **G0**, then Phase 3 |
| **C** Akshat | `PresidioRedactor` (EN + FR, Canadian SIN/postal, cards); `evaluate.py`; public labels mapped (`kept/text/labels.py`); `text.extractions` draft; compute machine ready (CUDA, SetFit on GPU, Ollama via LiteLLM) | Phase 1 done → **G0** |
| **D** Shreyas | Every parallel task of Phases 1–5: audit, labels, rules, access, features + dbt features, Feast, uplift, context builder, sizing, ranking, explain, engine, releaser, API routes, Next.js app in `web/`, `kept serve --demo` | Parallel work done; rest needs other tracks |

Dependency fixes merged with this: `setfit>=1.1` (text extra) and `dbt-duckdb<1.10` (data
extra). After pulling main run `uv sync --extra <yours>` (C: `--all-extras`). dbt now works
without the `--with` workaround.

---

## 2. How every track ships work (strict)

One branch per track (`track-a` … `track-d`), one open PR per track, merged often. GitHub
updates an open PR on every push to its branch, so the PR is the live progress view.

```bash
# Start of every task (K1)
git checkout track-x
git fetch origin && git merge origin/main        # merge, never rebase or force-push a pushed branch
uv sync --extra <yours>                          # picks up anyone's dependency change

# ... work in your own files, small commits, one-line messages ...

# Before every push
make lint && make test-contract && make test-x   # all green, or don't push
git push

# Once per phase: open the PR if none is open (later pushes update it automatically)
gh pr view track-x >/dev/null 2>&1 || gh pr create --draft --base main --head track-x \
  --title "Track X: Phase N" --body "<checklist: this phase's tasks from TEAM_PLAN §5>"

# When a task's tests go green: tick its box in the PR body, update docs/tracks/Track_X.md
# When CI is green and the branch has main merged in:
gh pr ready && gh pr merge --merge               # merge commit, not squash: keeps everyone's commits
# The next push after a merge opens the next PR the same way.
```

Rules that keep merges seamless:
- **Own files only** (plan §1). Shared files (`src/kept/contracts/`, `contracts/*.yaml`,
  `kept/config.py`, `tests/fakes.py`, `dbt/models/gold/schema.yml`) change only in their own small
  PR with one reviewer from each track that imports them; breaking changes bump `CONTRACT_VERSION`
  and update the fakes in the same PR (§8, Q11).
- **`kept/cli.py`:** add your subcommand as a function plus one line in `HANDLERS`, and your
  arguments in your own `if name == "<cmd>":` block in `main`. Don't touch other blocks.
- **`kept/app/api.py`, `tests/app/test_api.py`:** only your own handlers and tests (K9).
- **Dependencies:** never hand-edit `uv.lock`. Change `pyproject.toml` in its own commit, run
  `uv lock`, and say so in the PR. On a lock conflict: `git checkout origin/main -- uv.lock && uv lock`.
- **Data never goes into git** (K4). Handover files go to the shared folder (§1a), named with the
  commit and date.
- **Commit messages:** one plain line. No AI co-author trailers.
- **Never commit to main directly.**

---

## 3. G0: the contract PR (sequential, now)

G0's exit checks (§6): `make test-contract` green on main ✓; the four providers importable ✓;
every §9 row has an answer or an owner and a deadline (this PR). **One PR, opened by Akshat (C),
branch `g0-contract`; each owner reviews their lines.** Merge it before anyone starts work that
reads `text.extractions`, the Ask table list or the new `Services` fields.

| Item | File (owner reviews) | Proposal |
|---|---|---|
| `text.extractions` shape (S4) | `dbt/models/text/sources.yml` (C; A + D review) | One row per `source_id`; each field as `_value`, `_quote`, `_char_start`, `_char_end`, `_confidence`; plus `extractor`, `extracted_at`, `confirmed_by_agent_id`. The two `_char_*` columns are extra to the plan so evidence round-trips |
| `text` schema | `kept/common/db.py` `SCHEMAS` (A), `dbt/dbt_project.yml` (D) | Add `"text"`; dbt block `text: +schema: text` |
| `Services` gains two optional fields | `kept/app/api.py` (D) | `steward: StewardQueue \| None = None` (A), `extractions: ExtractionStore \| None = None` (C) |
| Ask table list | `contracts/c360_customer.odcs.yaml` (B + A) | B's 8 silver tables: `collections_cases`, `promises_to_pay`, `agents`, `contact_history`, `account_monthly_snapshot`, `card_accounts`, `loan_accounts`, `deposit_accounts`, plus gold C360 |
| `TEXT_EVAL_SAMPLE_SIZE` | `kept/config.py` (C) | 500 (the public labels per source); the gate is checked on the 30% held out by `kept.text.labels.is_holdout` |
| Free LLMs (K6) | `.env.example` (B + C) | Two settings, one gateway each: `KEPT_TEXT_LLM_MODEL=ollama/gemma3:12b-it-qat` (local on C's GPU, ~1 s/call warm) and `KEPT_ASK_LLM_MODEL=<B picks: Gemini / Groq / OpenRouter free tier>` with its key name. Remove the Anthropic lines (paid) |
| `GoldenCustomer.hard_stop_flags` | the four golden-record copies (A; D asked) | Additive: `frozenset[HardStop]`, from `kept.data.gold.hard_stop_flags` |
| §9 TBCs | `docs/TEAM_PLAN.md` §9 | Answered: random assignment = `assignment_method='random'`; legacy codes (D); `text.extractions` (C); roll-rate metric (B). Owner + deadline for the rest: ground-truth IDs + PAD at other FIs (A, ask organisers, by G1); `paid_14d` source (D + A, by G2, D's proposal in Track_D.md); cash-flow thresholds (C + D, by G2); Ask LLM (B, in this PR) |

---

## 4. Next tasks per track, and where to stop

Do the tasks in order. "Stop" means: post the stop message (§5) in team chat and the PR, then
wait for Akshat to confirm the gate passed. **Don't start anything past your stop line.**

### Track A (Satvik): Phase 2 → stop at G1

1. Review the G0 PR (S4 shape, `SCHEMAS`, Ask table list, `hard_stop_flags`).
2. `kept/data/clean.py`: `normalize_name`, `name_match_key`, `parse_dob`, `normalize_phone_e164`,
   `normalize_postal_code`, quarantine. Tests: `tests/data/test_clean.py`.
3. `kept/data/traps.py`: `latest_snapshot`, `card_dpd`, `dpd_bucket`, `bureau_percentile`,
   `current_scd2_rows`, `coalesce_renamed`, `has_transaction_coverage`. Tests: `tests/data/test_traps.py`.
4. Silver dbt models, one per source table (K2: dictionary names; `channel_v2` → `channel`), bad
   rows to `quarantine.<table>`. Keep `account_monthly_snapshot` with full history (D needs it).
   Fix the agent-note mojibake (4,636 notes, e.g. `appel�`) here or list it for the quality report.
   Check: `dbt build --select silver`.
5. `kept/data/identity/{exact,probabilistic,clustering}.py`. Tests: `tests/data/test_identity.py`, `test_splink.py`.
6. Ask the organisers: ground-truth IDs? PAD/autopay at other FIs?
7. Sequential, once silver is real: tune Splink on a 10% sample, write crosswalk v0, **hand the
   settings to C** for the full run.

**Stop:** Phase 2 parallel tasks green → stop message for G1. Not before G1: gold models, `DuckDBC360Reader`.

### Track B (Abhishek): Phase 3 parallel against fakes → stop

Phases 1–2 are done; starting Phase 3 against fakes is approved (§6 lets the user allow it).

1. In the G0 PR: pick the free hosted Ask model (check today's free tiers and limits), fill
   `KEPT_ASK_LLM_MODEL` + key name in `.env.example`, confirm the Ask table list with A.
2. `kept/ask/lookup.py`: `generate_candidates`, `normalize_result`, `majority_result`.
3. `kept/ask/grounding.py`: `extract_numbers`, `is_grounded`, `needs_clarification`.
4. `kept/ask/service.py`: `CollectionsAsk.ask` (scope → route → answer → guard → grounding, audit
   per call). Tests: `tests/ask/test_service.py`.
5. `/ask` handler and `test_ask_returns_discriminated_response` (B's lines only in `api.py`; D made
   `/ask` a pass-through to `services.ask`).
6. Write down the refusal rule for hidden test questions and how the scorer treats "direction of
   effect" / "±1 CAD" tolerances (open questions in Track_B.md).

**Stop:** after these, stop. G1 work for B (point `SqlPolicy` at real silver, run the guard on 10 real
questions) waits for A's silver. Not before G3: the full benchmark run (Q9).

### Track C (Akshat): Phase 2 → stop at G1

1. Open and merge the G0 contract PR (§3).
2. `kept/text/extract.py`: `resolve_day_of_month`, `locate_quote`, `LLMExtractor.extract` (prompt v1,
   a quote for every value), `confirm`. Tests: `tests/text/test_extract_and_eval.py`.
3. After G0 merges: `text.extractions` writer + `dbt/models/text/`; new round-trip test.
4. Prompt runs on the public labels with the local model; iterate on the 70% tuning split until every
   feature has F1 ≥ 0.80 and hardship recall ≥ 0.90; final check on the 30% holdout only.
5. Heavy run (§1a, Q12): redact all 760,594 notes + 25,000 transcripts → `text.redacted_notes` Parquet
   in the shared folder; spot-check 20.
6. Heavy run when A hands the Splink settings: full match → crosswalk v1 back to A.

**Stop:** Phase 2 parallel tasks green → stop message for G1. Not before G1: SetFit training on LLM labels (Phase 3).

### Track D (Shreyas): support work → no real-data runs until G2

Every parallel task through Phase 5 is done. Until the gates catch up:

1. Review the G0 PR (`Services` fields, `dbt_project.yml` text block, `hard_stop_flags`).
2. `web/`: the extraction confirm/edit panel on the case card, calling C's
   `/extractions/{source_id}/confirm` (C builds the route in Phase 4; build the panel against the demo
   services now), and the hardship-programmes banner for C's `eligible_programs`.
3. README run instructions (deliverable 1): setup per track, `kept serve --demo`, `make web`.
4. Agree the `paid_14d` source with A (§9, by G2).
5. Hand Akshat the setup steps for running `web/` on his machine (demo runs there, Phase 6).

**Stop:** no `kept train`, `kept score`, real `kept serve` or `nightly` until G2/G3 (Q7, Q8). At G1: build
the dbt features against real silver and the stub gold.

---

## 5. Stop message (post in team chat and the PR)

> The parallelizable part of Phase N for Track X is done. We need to integrate it with the other
> tracks' work at gate GN before we can move on to implement it further.
>
> Finished: … (tests that pass, PR link)
> Gate GN needs from other tracks: … (copy from TEAM_PLAN §6)
> Open questions / test changes: …

G1 (§6): A has bronze + silver + crosswalk v1 in `kept.duckdb` on real data; B runs the guard on 10
real questions against real silver; C runs extraction on 50 real notes through the real redactor and
gateway; D builds the dbt features against real silver and the stub gold. Exit: `dbt build --select
bronze silver` passes; each track's Phase 1–2 tests green; no unredacted text in the audit log's LLM events.
