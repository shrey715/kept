# Team plan: who builds what, in what order, and where we have to sync

Source of truth for the design: `docs/SharpeShooters_SystemDesign.pdf`.
Source of truth for the data: `docs/CIBC Hackathon - Data Dictionary.xlsx`.
What the organisers want: `docs/collection hackathon.pdf` (challenge) and
`docs/CIBC Hackathon Build Phase - Instructions.pdf` (build rules, deliverables, deadline).
How the dataset is laid out: the release's own `README.md` (inside the downloaded zip).

**Fixed external times (IST), set by the organisers:**
- **4 Oct, 7:00 PM:** extra benchmark questions released (Q13).
- **4 Oct, 9:00 PM:** submission deadline. Commits after 9:00 PM don't count.

Four people, four tracks, six phases. We started late, so nothing here is tied to the clock:
a checkpoint happens when the code it needs is done, not at a set hour. Inside a phase each
track works alone and tests against the fakes in `tests/fakes.py`. Between phases there is an
**integration gate** (G0–G4): when the tracks a gate depends on have each finished their
parallel tasks, we stop and plug their real code into each other. Gates are the only times we
wait for each other, and the only times the plan is sequential on purpose.
§3 lists every part that can't run in parallel. The two times above are the only fixed points:
if they get close, use §11 to cut scope rather than skipping Phase 6.

---

## 0. Rules for AI coding agents (read this first)

If you are an AI agent (Claude Code or similar) working in this repo for a team member,
follow the **ponytail principles** in the repo's `CLAUDE.md` for every change. Claude Code
loads that file on its own; other agents must be pointed at it. Then:

1. Find out which track (A, B, C or D) and which phase (1 to 5) you're working on. If the
   user didn't say, ask them.
2. Do only the tasks marked **parallel** for that track and phase in §5. Use the fakes in
   `tests/fakes.py` for anything another track provides. Don't edit files another track owns
   (§1), and don't change anything under "shared" in §8 without the user's say-so.
   Follow the conventions in §3a (merge small and often, silver keeps source names, and so on).
3. **When something is ambiguous** (a column's meaning, a threshold, which table to use, what a
   deliverable needs), first look it up in the docs:
   `docs/SharpeShooters_SystemDesign.pdf` (our design), `docs/collection hackathon.pdf` (challenge
   brief), `docs/CIBC Hackathon Build Phase - Instructions.pdf` (build rules, deliverables, deadline),
   `docs/CIBC Hackathon - Data Dictionary.xlsx`, the dataset release's `README.md`, and this plan. Then ask the user, and tell
   them what the docs say, quoting the file and section, so they can make an informed decision.
   If the docs say nothing, say that too.
4. A task marked **sequential** or **gate** needs another track's real output or a team
   decision. Don't start it on your own. If a parallel task turns out to need one, stop and
   tell the user which one and who it's waiting on.
5. When every parallel task for the phase is done (its listed tests pass, `make test-contract`
   is green, `make lint` is clean), **stop and tell the user, in these words:**

   > The parallelizable part of Phase N for Track X is done. We need to integrate it with
   > the other tracks' work at gate GN before we can move on to implement it further.

   Then list: what you finished (with the tests that now pass), what gate GN needs from the
   other tracks (copy it from §6), and any open questions or test changes you made.
   Don't start the next phase until the user confirms the gate has passed.
6. If you are Track C's agent, use the machine's GPU (RTX 5070 Ti) for anything that can run on
   it: SetFit training and inference, Whisper, embeddings, and the heavy runs in §1a. Check
   `torch.cuda.is_available()` first and say so if it's False rather than silently falling back to CPU.
7. Keep your person's track file, `docs/tracks/Track_<X>.md`, up to date (format in `CLAUDE.md`).
   Create it once the user has said which track they're on, and only for that track. It's a
   status file for people to read; instructions come through the prompt, so don't re-read it.
8. Never use a paid LLM API or key. Only the free options in §1b.
9. **Big downloads and long jobs need the user's go-ahead.** Before pulling a model (Ollama
   models, SetFit/sentence-transformers bases, Whisper, spaCy), installing a large extra, or
   starting a run that takes a long time or a lot of disk, first check what's already on the
   machine (`ollama list`, `~/.cache/huggingface`, installed packages, free disk space) and ask the
   user which option to use, with the size and time of each. The dataset is the exception:
   download it on every machine without asking (Q1).
10. When the user says a sequential part, an integration or a gate is done, check it before moving
   on, cheaply: make sure the branch is pulled and up to date with `origin/main`; then, for that
   item in §3/§5/§6, confirm the listed files and functions exist and are no longer stubs (grep for
   `NotImplementedError`, `make progress`), and that its exit checks in §6 hold. Skim signatures and
   diffs, don't read whole files. Report what's there and what's missing in a few lines, then carry on.

---

## 1. Tracks and ownership

