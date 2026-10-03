"""Step 1: refuse protected attributes, bulk personal data, write actions,
other people's cases, or data we don't have."""

from __future__ import annotations

import re
from collections.abc import Callable

from kept.common.llm import Purpose
from kept.contracts.ask import AskRequest, Refusal, RefusalReason, ScopeDecision
from kept.contracts.data_contract import DataContract
from kept.contracts.interfaces import LLMGateway, Redactor

# An LLM classifier: (question) -> ScopeDecision. Injected so tests can fake it.
Classifier = Callable[[str], ScopeDecision]

# Plain-English ways to ask for a protected or proxy column. A column is only matched when the
# contract lists it, so the contract stays the source of truth; its name (and name with spaces)
# is always matched too. Add a phrase here when a refusal is missed.
_ALIASES: dict[str, str] = {
    "gender_code": r"gender|sex",
    "marital_status": r"marital|married",
    "newcomer_program_flag": r"newcomers?|immigra\w+",
    "citizenship_status": r"citizen\w*|permanent resident",
    "household_size": r"household",
    "dependants_count": r"dependants?|dependents?",
    "accessibility_needs_flag": r"accessibility|disabilit\w+",
    "vulnerability_type": r"vulnerability type",
    "ccb_deposit_flag": r"canada child benefit|ccb",
    "customer_accent_region": r"accents?",
    "age_band": r"age bands?|age groups?|customer age|by age|seniors?",
    "date_of_birth": r"dates? of birth|birthdays?",
    "postal_code": r"postal (?:codes?|areas?)|zip",
    "fsa": r"fsas?",
    "preferred_language": r"preferred language",
    "ei_deposit_flag": r"employment insurance|ei benefits?",
    "cpp_oas_deposit_flag": r"cpp|oas",
}
_PII = re.compile(r"\b(?:phone numbers?|e-?mails?|addresses|names|sin|social insurance)\b", re.I)
_BULK = re.compile(r"\b(?:list|export|download|dump|every|all|each)\b", re.I)
_WRITE = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:delete|drop|remove|update|insert|modify|send|create|cancel"
    r"|reassign|assign|approve|waive|merge|change\s+(?:the|this|that|its|all|an?|cs?-\d))\b",
    re.I,
)
_CASE_ID = re.compile(r"\bCS?-\d[\w-]*", re.I)


def _mentions(text: str, column: str) -> bool:
    alias = _ALIASES.get(column)
    pat = rf"\b(?:{re.escape(column)}|{re.escape(column.replace('_', ' '))}{'|' + alias if alias else ''})\b"
    return re.search(pat, text, re.I) is not None


def rule_check(request: AskRequest, contract: DataContract) -> ScopeDecision | None:
    """Deterministic rules. Return a refusal ScopeDecision if any rule fires, else None
    (meaning: ask the classifier). Rules never call an LLM."""
    q = request.question

    def refuse(reason: RefusalReason, *terms: str) -> ScopeDecision:
        return ScopeDecision(in_scope=False, reason=reason, offending_terms=terms, decided_by="rules")

    hit = tuple(
        sorted(c for c in contract.protected_attributes | contract.proxy_attributes if _mentions(q, c))
    )
    if hit:
        return refuse(RefusalReason.PROTECTED_ATTRIBUTE, *hit)
    # plain words like "email" are only bulk requests with a bulk marker; snake_case names always are
    named = tuple(
        sorted(
            c
            for c in {c.split(".")[-1] for c in contract.direct_pii_columns}
            if "_" in c and re.search(rf"\b{c}\b", q, re.I)
        )
    )
    if named or (_PII.search(q) and _BULK.search(q)):
        return refuse(RefusalReason.BULK_PERSONAL_DATA, *named)
    if _WRITE.search(q):
        return refuse(RefusalReason.WRITE_ACTION)
    if request.role.value == "agent":
        other = tuple(
            c for c in _CASE_ID.findall(q) if c.upper() not in {x.upper() for x in request.own_case_ids}
        )
        if other:
            return refuse(RefusalReason.OTHER_PEOPLES_CASES, *other)
    return None


