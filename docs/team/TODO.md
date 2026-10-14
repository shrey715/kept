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
- [x] Guided demo and pay page in the same language (pay: framed card, steps, secure-link chip)
- [x] Lazy loading: charts, citations, panels below the fold load on demand; `content-visibility` on long lists
- [x] Stale-while-revalidate cache for page data; prefetch a case on queue row hover
- [x] Optimistic UI where safe (steward verdicts, mark-as-read); releases wait for the server's safety recheck
- [x] Green batch releases in parallel (bounded), not one by one
- [x] Notifications: bell in the top right, animated dropdown, toast queue (priority, dedupe, coalescing, cap), read state per user, built from real audit events

## Next: local model and orchestration
- [x] Gateway supports `llamacpp/` models (local llama-server, schema-constrained) (#169)
- [x] Gemma 4 26B tried as challenger: too slow on 16 GB (24 s a note), not more accurate; stays out
- [x] Gemma 3 12B on llama-server (the standard QAT Q4_0 GGUF; Ollama's own file isn't llama.cpp-compatible)
- [x] Local models only (14 Oct): the Ask runs on local Gemma 3 too; no hosted API, no keys
- [x] LangGraph Ask with deterministic checks, a convention linter, reviewed templates and a judge, on Qwen3.8-27B (llama.cpp): released 21/21, stress 38/42, unseen drill 27/30 (#175)
- [x] Text extraction and briefs on Qwen3.8-27B too: passes the gate on notes and calls (`extraction_gate.md`); Gemma and Ollama removed
- [ ] Optional: Qwen3.6-35B-A3B bake-off (download paused, resumable); Qwen3.8 already clears every bar

## Next: insight pages
- [x] Case page: full TreeSHAP drivers (both signs), warehouse history (contacts, promises, month-end balance and payments), stat tiles (#170)
- [x] Case brief: local model, every bullet cites facts or quotes, numbers checked, template fallback
- [x] Portfolio page: KPIs, balance and recovery by bucket, cases by action, the bank's A/B as a forest plot (Wilson 95% CIs), cohort heatmap, insights each with its SQL, case explorer (server-side filter/sort/page, CSV), analysts aggregates-only
- [x] Portfolio: tonight's cited brief; Models and governance section (reliability curve, Qini curve, TreeSHAP importance, fairness grid, drift PSI)
- [x] Explainability per case: TreeSHAP drivers on every card (#170)
- [x] Explainability, global: `scripts/model_card.py` (promise AUC 0.610, Brier 0.221 on 50,653 held-out promises; uplift Qini with noise)

## Next: models (behind the champion/challenger gate)
- [x] Uplift hyperparameter search, 40 candidates (`scripts/tune_uplift.py`, `docs/reports/tuning.md`): worse than the champion on held-out decisions, champion kept
- [x] Promised-date recall on notes: 0.73 to 0.83 with Qwen3.8-27B (same prompt, re-gated on the holdout)

## Deck
- [x] HTML presentation (`docs/deck/present/index.html`) and the PDF rebuilt with the final numbers (`make deck`)
- [x] LaTeX deck (`make deck`, 24 slides with appendix) and speaker notes; `docs/team/DECK_ISSUES.md` DK-01 to DK-17 drafted

## Phase 5 (unchanged, see NEXT_ROUND_PLAN.md §4a)
- [x] Final benchmark run to `data/exports/reports/` (local Qwen, 14 Oct)
- [x] Secret scan of the working tree and full history: clean (`scripts/secret_scan.sh`, 115,795 added lines, 488 commits)
- [~] Deck PDF in the repo (`docs/deck/kept.pdf`); the video link is the team's to add
- [ ] Two dress rehearsals and the Q&A drill; track logs updated
- [ ] Freeze Thu 18:00; evening refresh and preflight GO (§7a)

## Sources and polish
- [x] Studio redesign of every page and a calendar with `.ics` export, fitted to the window (#176)
- [x] Ask sources: table/row/freshness chips, formatted and highlighted SQL with copy, numbered policy quotes with Verify
- [x] Phone access: dev server allows the LAN IP (KEPT_DEV_ORIGINS)

## Waiting on Akshat
- [x] Copy the model file for llama.cpp (it turned out unusable; a standard GGUF was downloaded instead and the copy deleted)
- [ ] Check the pay page in a browser
- [ ] Review deck v2
