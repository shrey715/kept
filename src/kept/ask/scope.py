"""Step 1: refuse protected attributes, bulk personal data, write actions,
other people's cases, or data we don't have."""

from __future__ import annotations

from collections.abc import Callable

from kept.contracts.ask import AskRequest, Refusal, ScopeDecision
from kept.contracts.data_contract import DataContract

# An LLM classifier: (redacted question) -> (in_scope, reason or None). Injected so tests can fake it.
Classifier = Callable[[str], ScopeDecision]


def rule_check(request: AskRequest, contract: DataContract) -> ScopeDecision | None:
    """Deterministic rules. Return a refusal ScopeDecision if any rule fires, else None
    (meaning: ask the classifier). Rules never call an LLM."""
    raise NotImplementedError("Track B")


def check_scope(request: AskRequest, contract: DataContract, classifier: Classifier) -> ScopeDecision:
    """Rules first; classifier only if no rule fired. Fail closed: if the classifier
    raises, refuse with LOW_CONFIDENCE."""
    raise NotImplementedError("Track B")


def refusal_for(decision: ScopeDecision, *, suggestion: str | None) -> Refusal:
    """Turn an out-of-scope decision into the user-facing refusal. The message names
    the offending column and why: "This needs gender_code, which is excluded from
    collections analytics." The suggestion is prefixed "Try: ".
    An in-scope decision -> ValueError."""
    raise NotImplementedError("Track B")
