# Kept: polish and insight push (14–15 Oct)

Every request for the final push, in the order we work. One PR per item or group; `main` stays demo-ready.
Freeze Thu 15 Oct 18:00: anything not green by 16:00 stays out. Ticked = merged to `main`.

## Done
- [x] Audit screens read newest events in SQL: 7.9 s to 0.04 s (#168)
- [x] Concurrent audit appends can't fork the hash chain (lock + test) (#168)
- [x] Voice extraction complete: 1,172/1,172 calls; the local model decodes to a typed JSON schema (#165)
- [x] Features refreshed to today's 06:00 UTC slot; preflight GO
- [x] Workspace redesign: framed panel, dark icon rail, full width, capsule chart, new queue (#166)
- [x] Landing restyled to match; 3D story untouched; free-floating top bar with solid pills (#166)
- [x] New app icon and logo mark (#166)
- [x] Steward review loads 50 at a time as you scroll (36,279 pairs), optimistic verdicts (#167)

## UI, motion and speed (#168, #170)
- [x] Section headings: maple eyebrow, display title, icon chip, on every dashboard section
- [x] Handwritten font (Kalam) for the sketch and signatures
- [x] Fonts: Inter (text), Inter Tight (display), Geist Mono (numbers), Source Serif (paper)
- [x] One `PageHeader` on every page; GSAP SplitText title reveal; consistent size scale
- [x] Page transitions: React `ViewTransition` (old page lifts and fades, new one rises; rail anchored)
- [x] Rail drawn while the session loads (no jump between pages)
- [x] Maple logo links to the landing page
- [x] Ask redesign: prompt bar, example cards by path, thinking steps, chart/table tabs, grounding ladder, session history
- [x] Redesign every page in the same language: Approvals (stage cards), Audit, Bench, Steward, case page, sign-in (two-pane, pencil sketch)
- [ ] Guided demo and pay page in the same language
- [x] Lazy loading: charts, citations, panels below the fold load on demand; `content-visibility` on long lists
- [x] Stale-while-revalidate cache for page data; prefetch a case on queue row hover
- [x] Optimistic UI where safe (steward verdicts, mark-as-read); releases wait for the server's safety recheck
- [x] Green batch releases in parallel (bounded), not one by one
- [x] Notifications: bell in the top right, animated dropdown, toast queue (priority, dedupe, coalescing, cap), read state per user, built from real audit events

## Next: local model and orchestration
- [x] Gateway supports `llamacpp/` models (local llama-server, schema-constrained) (#169)
- [x] Gemma 4 26B tried as challenger: too slow on 16 GB (24 s a note), not more accurate; stays out
- [ ] Gemma 3 12B on llama-server (needs the model file copied, see Waiting on Akshat)
- [ ] Ask falls back to the local model when the free hosted tier rate-limits (fully offline demo)
- [ ] LangGraph Ask: route → retrieve → answer → grounding check → retry/refuse → cite, with the trace shown in the UI; merges only if released 21/21, stress ≥ 35/42, drill ≥ 26/30

## Next: insight pages
- [x] Case page: full TreeSHAP drivers (both signs), warehouse history (contacts, promises, month-end balance and payments), stat tiles (#170)
- [ ] Case page: LLM case brief with quoted sources
- [x] Portfolio page: KPIs, balance and recovery by bucket, cases by action, the bank's A/B as a forest plot (Wilson 95% CIs), cohort heatmap, insights each with its SQL, case explorer (server-side filter/sort/page, CSV), analysts aggregates-only
- [ ] Portfolio: fairness and drift panels; LLM-written daily brief over the computed facts (numbers checked)
- [x] Explainability per case: TreeSHAP drivers on every card (#170)
- [ ] Explainability, global: feature importance, calibration and uplift (Qini) curves

## Next: models (behind the champion/challenger gate)
- [ ] Hyperparameter search for the promise and uplift models; report honestly whether they beat the champion
- [ ] Promised-date recall on notes (0.73): prompt or rule fix, re-gated

## Phase 5 (unchanged, see NEXT_ROUND_PLAN.md §4a)
- [ ] Final benchmark run to `data/exports/reports/`
- [ ] Secret scan of the working tree and full history
- [ ] Deck PDF and video link in the repo
- [ ] Two dress rehearsals and the Q&A drill; track logs updated
- [ ] Freeze Thu 18:00; evening refresh and preflight GO (§7a)

## Sources and polish
- [x] Ask sources: table/row/freshness chips, formatted and highlighted SQL with copy, numbered policy quotes with Verify
- [x] Phone access: dev server allows the LAN IP (KEPT_DEV_ORIGINS)

## Waiting on Akshat
- [ ] Copy the model file for llama.cpp (one `sudo cp`, see the chat)
- [ ] Check the pay page in a browser
- [ ] Review deck v2
