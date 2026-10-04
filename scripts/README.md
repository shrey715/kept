# scripts/

Reports, evaluations and one-off jobs. Pipeline steps live in `kept.cli` (`uv run kept <step>`).

| Script | What it does |
|---|---|
| `reportlib.py` | shared chart style and the Markdown → LaTeX → PDF build every report uses |
| `quality_report_full.py` | deliverable 4: `QUALITY_REPORT.pdf` (uses the issue checks in `quality_report.py`) |
| `business_case.py` | `docs/reports/business_case.pdf`: value, cost, ROI, sensitivity |
| `drift_report.py` | `docs/reports/drift_report.pdf`: feature drift (PSI) vs training |
| `fairness_report.py` | `docs/reports/fairness_report.pdf`: outcomes by protected group (compliance-only inputs) |
| `benchmark_report.py` | `docs/reports/benchmark_report.pdf` from a `kept benchmark` run |
| `eval_extraction.py` · `eval_call_summary.py` · `eval_qa.py` | text models vs the release's public labels |
| `redact_all.py` · `llm_label.py` · `backfill.py` | the one-off text jobs (redact everything, LLM labels, SetFit backfill) |
| `build_policy_index.py` | the Ask's policy and incident search index |
| `gen_silver.py` · `review_sample.py` · `sort_review_pairs.py` | silver model generation; the 300-pair match review sample |
| `ask_g1_check.py` · `g2_hardship_check.py` | integration-gate checks from the build (G1, G2) |
