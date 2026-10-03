"""The fakes in tests/fakes.py must satisfy the Protocols they stand in for."""

from __future__ import annotations

import inspect

import pytest

from kept.contracts import interfaces as I

from ..fakes import (
    ConstantScorer,
    DictC360Reader,
    FixedContextBuilder,
    InMemoryAuditLog,
    PassThroughRedactor,
    PurposeLLM,
    ScriptedLLM,
    StaticFeatureProvider,
)

PAIRS = [
    (ScriptedLLM(), I.LLMGateway),
    (PurposeLLM({}), I.LLMGateway),
    (PassThroughRedactor(), I.Redactor),
    (InMemoryAuditLog(), I.AuditLog),
    (DictC360Reader(), I.C360Reader),
    (StaticFeatureProvider(), I.FeatureProvider),
    (FixedContextBuilder(), I.CaseContextBuilder),
    (ConstantScorer({}), I.UpliftScorer),
]


@pytest.mark.parametrize("fake,proto", PAIRS, ids=lambda x: getattr(x, "__name__", type(x).__name__))
def test_fake_satisfies_protocol(fake: object, proto: type) -> None:
    assert isinstance(fake, proto)


@pytest.mark.parametrize("fake,proto", PAIRS, ids=lambda x: getattr(x, "__name__", type(x).__name__))
def test_fake_signatures_match_protocol(fake: object, proto: type) -> None:
    for name, member in inspect.getmembers(proto, inspect.isfunction):
        if name.startswith("_"):
            continue
        expected = list(inspect.signature(member).parameters)
        actual = ["self", *inspect.signature(getattr(fake, name)).parameters]
        assert actual == expected, f"{type(fake).__name__}.{name}"


def test_scripted_llm_refuses_unredacted_text() -> None:
    with pytest.raises(TypeError):
        ScriptedLLM(["x"]).complete(system="s", user="raw text", purpose="p", actor_id="a")  # type: ignore[arg-type]
