"""Layer 2: Collections Ask (Track B). SQL computes the answer; the LLM only explains it.

scope.py      1. scope check: rules + LLM classifier
router.py     2. router: question -> Intent JSON (editable chips)
metrics.py    3a. certified metrics: SQL is compiled, never LLM-written
lookup.py     3b. lookups: 3 LLM SQL candidates, keep the majority result
policy.py     3c. policy questions: LanceDB over current documents, cite the section
sql_guard.py  4. sqlglot guard: SELECT only, approved tables, no protected/PII columns, limits
grounding.py  5. numbers only from results; low confidence -> one clarifying question, then refuse
privacy.py    analysts see aggregates of 10 or more
service.py    orchestrates 1-5, implements AskService
benchmark.py  scorecard on the provided benchmark questions
"""
