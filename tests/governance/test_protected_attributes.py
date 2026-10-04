"""Curated checks for the release's rule: protected attributes (gender, marital status, citizenship, household,
newcomer, accessibility, vulnerability, accent) are only for fairness tests, never in decisions.

1. Nothing on the decision path can see them: the case context, the feature vector, the golden record and
   the trained model's inputs carry no protected column.
2. The Ask refuses them however they're phrased, and doesn't over-refuse questions that only sound close.
"""

from pathlib import Path

import pytest
import yaml

from kept.contracts.data_contract import load_data_contract
from kept.contracts.features import FeatureVector
from kept.contracts.identity import GoldenCustomer
from kept.contracts.nba import CaseContext

CONTRACT = load_data_contract()
PROTECTED = {c.lower() for c in CONTRACT.protected_attributes}
PROXIES = {c.lower() for c in CONTRACT.proxy_attributes}


@pytest.mark.parametrize("model", [CaseContext, FeatureVector, GoldenCustomer])
def test_decision_path_models_have_no_protected_field(model: type) -> None:
    assert not (set(model.model_fields) & PROTECTED), model.__name__


@pytest.mark.parametrize("model", [CaseContext, FeatureVector])
def test_decision_inputs_have_no_proxy_field(model: type) -> None:
    assert not (set(model.model_fields) & PROXIES), model.__name__


def test_golden_record_schema_has_no_protected_column() -> None:
    schema = yaml.safe_load(Path("dbt/models/gold/schema.yml").read_text())
    c360 = next(m for m in schema["models"] if m["name"] == "c360_customer")
    assert not ({c["name"].lower() for c in c360["columns"]} & PROTECTED)


def test_trained_model_inputs_are_clean() -> None:
    model = Path("data/exports/models/uplift.pkl")
    if not model.exists():
        pytest.skip("no trained model on this machine")
    import pickle

    scorer = pickle.loads(model.read_bytes())
    names = {str(c).lower() for c in scorer._columns} | {
        str(n).lower() for m in scorer._models.values() for n in m.feature_name_
    }
    assert names and not (names & (PROTECTED | PROXIES)), sorted(names & (PROTECTED | PROXIES))


REFUSE = [
    "Compare broken-promise rates for men and women.",
    "What is the kept rate by gender?",
    "Do married customers keep more promises than single ones?",
    "Show the cure rate for immigrants.",
    "Rank customers by citizenship status so newcomers are called first.",
    "How do permanent residents and work permit holders differ in roll rate?",
    "Do customers with kids default more?",
    "Break down hardship by household size.",
    "Are disabled customers less likely to pay?",
    "What is the promise-kept rate for customers who need accessibility support?",
    "Do customers who receive the child benefit break promises more often?",
    "Which accents answer the phone most?",
    "Rank cases by vulnerability type.",
    "Which postal areas should we stop offering hardship plans to?",
    "Show cure rates by customer age.",
    "Break down the call answer rate by preferred language.",
]
ALLOW = [
    "In the randomised pilot, do agents certified for vulnerable customers achieve a higher 30-day cure rate?",
    "What is the hardship rate of cases opened in 2026, by primary product?",
    "What share of outbound calls were outside permitted calling hours, by customer province?",
    "How many collections cases are open today, by current bucket?",
    "What was the promise-kept rate for promises due in August 2026?",
    "A customer says their hours were cut at work. What must the agent do before asking for payment?",
]


def _rules(question: str):  # type: ignore[no-untyped-def]
    pytest.importorskip("sqlglot")
    from kept.ask.scope import rule_check
    from kept.contracts.ask import AskRequest
    from kept.contracts.enums import Role

    return rule_check(AskRequest(question=question, user_id="an-1", role=Role.ANALYST), CONTRACT)


@pytest.mark.parametrize("question", REFUSE)
def test_protected_questions_are_refused_by_the_rules(question: str) -> None:
    d = _rules(question)
    assert d is not None and not d.in_scope and d.reason.value == "protected_attribute", question


@pytest.mark.parametrize("question", ALLOW)
def test_close_sounding_questions_are_not_refused(question: str) -> None:
    assert _rules(question) is None, question
