# What changed from the system design, and why

The design (`docs/design/SharpeShooters_SystemDesign.pdf`) against what the repo runs today. Each change names the
evidence that decided it.

| Area | Planned | Built | Why |
|---|---|---|---|
| Language model | One LLM behind LiteLLM, provider open | Qwen3.8-27B (3-bit) on llama.cpp for every call: the Ask, briefs, text extraction | Customer text stays on the machine and there is no quota. A hosted free tier rate-limited mid-benchmark; Ollama ran a 4,096-token window under the Ask's ~9,000-token prompt (`ask_accuracy.md`) |
| Ask pipeline | Five steps: scope, router, metric / three SQL drafts / policy search, narration | The same steps as a LangGraph graph, plus deterministic intent checks, a convention linter that sends a draft back with the reason, reviewed SQL templates, per-period comparisons, and a judge when drafts disagree | Released 18/21 to 21/21 and the unseen drill 22/30 to 27/30 on the same model (`ask_accuracy.md`) |
| Ask speed | Under 5 s | Median about 6 s on the local model | Local inference on one GPU; the hosted model was faster but is out of scope |
| Text extraction | LLM with quoted evidence, F1 ≥ 0.80 gate, SetFit backfill | As planned; replies decoded to the JSON schema; a rule against cease false alarms | Malformed replies 152 to 0 on 1,172 calls; cease F1 1.00 on the holdout (`extraction_gate.md`) |
| Voice | Whisper on calls | Whisper large-v3-turbo on every call recording | Word error rate 9.4% against the bank's 12.4% (`voice_wer.md`) |
| Promise model | Not in the design | LightGBM, isotonic-calibrated, alongside the bank's own score | Combined with the bank's score: AUC 0.728 against 0.702, +2.5 points [1.9, 3.3]. A first version scored 0.92 through a leaking feature, which was removed (`model_card.md`, `evidence.md` §3) |
| Uplift model | LightGBM T-learner, checked with Qini | As planned; the champion is kept behind a challenger gate | A 40-candidate tuning search lost to the champion on held-out decisions (`tuning.md`) |
| Payroll features | Inputs to the uplift model | Used for promise dating and sizing, not as model inputs | They did not beat the champion beyond the noise (`tuning.md`) |
| Larger model | Not planned | Gemma 4 26B tried and rejected | 24 s a note and runaway replies on a 16 GB GPU, no gain on held-out notes |
| Briefs | Not in the design | A short brief per case and for the portfolio; every point cites its facts or quotes, unverified numbers are removed | Agents and leads get the essentials before acting |
| Calendar | Not in the design | Promise dues, contact windows, approval deadlines, paydays and hardship reviews, with a subscription feed (`GET /calendar.ics`) | Collections work is date-driven; the feed puts it in the tools people already use |
| Hold-out and pilot | A permanent 5% hold-out read at day 30 | Specified in the pilot plan; the bank's own randomised strategy cells are the evidence today | A live hold-out needs production traffic |
| Production scale | Spark or Snowflake, Redis, Kafka | DuckDB, dbt, Feast on one machine | The same dbt and Splink code moves over; 96,000 cards score in about 85 s here |