def check_scope(request: AskRequest, contract: DataContract, classifier: Classifier) -> ScopeDecision:
    """Rules first; classifier only if no rule fired. Fail closed: if the classifier
    raises, refuse with LOW_CONFIDENCE."""
    if (decision := rule_check(request, contract)) is not None:
        return decision
    try:
        return classifier(request.question)
    except Exception:
        return ScopeDecision(in_scope=False, reason=RefusalReason.LOW_CONFIDENCE, decided_by="classifier")


_MESSAGES = {
    RefusalReason.BULK_PERSONAL_DATA: "I can't list personal contact details in bulk.",
    RefusalReason.WRITE_ACTION: "Ask is read-only: I can't change records or send messages.",
    RefusalReason.OTHER_PEOPLES_CASES: "You can only ask about the cases in your own queue.",
    RefusalReason.DATA_UNAVAILABLE: "The collections data doesn't cover that.",
    RefusalReason.LOW_CONFIDENCE: "I couldn't tell whether I can answer that, so I didn't. Try rephrasing.",
    RefusalReason.SQL_GUARD: "That would need a query I'm not allowed to run.",
    RefusalReason.SMALL_GROUP: "That group is too small to show.",
}


def refusal_for(decision: ScopeDecision, *, suggestion: str | None) -> Refusal:
    """Turn an out-of-scope decision into the user-facing refusal. The message names
    the offending column and why: "This needs gender_code, which is excluded from
    collections analytics." The suggestion is prefixed "Try: ".
    An in-scope decision -> ValueError."""
    if decision.in_scope:
        raise ValueError("an in-scope decision has nothing to refuse")
    reason = decision.reason or RefusalReason.LOW_CONFIDENCE
    if reason is RefusalReason.PROTECTED_ATTRIBUTE:
        terms = ", ".join(decision.offending_terms) or "a protected attribute"
        message = f"This needs {terms}, which is excluded from collections analytics."
    else:
        message = _MESSAGES[reason]
    return Refusal(reason=reason, message=message, suggestion=f"Try: {suggestion}" if suggestion else None)


_CLASSIFIER_SYSTEM = """You decide whether a question can be answered by Maple Bank's collections Ask.
In scope: metrics and counts over cases, promises to pay, contacts, accounts and agents; how collections
practice works (contact limits, calling hours, consent, the National Do Not Call List, hardship programmes,
promises, disputes, complaints, escalation, regulatory rules for collectors), answered from the policy and
procedure documents; questions about how a metric behaves. When unsure, answer in_scope true: later checks
catch missing data.
Answer in_scope false with a reason only when the question is: about something else entirely
(data_unavailable, e.g. weather, sports, other banks); asks for protected attributes such as gender, marital
status, citizenship, newcomer status, disability, age, postal code or language (protected_attribute); asks
for lists of personal data (bulk_personal_data); or asks to change data or contact customers
(write_action). reason is null when in scope."""
_CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "reason": {"type": ["string", "null"], "enum": [r.value for r in RefusalReason] + [None]},
        "offending_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["in_scope"],
}


def make_classifier(llm: LLMGateway, redactor: Redactor, *, actor_id: str) -> Classifier:
    """The LLM scope classifier (S5). Redacts the question before the call; a bad reply raises
    ValueError, which check_scope turns into a LOW_CONFIDENCE refusal."""

    def classify(question: str) -> ScopeDecision:
        reply = llm.complete(
            system=_CLASSIFIER_SYSTEM,
            user=redactor.redact(question),
            purpose=Purpose.ASK_SCOPE,
            actor_id=actor_id,
            json_schema=_CLASSIFIER_SCHEMA,
        )
        if reply.parsed is None:
            raise ValueError("classifier reply is not a JSON object")
        return ScopeDecision.model_validate({**reply.parsed, "decided_by": "classifier"})

    return classify