| Track | Person | Design column | Owns (code) | Owns (tests) | Extra |
|---|---|---|---|---|---|
| **A: Data and IDs** | Satvik Rao | Layer 1 + parity test | `kept/data/**`, `kept/common/db.py`, `kept/contracts/data_contract.py`, `kept/features/parity.py`, `dbt/models/{bronze,silver,gold}`, `soda/`, `contracts/*.yaml`, `/steward` routes, new `kept/data/c360_reader.py` | `tests/data`, `tests/features/test_parity.py` | `make setup-a` |
| **B: Ask** | Garimella Sai Abhishek | Layer 2 + fairness | `kept/ask/**`, `kept/common/llm.py` (LLM gateway), `/ask` route, `kept/governance/{lineage,fairness}.py` | `tests/ask`, `tests/common/test_llm_gateway.py`, `tests/governance/test_lineage_and_fairness.py` | `make setup-b`; run the fairness tests with `uv run --with "fairlearn>=0.11" pytest ...` (Fairlearn sits in the `text` extra, which pulls torch, and `uv sync` would remove a separately installed copy) |
| **C: Text features + compute** | Akshat Srivastava | Layer 3 text + every heavy run (§1a) | `kept/text/**`, `kept/hardship/**`, `/extractions` route, new `dbt/models/text/` | `tests/text`, `tests/hardship` | `make setup-all`, then `uv run python -m spacy download en_core_web_lg` (Presidio needs it; `setup-all` doesn't fetch it) |
| **D: Model and UI** | Shreyas Deb | Layer 3 SQL features + Layer 4 + app | `kept/features/{definitions,store}.py`, `feature_repo/`, `dbt/models/features`, `kept/nba/**`, `kept/app/**`, `kept/common/audit.py`, `kept/governance/access.py`, new `kept/nba/context.py`, `kept/cli.py` | `tests/features`, `tests/nba`, `tests/app`, `tests/common/test_audit.py`, `tests/governance/test_access.py` | `make setup-d` |

Load (tests to turn green): A ≈ 95, B ≈ 72, C ≈ 43 plus every heavy run (§1a), D ≈ 125.
D is the heaviest, so A, B and C pick up the non-code deliverables (§2), and A takes
`kept/features/` from D at G2 if D is behind. C has the least code because C's machine runs
the heavy jobs for every track. Those runs are mostly waiting time, and C codes while they run.

## 1a. Compute: heavy jobs run on C's machine

C's machine has an RTX 5070 Ti, so every heavy job runs there. Nobody waits on it: the other
tracks keep working on their own phase tasks with fakes or a sample until the output lands.
The track that owns a job writes and tests its code on their own laptop on a small sample, then
hands the settings to C for the full run.

| Job | Code owner | Full run | Until it lands, others use | Handed back as |
|---|---|---|---|---|
| Splink match on all of real silver (about 1M CRM records + account keys) | A (tunes on a 10% sample) | C, CPU | A's crosswalk v0 from the sample | `identity_crosswalk` Parquet + the trained Splink model JSON |
| Presidio redaction of about 1.5M agent notes and 25K transcripts | C | C, parallel CPU processes | `PassThroughRedactor` and fixture notes | `text.redacted_notes` Parquet |
| SetFit training and backfill over the redacted notes | C | C, GPU | `PurposeLLM`, fixture extractions | `text.extractions` Parquet |
| Bulk LLM work on the local model (§1b): prompt tuning runs on the public labels, ~3k LLM labels | C | C, GPU (Ollama) | `PurposeLLM` | `data/labels/` files |
| Whisper on 2,000 voice recordings | C | C, GPU | nothing (voice is optional) | `text.transcripts` Parquet |
| Anything else that takes more than about 15 minutes on a laptop (e.g. a full uplift retrain with SHAP) | the track that owns it | C | that track's sample run | Parquet, or a model in MLflow |

How handovers work: data never goes into git. C puts outputs in a shared folder (a team
Drive folder), and the receiver copies them into `data/exports/<name>/`. Every output's
filename says which code commit and settings produced it.

Order of runs (Q12): one GPU job and one big CPU job can run at the same time; two of the same
kind queue. When two are ready at once, the one on the critical path (§3) goes first: the Splink
match, then the note redaction, then SetFit, then Whisper.

## 1b. LLMs: free only

We don't use any paid API key. LiteLLM (`kept.common.llm`) lets us swap models by changing a
model string, so the code doesn't change; only `.env` does.

| Use | Where it runs | Why |
|---|---|---|
| Text extraction: prompt tuning on the public labels, bulk LLM labels for SetFit, live extraction in the demo | a local model on C's GPU, served by Ollama (`ollama/<model>`) | the heaviest LLM use; local means no rate limits and no cost |
| Collections Ask: scope, route, lookup SQL, narration, benchmark runs | a free hosted tier through LiteLLM, each person on their own free key | few calls per question, and every laptop needs it; per-person keys mean we don't share one quota |
| Policy search embeddings (LanceDB) | a small local sentence-transformers model | the policy documents are small; CPU is fine |

Which exact models: decided at G0 (§9). Check the current free tiers and their rate limits on the
day; don't assume. Candidates to compare: Google Gemini's free tier, Groq's free tier,
OpenRouter's free models, and for local, whatever fits the 5070 Ti's 16 GB (an 8B–14B instruct model).

Living with free limits:
- The gateway (B) retries on rate-limit errors with backoff, and gives up cleanly (the Ask
  returns a refusal or clarification, never a crash).
- Lookups ask for `SQL_CANDIDATES = 3` SQL drafts per question. If rate limits bite, dropping to
  1 is a team decision (it's a `kept.config` value).
- The 7:00 PM benchmark rerun (Q13) must fit inside the free quota: B measures how many calls one
  full run takes once the Ask works, and keeps a spare key ready.
- If the local model can't pass the extraction F1 gate, C trains SetFit directly on the public
  labels (minus the held-out set) instead of on LLM labels.
- The live demo's extraction runs on C's machine, which is where Phase 6 runs anyway.

## 2. Deliverables (from the brief) and who owns them

All seven submissions come from the build-phase instructions. Everything except the video and
deck goes in the repo.

| # | Deliverable | Owner | Done at |
|---|---|---|---|
| 1 | Code repository: private GitHub repo, organisers added as collaborators, commits from all four of us throughout (team work is 15%). README covers how to run it, **what changed from the design and why**, and **which AI tools we used and for what** | everyone; D owns the run instructions, `kept serve` and `kept nightly`; each owner adds their own "what changed" and "AI tools" lines | G4, README final in Phase 6 |
| 2 | Architecture diagram, final, as PDF or PNG in the repo | C | Phase 6 |
| 3 | Data contract (`contracts/c360_customer.odcs.yaml`): owner, schema, quality rules, allowed uses, refresh. Check it against the example contract DC-COLL-001 in the release's `files/docs/data_contracts/` | A | G2, frozen at G3 |
| 4 | Data quality report (`docs/quality_report.md`): each issue found, how many records it affected, how we handled it | A | G3 |
| 5 | Benchmark answers CSV in the release's answers template (`question_id`, `answer`, `sql_or_sources`, `refused`) for every released question plus the extra ones (Q13). Generated by `kept benchmark`, never edited by hand | B | after 4 Oct 7:00 PM |
| 6 | Demo video, up to 5 minutes, on real data, unlisted YouTube or Drive link | A writes the script in Phase 5 and records it once the demo works | Phase 6 |
| 7 | Pitch deck, up to 10 slides, PDF | C writes it in Phase 5; each owner drafts their track's slide | Phase 6 |
| — | Fairness report (Fairlearn on real recommendations) and lineage CI check (not submitted separately; it backs the "no protected attributes" claim) | B | G4 |

Judges also ask unseen Ask questions live, so the Ask has to work on questions outside the benchmark.

---

## 3. What can't be parallelized

These parts are sequential. Plan around them and don't let an agent start them alone.

| # | What | Why it's sequential | Who | Checkpoint |
|---|---|---|---|---|
| Q1 | **Kickoff**: names in §1; download the dataset (below) and put the 31 tables in `data/raw/`; read the release `README.md` (file conventions, loading code, each system's customer key); `make setup` + `make setup-x`, `make test-contract` green on every laptop, agree the branch rules (one branch per track, PR to main, CI green) | nothing works without the data and a green baseline | all | before anything else |
| Q2 | **Early providers** that the other tracks call: `load_data_contract` (A), `LiteLLMGateway` (B), `PresidioRedactor` (C), `DuckDBAuditLog` (D) | the others code against fakes until then, but can't run on real inputs without them | each owner, first task | merged before G0 |
| Q3 | **Contract decisions** (G0): the `text.extractions` table, the Ask table list, the Day-1 TBCs in §9 | changing a shared shape later breaks other tracks' work | all | G0 |
| Q4 | **Data chain on real data**: raw → bronze → silver → exact links + Splink → crosswalk → gold C360 → dbt features → Feast materialise → labels → train uplift → score | each step reads the previous step's real tables. Code for every step can be written in parallel against fixtures; *running* it on real data can't | A then D | G1 → G3 |
| Q5 | **Text chain**: the release's 500 public labels (notes, and 500 for transcripts) → extraction prompt passes the F1 gate on them → LLM labels → SetFit → backfill historical notes → hardship and text features reach gold and features | each step needs the last step's output | C | Phase 1 → G2 |
| Q6 | **Hardship into the golden record**: `gold.c360_customer.hardship_status` = `hardship.combine` over agent/account/LLM/cash-flow observations | needs C's extractions table and A's gold build at the same time | A + C | G2 |
| Q7 | **Uplift training** | needs real features (D), real `paid_14d` labels (D + A), and the random-assignment TBC | D | after G2 |
| Q8 | **Wiring the real services**: `CaseContextBuilder` over the real C360 reader + Feast, `KeptEngine` with the real scorer, `create_app(Services(...))`, `kept nightly` | it needs every track's real implementation | D, with each owner present | G3, G4 |
| Q9 | **Final scoring runs**: full Ask benchmark on real gold, parity on real offline vs online, fairness on real recommendations | needs the integrated system | B, A | after G3 |
| Q10 | **Demo, video, deck** | the demo has to work end to end before we record it | all | Phase 6, after G4 |
| Q11 | **Breaking contract changes** | one at a time: agree in chat, bump `CONTRACT_VERSION`, update fakes in the same PR | whoever needs it | any time, serialised |
| Q12 | **Heavy runs on C's machine** (§1a) | one machine and one GPU, so runs queue; the full crosswalk and the backfilled extractions feed gold, so gold on real data waits for them | C | crosswalk before G1 closes; backfill before G2 closes |
| Q13 | **Extra benchmark questions** (4 Oct, 7:00 PM IST): run `kept benchmark` on them as the system is, write the answers CSV, commit before 9:00 PM. The Ask must be in its final state by then | the questions don't exist until 7:00 PM | B | 4 Oct, 7:00–9:00 PM |

Getting the data (Q1), from the build-phase instructions. Needs about 10 GB free; the voice zip
adds 6 GB and only C's machine needs it.

```bash
pip install -U huggingface_hub
hf download nuxsh/maple-collections-hackathon --repo-type dataset --local-dir maple_data
cd maple_data && unzip maple_collections_release.zip    # C also: unzip maple_collections_voice.zip
```

Read `maple_collections_release/README.md` first, then copy the tables into `data/raw/` as
`data/README.md` describes. The release also carries the policy documents (→ `data/policy/`),
the benchmark questions and answers template (→ `data/benchmark/`) and the public labels (→ `data/labels/`).

Critical path (the longest chain; slip here and the demo slips):

```
Q1 ─▶ A: land + contract ─▶ A: silver + IDs ─G1─▶ A: gold C360 ─G2─▶ D: features on real gold
     ─▶ D: Feast + train uplift ─G3─▶ D: engine on real providers ─G4─▶ demo ─▶ video
```

The text chain (Q5) runs alongside it and must reach gold by G2, or the "a new note flips
hardship" moment in the demo has nothing to flip.

---

## 3a. Conventions every track relies on (so nobody drifts)

The fakes stop tracks from waiting on each other. These rules stop them from building
different versions of the same thing. They are fixed; changing one is a G-level team decision.

| # | Convention | Why it matters |
|---|---|---|
| K1 | **Merge small and often.** Open a PR to main as soon as a task's tests go green (CI must pass), and pull main before starting each task. Gates are for running on real data together, not the first time code meets main | four branches that only meet at gates will conflict and drift |
| K2 | **Silver keeps source names.** Each cleaned table is `silver.<source_table>`, with the data dictionary's column names unchanged. New derived columns get new names; a renamed source column is coalesced back to the dictionary name (`channel_v2` → `channel`). Gold is exactly the contract | B's Ask SQL, D's dbt features and the feature registry all read silver by dictionary names |
| K3 | **One raw layout.** At kickoff, A reads the release `README.md` and writes down in `data/README.md` exactly how the release files go into `data/raw/`; everyone copies them the same way | otherwise `kept land` works on one laptop and not another |
| K4 | **Everyone builds their own warehouse** from main plus the Parquet files handed over from C's machine (§1a). Never copy a `.duckdb` file between machines. Handover file names carry the commit and date | two people looking at different data will "fix" different bugs |
| K5 | **DuckDB allows one writer.** Open a connection per job or request and close it; don't hold `kept.duckdb` open. Don't run batch jobs against the warehouse the API is serving from. The audit log is its own file (`audit.duckdb`) | the live demo (API serving while a new note is extracted) fails on a lock otherwise |
| K6 | **One free LLM per use, the same for everyone** (§1b): one hosted free model for the Ask, one local model for text extraction, both set in `.env`. No paid keys. Changing either is a team decision: the Ask benchmark and the extraction F1 gate are tuned on them | a prompt that passes on one model can fail on another |
| K7 | **Times and money:** store UTC, timezone-aware; convert to customer-local only for calling hours. Money is `Decimal`, rounded to cents (`kept.config.CENT`). The contracts already enforce this; don't work around them | off-by-one-day promise dates and float cents |
| K8 | **Gold SQL shape (A):** `tests/contracts` reads each gold model's columns from lines ending `as <column>`. Keep each gold model's final `select` to exactly the contract columns, one per line, and put intermediate logic in separate models (e.g. `silver.int_*`) | otherwise the real gold model fails the contract suite, which must stay green |
| K9 | **Each track edits only its own parts of shared entry points**, in small PRs: its handlers in `kept/app/api.py`, its tests in `tests/app/test_api.py`, and its own subcommands in `kept/cli.py` (A: `land`, `build`, `match`, `gate`, `parity`; B: `benchmark`; C: `extract`; D: `features`, `train`, `score`, `serve`, `nightly`) | four tracks share these files, and nobody should wait on someone else to wire a command |

## 4. Gaps in the skeleton: interfaces with no real implementation yet

The skeleton has fakes for these but no real class. Each now has an owner.

| # | What's missing | Owner | Where | Phase |
|---|---|---|---|---|
| S1 | `DataContract` loader (stubbed, but every track needs it) | A | `kept/contracts/data_contract.py` | 1, first task |
| S2 | A DuckDB-backed `C360Reader` (only `DictC360Reader` exists) | A | new `kept/data/c360_reader.py` + `tests/data/test_c360_reader.py` | 3 |
| S3 | A real `CaseContextBuilder` (only `FixedContextBuilder` exists). It reads C360 + online features and fills `CaseContext` | D | new `kept/nba/context.py` + `tests/nba/test_context.py` | 3 |
| S4 | Somewhere to store extractions. Nothing writes `TextExtraction` rows or reads them back | C (shape agreed at G0) | `text.extractions` table in `kept.duckdb`, one row per `source_id`, columns = `TextExtraction` flattened (`<field>_value`, `<field>_quote`, `<field>_confidence`), plus `extractor`, `extracted_at`, `confirmed_by_agent_id`. dbt source in new `dbt/models/text/` | 2 |
| S5 | The LLM scope `Classifier` (a `Callable[[str], ScopeDecision]`) | B | `kept/ask/scope.py`, via `Purpose.ASK_SCOPE` | 2 |
| S6 | Every `kept` CLI command | each owner adds their own subcommand when its function works (K9); D owns `nightly` and `serve`, which call the others | `kept/cli.py` | as each step lands; `nightly` in 5 |
| S7 | Something to show on screen: the API returns JSON only | D | one static HTML page served by FastAPI that renders the NBA card, plus the Ask box (B) and the steward queue (A). No frontend framework | 5 |

---

## 5. Phase-by-phase plan

A phase has no fixed length: it ends for a track when that track's parallel tasks are done,
and it ends for the team at the gate (§6). "Tests" are what must pass for the task to count
as done (`uv run pytest <path>`). Within a phase, do the tasks in the order listed.

### Phase 0: kickoff. Sequential, everyone (Q1)

Write your name in §1. Download the dataset (§3, Q1). A reads the release `README.md` and writes
the `data/raw/` layout into `data/README.md` (K3); everyone then copies the files the same way.
Run `make setup && make setup-<track> && make test-contract && make progress`. Read §3, §3a and §9.

### Phase 1: foundations → G0

**A: Data and IDs**
| Task | Mode | Files | Tests |
|---|---|---|---|
| Contract loader: `load_data_contract`, `table_columns`, `columns_with`, `ask_blocked_columns`. **Merge this first; B, C and D need it** | parallel, early provider (Q2) | `kept/contracts/data_contract.py` | `tests/contracts`, `tests/data/test_contract_and_ingest.py` |
| `connect`, `land_file`, `land_directory` (CSV, Parquet by year, JSON; WAV listed only) | parallel | `kept/common/db.py`, `kept/data/ingest.py` | `tests/data/test_contract_and_ingest.py` |
| Land every raw table into bronze and add the `kept land` subcommand (K9): it should leave 31 bronze tables in `data/warehouse/kept.duckdb` | parallel | `dbt/models/bronze/sources.yml` | row counts match the dictionary's approx. rows |
| Read the release `README.md` (customer key per source system); check our contract against the example DC-COLL-001 | parallel | `contracts/c360_customer.odcs.yaml` | `tests/contracts` |
| Ask the organisers (doubts channel) whether ground-truth IDs exist. Decide on autopay/PAD accounts at other FIs | parallel (TBC) | §9 | — |

**B: Ask**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `LiteLLMGateway.complete`: redacted input only, JSON-schema validation, one audit event per call, retry with backoff on rate-limit errors (§1b). **Merge before G0: everyone's LLM calls go through it** | parallel, early provider (Q2) | `kept/common/llm.py` | `tests/common/test_llm_gateway.py` |
| `load_metric_definitions`, `compile_metric`; certified SQL for each metric, roll rate first | parallel | `kept/ask/metrics.py` | `tests/ask/test_pipeline_parts.py` (metrics) |
| `load_benchmark`, `parse_tolerance`, `score` | parallel | `kept/ask/benchmark.py` | `tests/ask/test_pipeline_parts.py` (benchmark) |
| Write `kept benchmark`'s output in the release's answers template (`question_id`, `answer`, `sql_or_sources`, `refused`); see the release README's "Benchmark questions" section and the dev answers file | parallel | `kept/ask/benchmark.py` | a CSV that matches the template's columns |

**C: Text features**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `PresidioRedactor.redact`. **Merge before G0: A and B pass text through it before any LLM call** | parallel, early provider (Q2) | `kept/text/redact.py` | `tests/text/test_redact.py` |
| Load the release's 500 public note labels and 500 transcript labels into `data/labels/`; map their columns to our `TextExtraction` fields | parallel | `data/labels/` | every label column maps to a field, or is listed as unused |
| `binary_metrics`, `text_feature_gate`, `cohens_kappa`, `adjudicate` | parallel | `kept/text/evaluate.py` | `tests/text/test_extract_and_eval.py` (eval) |
| Draft the `text.extractions` shape (S4) for G0 | parallel | PR description | — |
| Set up the compute machine: `make setup-all`, check `torch.cuda.is_available()`, install Ollama and pick a local model (§1b): check what's already there with `ollama list`, then ask before pulling one (rule 9), create the shared handover folder (§1a) | parallel | — | a 1-minute SetFit smoke run on the GPU; one LiteLLM call to the local model |

**D: Model and UI**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `DuckDBAuditLog` (append-only, duplicate id → `ValueError`), `new_event_id`. **Merge before G0: everyone logs** | parallel, early provider (Q2) | `kept/common/audit.py` | `tests/common/test_audit.py` |
| `paid_within`, `rolled_forward`, `roll_forward_rate` | parallel | `kept/nba/labels.py` | `tests/nba/test_uplift_explain_labels.py` (labels) |
| `hard_stops`, `permission_gate`, `allowed_actions`, `hardship_override` | parallel | `kept/nba/rules.py` | `tests/nba/test_rules.py` |
| Access and masking: `can_view_case`, `can_read_restricted`, `mask_*`, `masked_view`, `can_release` | parallel | `kept/governance/access.py` | `tests/governance/test_access.py` |
| `/health` route | parallel | `kept/app/api.py` | `tests/app/test_api.py::test_health` |

**Agents: stop here and report (rule 5, gate G0).**

### Phase 2: cleaning, IDs, Ask guard rails, extraction, rules → G1

**A**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `normalize_name`, `name_match_key`, `parse_dob`, `normalize_phone_e164`, `normalize_postal_code`, quarantine records | parallel | `kept/data/clean.py` | `tests/data/test_clean.py` |
| `latest_snapshot`, `card_dpd`, `dpd_bucket`, `bureau_percentile`, `current_scd2_rows`, `coalesce_renamed`, `has_transaction_coverage` | parallel | `kept/data/traps.py` | `tests/data/test_traps.py` |
| One silver dbt model per source table using the rules above; bad rows to `quarantine.<table>` | parallel | `dbt/models/silver/` | `dbt build --select silver` |
| `exact_link_pairs`; Splink `build_settings`, `score_pairs`; `route_score`, `decide`, `connected_components`, `cluster_review_reasons`, `GoldenIdRegistry` | parallel | `kept/data/identity/{exact,probabilistic,clustering}.py` | `tests/data/test_identity.py`, `tests/data/test_splink.py` |
| Tune Splink on a 10% sample of real silver and write crosswalk v0. Hand the settings to C for the full run (§1a) | sequential: needs real silver (Q4) | — | precision on a quick 50-pair eyeball |

**B**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `rule_check`, `check_scope`, `refusal_for`; the LLM classifier (S5) | parallel | `kept/ask/scope.py` | `tests/ask/test_pipeline_parts.py` (scope) |
| `route` (LLM → JSON intent with metric, filters, dates) | parallel | `kept/ask/router.py` | `tests/ask/test_pipeline_parts.py` (router) |
| `guard_sql` (SELECT only, approved tables, no blocked columns, row limit), `execute_guarded` (timeout) | parallel | `kept/ask/sql_guard.py` | `tests/ask/test_sql_guard.py` |
| `suppress_small_groups` | parallel | `kept/ask/privacy.py` | `tests/ask/test_pipeline_parts.py` (privacy) |

**C**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `resolve_day_of_month`, `locate_quote`, `LLMExtractor.extract` (prompt v1, evidence quote for every value), `confirm` | parallel | `kept/text/extract.py` | `tests/text/test_extract_and_eval.py` (extract) |
| Run the prompt on the 500 public note labels (and transcript labels). Iterate until every text feature has F1 ≥ 0.80 and hardship recall ≥ 0.90. Hold out some labels for the final check so we don't tune on the test set | sequential: needs the labels loaded | — | `text_feature_gate` passes per feature on the held-out labels |
| Create `text.extractions` (S4) and a writer for it | parallel, after G0 | `kept/text/extract.py`, `dbt/models/text/` | new test: round-trip one `TextExtraction` |
| Redact all notes and transcripts on the compute machine → `text.redacted_notes` | sequential: needs the redactor merged (Q12) | — | row count = notes + transcripts; spot-check 20 for leaked PII |
| Full Splink run with A's settings → crosswalk v1 back to A | sequential: needs A's settings (Q12) | — | A signs off on the cluster counts |

**D**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `broken_promises_90d`, `kept_promise_ratio`, `days_to_next_payroll`, `contacts_last_7d`, `answer_rate`, `cohort_rate` | parallel | `kept/features/definitions.py` | `tests/features/test_definitions_and_store.py` |
| dbt feature models matching those definitions. Build them against a small fixture C360 until G2 | parallel | `dbt/models/features/` | `dbt build --select features` on the fixture |
| `drop_denied`, `assert_no_denied` | parallel | `kept/features/store.py` | `tests/features/test_definitions_and_store.py` |
| `legacy_to_action`, `treatment_to_action` (needs the code-list TBC) | parallel | `kept/nba/legacy.py` | `tests/nba/test_legacy.py` |
| `assign_tier`; `in_holdout`, `is_stale`, `sample_for_batch_review` | parallel | `kept/nba/tiers.py`, `kept/nba/release.py` | `tests/nba/test_sizing_ranking_tiers.py` (tiers), `tests/nba/test_release.py` (helpers) |

**Agents: stop here and report (rule 5, gate G1).**

### Phase 3: gold C360, answer card, backfill, Feast and uplift → G2

**A**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `merge_contact_permissions`, `derive_contact_flags`, `hard_stop_flags` | parallel | `kept/data/gold.py` | `tests/data/test_gold_and_quality.py` (gold) |
| Gold SQL: `c360_customer`, `identity_crosswalk`, `c360_restricted`; `build_gold`, `export_parquet`. Leave `hardship_status` = agent/account sources only until G2 | parallel | `dbt/models/gold/*.sql`, `kept/data/gold.py` | `dbt build --select gold`, `tests/contracts` |
| Every `check_*`, `generate_soda_checks`, `quality_report`, `run_gate` | parallel | `kept/data/quality.py`, `soda/checks/` | `tests/data/test_gold_and_quality.py` (quality) |
| `DuckDBC360Reader` (S2) over `gold.c360_customer` + `gold.identity_crosswalk` | parallel | new `kept/data/c360_reader.py` | new `tests/data/test_c360_reader.py`; must pass the same checks as `DictC360Reader` in `tests/contracts/test_fakes_conform.py` |

**B**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `generate_candidates`, `normalize_result`, `majority_result` | parallel | `kept/ask/lookup.py` | `tests/ask/test_pipeline_parts.py` (lookup) |
| `extract_numbers`, `is_grounded`, `needs_clarification` | parallel | `kept/ask/grounding.py` | `tests/ask/test_pipeline_parts.py` (grounding) |
| `CollectionsAsk.ask`: scope → route → answer → guard → grounding, audit per call | parallel | `kept/ask/service.py` | `tests/ask/test_service.py` |
| `/ask` route | parallel | `kept/app/api.py` (B's handler only) | `tests/app/test_api.py::test_ask_returns_discriminated_response` |

**C**
| Task | Mode | Files | Tests |
|---|---|---|---|
| LLM labels on ~3k notes with the prompt that passed the gate | sequential: needs the gate pass (Q5) | `data/labels/` | — |
| `SetFitBackfill` fit/predict/save/load; train on the GPU; must also pass the F1 gate on the held-out public labels | parallel (code), sequential (training) | `kept/text/backfill.py` | `tests/text/test_backfill.py` |
| Backfill all redacted notes into `text.extractions` on the GPU with `extractor="setfit:..."`, then hand over (§1a) | sequential: needs the trained model and the redacted notes (Q12) | — | row count = notes count |
| `combine`; `cash_flow_hardship`, `new_ei_deposit`, `is_ei_deposit` | parallel | `kept/hardship/{combine,cashflow_rule}.py` | `tests/hardship/test_hardship.py` |

**D**
| Task | Mode | Files | Tests |
|---|---|---|---|
| Feast FeatureViews over `data/exports/features/*.parquet`; `FeastFeatureProvider.get_online`, `get_historical` | parallel (on fixture parquet) | `feature_repo/features.py`, `kept/features/store.py` | `tests/features/test_definitions_and_store.py` (store) |
| `TLearnerUplift` fit/predict/uplift, `qini_curve`, `qini_coefficient` (on synthetic data) | parallel | `kept/nba/uplift.py` | `tests/nba/test_uplift_explain_labels.py` (uplift) |
| `CaseContextBuilder` (S3) against `DictC360Reader` + `StaticFeatureProvider` | parallel | new `kept/nba/context.py` | new `tests/nba/test_context.py` |

**Agents: stop here and report (rule 5, gate G2).**

### Phase 4: steward, policy search, live extraction, sizing, ranking, SHAP → G3

**A**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `StewardQueue` (enqueue, pending, resolve), `precision` | parallel | `kept/data/identity/steward.py` | `tests/data/test_identity.py` (steward) |
| `/steward/queue`, `/steward/items/{item_id}` | parallel | `kept/app/api.py` (A's handlers only) | none yet: add route tests to `tests/app/test_api.py` |
| Review the 300-pair sample; target 98% precision | parallel (human work) | `data/labels/match_pairs.csv` | `check_review_precision` |
| `draft_mapping` (LLM drafts source-to-target mappings, engineer approves) | parallel, cut first if behind | `kept/data/mapping_assistant.py` | none yet: add one small test |
| If D handed over `kept/features/` at G2: finish dbt features + Feast on real gold | parallel | `kept/features/`, `feature_repo/` | `tests/features` |

**B**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `effective_windows`, `chunk_document`, `PolicyIndex` (LanceDB, cites the section, current documents only) | parallel | `kept/ask/policy.py` | `tests/ask/test_policy_index.py` |
| Build the index from `data/policy/` | parallel | — | 5 policy questions answered with citations |
| Run the benchmark subset on real gold and fix the failures | sequential: needs G2 (Q9) | — | scorecard committed to `docs/` |

**C**
| Task | Mode | Files | Tests |
|---|---|---|---|
| Live extraction: `kept extract` on new notes → `text.extractions` → hardship observation | parallel | `kept/text/`, `kept/hardship/` | new note → row in `text.extractions` in seconds |
| `/extractions/{source_id}/confirm` (agent confirms or edits) | parallel | `kept/app/api.py` (C's handler only) | none yet: add a route test to `tests/app/test_api.py` |
| `eligible_programs` | parallel | `kept/hardship/programs.py` | `tests/hardship/test_programs.py` |
| `transcribe` (Whisper), then run it on all 2,000 recordings on the GPU → `text.transcripts`. Voice is still second on the cut list | parallel (code), sequential (run, Q12) | `kept/text/transcribe.py` | integration test |
| Heavy runs other tracks hand over (§1a), e.g. D's full uplift retrain | sequential (Q12) | — | output handed back |

**D**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `promise_due_date`, `size_promise`, `sizing_text` | parallel | `kept/nba/sizing.py` | `tests/nba/test_sizing_ranking_tiers.py` (sizing) |
| `score_actions`, `allocate_capacity`, `is_close_call` | parallel | `kept/nba/ranking.py` | `tests/nba/test_sizing_ranking_tiers.py` (ranking) |
| `top_reasons` (TreeSHAP), fill `REASON_TEMPLATES`, `similar_cases_text` | parallel | `kept/nba/explain.py` | `tests/nba/test_uplift_explain_labels.py` (explain) |
| `KeptEngine.recommend` (stages 1–7) against fakes | parallel | `kept/nba/engine.py` | `tests/nba/test_engine.py` |
| Train uplift v1 on real features and labels, log to MLflow, Qini on the hold-out | sequential: needs G2 (Q7) | — | Qini > 0 against the legacy baseline |

**Agents: stop here and report (rule 5, gate G3).**

### Phase 5: parity, full benchmark, fairness, release gate, app → G4

**A**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `parity_report` | parallel | `kept/features/parity.py` | `tests/features/test_parity.py` |
| Run parity on real offline vs online features | sequential: needs G3 (Q9) | — | mismatch ≤ 0.1% |
| `build`, `match`, `gate`, `parity` subcommands (K9), if not added already | parallel | `kept/cli.py`, `kept/data/` | each runs on real data |
| Commit the data quality report | parallel | `docs/quality_report.md` | — |
| Video script: the demo scenario in §7, 5 minutes | parallel | `docs/demo_script.md` | — |

**B**
| Task | Mode | Files | Tests |
|---|---|---|---|
| Full benchmark run; tune prompts until accuracy ≥ 80% and refusal recall ≥ 95%. Rerun on every prompt change | sequential: needs G3 (Q9) | — | scorecard in `docs/` |
| `benchmark` subcommand (K9), writing the answers CSV | parallel | `kept/cli.py`, `kept/ask/benchmark.py` | — |
| `lineage_violations` + CI check (no feature from a protected attribute or proxy). Add `pytestmark = pytest.mark.track_b` to the test file: the `governance/` folder defaults to `track_c`, so `make test-b` misses it otherwise | parallel | `kept/governance/lineage.py` | `tests/governance/test_lineage_and_fairness.py` |
| `recommendation_rates` (Fairlearn) on real recommendations | parallel (code), sequential (real run, Q9) | `kept/governance/fairness.py` | same file |

**C**
| Task | Mode | Files | Tests |
|---|---|---|---|
| Full-data reruns for the nightly: redact and backfill new notes, Splink on changed rows | sequential (Q12) | — | outputs handed over before G4 |
| `extract` subcommand (K9), if not added in Phase 4 | parallel | `kept/cli.py`, `kept/text/` | — |
| Deck draft (10 slides); ask each owner for their slide | parallel | `docs/` | — |

**D**
| Task | Mode | Files | Tests |
|---|---|---|---|
| `Releaser.release`, `cancel_pending` | parallel | `kept/nba/release.py` | `tests/nba/test_release.py` |
| `/cases/{case_id}/nba`, `/proposals/{proposal_id}/decision` | parallel | `kept/app/api.py` | `tests/app/test_api.py` |
| NBA card page (S7) with Ask box and steward queue | parallel | `kept/app/` | renders the fixture card |
| `kept nightly` (calls every track's subcommand in order) and `kept serve` with real `Services` (S6) | sequential: needs every track's subcommands (Q8) | `kept/cli.py` | `uv run kept nightly` and `uv run kept serve` run |

**Agents: stop here and report (rule 5, gate G4).**

### Phase 6: demo, video, deck. Sequential, everyone (Q10)

Each step starts when the one before it is done, except step 4, which happens at 7:00 PM wherever the others are.

1. Run `kept nightly` from a clean warehouse on C's machine (it has every extra installed), then the demo scenario (§7) twice. Fix only demo blockers.
2. Record the video on real data (A drives, others on standby for fixes).
3. Finish the deck as PDF and the architecture diagram as PDF/PNG in the repo (C). README (D, with everyone's lines): how to run, what changed from the design and why, AI tools used.
4. At 7:00 PM, when the extra questions are out: B runs `kept benchmark` on the full set and commits the answers CSV (Q13). No code changes to the Ask after this.
5. Before 9:00 PM: last commit pushed, repo private with organisers added, then submit the form (repo, diagram, contract, quality report, answers CSV, video link, deck).

---

## 6. Integration gates

A gate is ready when every track in its "Waits for" column has reported its parallel tasks
done (the agent's stop message in §0, posted to the team chat). Then those tracks merge to main
and work through the integration list together. A gate passes when its exit checks pass.

If you finish early and the gate is still waiting on another track, you may tell your agent to
start the next phase's parallel tasks against fakes. That is the user's call, not the agent's,
and the gate's integration work still waits for everyone it needs.

| Gate | Waits for | Integration work (sequential) | Exit checks |
|---|---|---|---|
| **G0** | A, B, C, D: Phase 1 done | Merge the four early providers. One contract PR, everyone reviews: `text.extractions` shape (S4), plus the `text` schema added to `kept.common.db.SCHEMAS` and `dbt/dbt_project.yml`; `Services` in `kept/app/api.py` gains two optional fields (default `None`) for A's steward queue and C's extraction store, so A and C don't each edit it; Ask table list; `TEXT_EVAL_SAMPLE_SIZE` in `kept.config` matched to the public labels; the two free LLM choices (§1b, K6) with `.env.example` updated to them; resolved TBCs (§9) | `make test-contract` green on main; the four providers are importable; §9 has an answer or an owner and deadline for every row |
| **G1** | A, B, C, D: Phase 2 done | A: bronze + silver + crosswalk v1 in `kept.duckdb` on real data. B: point `SqlPolicy` at the real silver/gold schema and run the guard on 10 real questions. C: run extraction on 50 real notes through the real redactor and gateway. D: build dbt features against real silver and the stub gold | `dbt build --select bronze silver` passes; each track's Phase 1–2 tests green; no unredacted text in the audit log's LLM events |
| **G2** | A, C, D: Phase 3 done (B joins for its 10 questions when ready) | A + C: gold `hardship_status` from `hardship.combine` over `text.extractions` (Q6). A: real gold + `DuckDBC360Reader` on main. D: dbt features on real gold → export → `feast materialize`; decide whether `kept/features/` moves to A. B: Ask answers 10 benchmark questions on real gold. D: run `CaseContextBuilder` on the real reader | quality gate (`run_gate`) passes on real gold; every open case resolves (Q2 of the contract); Feast online read returns a full `FeatureVector` for a real case |
| **G3** | A, C, D: Phase 4 done | D: `KeptEngine` with the real context builder, Feast provider and uplift v1. A: first parity run. C: a new note → live extraction → hardship → gold → features → the NBA card changes. A: steward routes on real queue | `kept score` produces a card for every open case; the "new note flips hardship" path works once; parity report produced |
| **G4** | A, B, C, D: Phase 5 done | D: `kept nightly` and `kept serve` with real `Services`. B: final scorecard and fairness on real recommendations | CI green; nightly runs end to end; scorecard ≥ 80% / ≥ 95%; fairness report produced |

## 7. Demo scenario (what G3 and G4 must make work)

Raw keys from three systems → one golden ID with match confidence and lineage → Ask a metric
question (SQL shown), a lookup, a policy question (cited), and a protected-attribute question
(refused with a suggestion) → open a case's NBA card (reasons, Kept sizing, checks) → add a note
that says the customer lost shifts → hardship turns possible, actions narrow, the card changes →
a hardship specialist and a second person release it → audit log shows every step.

---

## 8. How the parts connect

```
           contracts/c360_customer.odcs.yaml  (allow-lists, protected attrs, PII lists)
                          │ DataContract
   A ──── gold.c360_customer / C360Reader ──────────────┬──────────────┐
   │   ▲                                                │              │
   │   └─ hardship_status ◀── text.extractions ◀── C    │              │
   │                                  C ── Redactor ──▶ B (Ask)        │
   │                                  C ── TextExtractor ─▶ D (features: hardship, cease, promise)
   │                                                                   │
   └── parity_report ◀── FeatureProvider (offline vs online) ── D ── NBAEngine / ReleaseGate ──▶ app
                                       LLMGateway (B) + AuditLog (D) used by everyone
```

| Interface (`kept.contracts.interfaces`) | Provider | Real class | Consumers | Fake |
|---|---|---|---|---|
| `C360Reader` | A | `DuckDBC360Reader` (S2, new) | B, C, D | `DictC360Reader` |
| `Redactor` | C | `PresidioRedactor` | A, B, C | `PassThroughRedactor` |
| `TextExtractor` | C | `LLMExtractor` | D | (scripted via `PurposeLLM`) |
| `FeatureProvider` | D | `FeastFeatureProvider` | D, A (parity) | `StaticFeatureProvider` |
| `UpliftScorer` | D | `TLearnerUplift` | D | `ConstantScorer` |
| `CaseContextBuilder` | D (reads A's C360) | new, S3 | D | `FixedContextBuilder` |
| `NBAEngine`, `ReleaseGate` | D | `KeptEngine`, `Releaser` | app | fakes in `tests/app/test_api.py` |
| `AskService` | B | `CollectionsAsk` | app | fake in `tests/app/test_api.py` |
| `LLMGateway` | B | `LiteLLMGateway` | A, B, C | `ScriptedLLM`, `PurposeLLM` |
| `AuditLog` | D | `DuckDBAuditLog` | everyone | `InMemoryAuditLog` |

Shared data shapes (`kept.contracts.*`): `GoldenCustomer`, `CrosswalkEntry`, `FeatureVector`,
`TextExtraction`, `RedactedText`, `CaseContext`, `Proposal`, `NBACard`, `ReleaseDecision`,
`AskRequest`/`AskAnswer`/`Refusal`/`Clarification`, `AuditEvent`.
The feature list is `kept.contracts.feature_registry.FEATURES`. Every threshold the design
commits to is in `kept.config`.

### Changing a contract

Anything in `src/kept/contracts/`, `contracts/*.yaml`, `kept/config.py`, `tests/fakes.py`
or `dbt/models/gold/schema.yml` is shared.

- **Additive** (new optional field, new enum member, new feature): PR + one reviewer from each track that imports it.
- **Breaking** (rename, remove, type change): agree in chat first, bump `CONTRACT_VERSION`, update the fakes in the same PR (Q11).
- The four copies of the golden record (ODCS YAML, `GoldenCustomer`, dbt `schema.yml`, the gold SQL stub)
  and the feature registry vs `FeatureVector` are checked by `tests/contracts/`. The contract is also
  checked against the data dictionary (`tests/contracts/test_data_dictionary.py`).

### TDD workflow

1. Pick a red test in your track: `make test-b` (or `uv run pytest tests/ask/test_sql_guard.py`).
2. Replace the `raise NotImplementedError` with the smallest code that makes it pass.
3. Keep the contract suite green: `make test-contract` (CI runs it strictly).
4. See where everyone is: `make progress` (counts stubs per track).

CI runs `pytest --allow-stubs`: a test that hits a stub (or is marked `todo`) is
reported as xfail, so main stays green while work is in progress. Any other failure fails CI.
Tests marked `integration` need your track's extra (`make setup-x`) and skip without it.

Tests are the spec. If a test is wrong (the data says otherwise), change it in its
own commit with a one-line reason, and tell the track that consumes the behaviour.

---

## 9. Day-1 TBCs (resolve by G0 unless noted)

| Item | Owner | Where | Blocks | G0 status |
|---|---|---|---|---|
| Which `assignment_method` / `test_cell` values mean random assignment (`code_lookups`) | D + A | `kept/nba/uplift.py` | uplift training (Q7) | Answered (D): `collections_cases.assignment_method = 'random'` (146,573 cases) |
| Full code lists for `nba_recommendation_last` and `treatment_code` → `Action` | D | `kept/nba/legacy.py` | legacy mapping, hold-out, Qini baseline | Answered (D): 5 `nba_recommendation_last` values mapped; `send_letter` / `letter` map to no Action |
| Certified `metric_id` for roll rate; hand-translate certified metrics to SQL | B | `kept/ask/metrics.py` | Ask metric path | Answered (B): certified SQL in `kept/ask/certified.py`, 14 of 15 metrics |
| Final Ask table list vs `benchmark_questions.expected_tables` | B + A | `contracts/c360_customer.odcs.yaml` | SQL guard allow-list | In the G0 PR: the 16 tables in `askAllowedTables` cover B's certified SQL; B + A confirm in review |
| Authoritative payment source per product for `paid_14d` | D + A | `kept/nba/labels.py` | labels → uplift training | Open, D + A by G2: D's proposal in `docs/tracks/Track_D.md` |
| Ground-truth IDs for scoring matching? Ask the organisers | A | `kept/data/identity/` | match precision claim (by G1) | Open, A by G1: ask the organisers |
| Autopay/PAD accounts at other FIs: ignore or quarantine | A | `kept/data/identity/exact.py` | exact links | Open, A by G1 |
| Cash-flow rule thresholds, proposal TTL, close-call margin | C, D | `kept/hardship/cashflow_rule.py`, `kept/config.py` | hardship rule, release, tiers (by G2) | Open, C + D by G2 |
| Fill `REASON_TEMPLATES` (one fixed sentence per model feature) | D | `kept/nba/explain.py` (test marked `todo`) | explanation (by G3) | Answered (D): a fixed sentence per model feature |
| `text.extractions` shape (S4) | C, reviewed by A + D | `dbt/models/text/` | hardship into gold, text features | Answered (C): `dbt/models/text/sources.yml`, store interface `ExtractionStore` |
| Free LLM choices (§1b): the hosted free model for the Ask, the local model for text extraction | B (Ask), C (local) | `.env.example` | every LLM call | In the G0 PR: text `ollama/gemma3:12b-it-qat` (C); Ask model TBC, B picks before G0 merges |

## 10. Data traps the dictionary confirms (tests already cover them)

- The organisers say: use DuckDB or Polars for the large tables; loading everything into pandas is slow.
  Use pandas only on small frames (one case, a sample, a test).
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

## 11. If we fall behind

Cut in this order (design §10): the semantic layer, then voice (`transcribe`), then the
similar-cases line, then `mapping_assistant`. The GPU makes the voice run cheap, so cut voice
only if its code isn't done. Never cut: ID matching, refusals, the safety
rules (hard stops, permission gate, hardship override) or the release gate. If D is behind at
G2, A takes `kept/features/`. If a gate is stuck waiting on one track, the others help
that track rather than starting more of their own. If submission is getting close, drop the
next phase's lowest-priority task from every track instead of shortening Phase 6.
