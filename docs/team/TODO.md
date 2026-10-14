# Kept: polish and insight push (14–15 Oct)

Every request for the final push, in the order we work. One PR per item or group; `main` stays demo-ready.
Freeze Thu 15 Oct 18:00: anything not green by 16:00 stays out. Ticked = merged to `main`.

## Done
- [x] Voice extraction complete: 1,172/1,172 calls; the local model decodes to a typed JSON schema (#165)
- [x] Features refreshed to today's 06:00 UTC slot; preflight GO
- [x] Workspace redesign: framed panel, dark icon rail, full width, capsule chart, new queue (#166)
- [x] Landing restyled to match; 3D story untouched; free-floating top bar with solid pills (#166)
- [x] New app icon and logo mark (#166)
- [x] Steward review loads 50 at a time as you scroll (36,279 pairs), optimistic verdicts (#167)

## In progress: UI, motion and speed (`feat/ui-motion-perf`)
- [ ] Fonts: Inter (text), Inter Tight (display), Geist Mono (numbers), Source Serif (paper)
- [ ] One `PageHeader` on every page; GSAP SplitText title reveal; consistent size scale
- [ ] Page transitions: React `ViewTransition` (old page lifts and fades, new one rises; rail anchored)
- [ ] Rail drawn while the session loads (no jump between pages)
- [ ] Maple logo links to the landing page
- [ ] Ask redesign: prompt bar, example cards by path, thinking steps, chart/table tabs, grounding ladder, session history
- [ ] Redesign every page in the same language: Approvals, Audit, Bench, Steward, case page, guided demo, sign-in, pay page
- [ ] Lazy loading: charts, citations, panels below the fold load on demand; `content-visibility` on long lists
- [ ] Stale-while-revalidate cache for page data; prefetch a case on queue row hover
- [ ] Optimistic UI where safe (notes, confirmations, steward); releases show "releasing…" until the server's safety recheck answers
- [ ] Green batch releases in parallel (bounded), not one by one
- [ ] Notifications: bell in the top right, animated dropdown, toast queue (priority, dedupe, coalescing, cap), read state per user, built from real audit events

## Next: local model and orchestration
- [ ] llama.cpp server (CUDA, parallel slots, JSON-schema grammar) on the Gemma 3 12B QAT GGUF; LiteLLM points at it, Ollama as fallback
- [ ] Ask falls back to the local model when the free hosted tier rate-limits (fully offline demo)
- [ ] LangGraph Ask: route → retrieve → answer → grounding check → retry/refuse → cite, with the trace shown in the UI; merges only if released 21/21, stress ≥ 35/42, drill ≥ 26/30

## Next: insight pages
- [ ] Case page as a customer 360: payment and contact timeline, promise history, balances by product, payday calendar with the proposed date, uplift per action, SHAP reason waterfall, LLM case brief with quoted sources
- [ ] Portfolio page: KPIs by bucket, product and strategy with CIs; cohort heatmap; champion vs challengers; fairness and drift panels; table explorer with filters and CSV export; LLM insights, each with its SQL and table
- [ ] Explainability: SHAP (TreeExplainer) global and per case; calibration and uplift (Qini) curves on Bench

## Next: models (behind the champion/challenger gate)
- [ ] Hyperparameter search for the promise and uplift models; report honestly whether they beat the champion
- [ ] Promised-date recall on notes (0.73): prompt or rule fix, re-gated

## Phase 5 (unchanged, see NEXT_ROUND_PLAN.md §4a)
- [ ] Final benchmark run to `data/exports/reports/`
- [ ] Secret scan of the working tree and full history
- [ ] Deck PDF and video link in the repo
- [ ] Two dress rehearsals and the Q&A drill; track logs updated
- [ ] Freeze Thu 18:00; evening refresh and preflight GO (§7a)

## Waiting on Akshat
- [ ] Copy the model file for llama.cpp (one `sudo cp`, see the chat)
- [ ] Check the pay page in a browser
- [ ] Review deck v2
