# Track D: Model and UI

Person: Shreyas Deb · Tasks: `docs/TEAM_PLAN.md` §5

## Now
- Phase: 1 (parallel tasks done)
- Working on: nothing; waiting at G0
- Waiting on: G0 (A, B, C finish Phase 1)

## Done
- `DuckDBAuditLog` + `new_event_id` (early provider, Q2): `tests/common/test_audit.py` 7/7. Branch `track-d`.
- Labels `paid_within`, `rolled_forward`, `roll_forward_rate`: label tests in `tests/nba/test_uplift_explain_labels.py` 14/14.
- Rules `hard_stops`, `permission_gate`, `allowed_actions`, `hardship_override`: `tests/nba/test_rules.py` 54/54.
- Access and masking: `tests/governance/test_access.py` 39/39.
- `/health`: `tests/app/test_api.py::test_health`.

## Decisions and changes from the plan
- Audit log: a file-backed log opens a DuckDB connection per call (K5); `:memory:` keeps one. Events are stored as JSON, so reads are lossless.
- `roll_forward_rate` skips cases with a null `dpd_at_day_30` (younger than 30 days). Otherwise they'd count as cures and flatter the rate. New test added.
- `test_local_calling_hours` now allows Sunday contact: the DST fall-back case (1 Nov 2026) is a Sunday, and the Sunday rule masked the hour under test. Own commit.
- `mask_phone` assumes 10-digit national numbers (NANP); every customer is Canadian.

## Open questions
- None blocking Phase 1. For G0: random-assignment values and legacy code lists (§9) need `code_lookups` from the real data.

## Log
- 3 Oct: Phase 1 parallel tasks done; rebased onto force-pushed main (4b21af6).
