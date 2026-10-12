"""LiteLLM gateway (Track B owns). Network is never touched: litellm.completion is patched."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from kept.common.llm import LiteLLMGateway, Purpose
from kept.contracts import AuditKind, RedactedText

from ..fakes import InMemoryAuditLog

pytestmark = pytest.mark.track_b


def _reply(text: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        model="test-model",
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    litellm = pytest.importorskip("litellm")
    calls: list[dict[str, Any]] = []
    replies = iter([_reply('{"ok": true}'), _reply("not json"), _reply("plain")])

    def fake_completion(**kw: Any) -> Any:
        calls.append(kw)
        return next(replies)

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


def _text(s: str) -> RedactedText:
    return RedactedText(text=s, redactor_version="test")


def test_rejects_unredacted_text() -> None:
    gw = LiteLLMGateway(model="test-model", audit_log=InMemoryAuditLog())
    with pytest.raises(TypeError):
        gw.complete(system="s", user="raw PII here", purpose=Purpose.ASK_ROUTE, actor_id="u1")  # type: ignore[arg-type]


def test_json_schema_validated_and_parsed(patched: list[dict[str, Any]]) -> None:
    log = InMemoryAuditLog()
    gw = LiteLLMGateway(model="test-model", audit_log=log)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    r = gw.complete(system="s", user=_text("u"), purpose=Purpose.ASK_ROUTE, actor_id="u1", json_schema=schema)
    assert r.parsed == {"ok": True} and r.call_id
    with pytest.raises(ValueError):
        gw.complete(system="s", user=_text("u2"), purpose=Purpose.ASK_ROUTE, actor_id="u1", json_schema=schema)


def test_every_call_logged_including_failures(patched: list[dict[str, Any]]) -> None:
    log = InMemoryAuditLog()
    gw = LiteLLMGateway(model="test-model", audit_log=log)
    schema = {"type": "object", "required": ["ok"]}
    gw.complete(
        system="s", user=_text("u"), purpose=Purpose.TEXT_EXTRACT, actor_id="system:x", json_schema=schema
    )
    with pytest.raises(ValueError):
        gw.complete(
            system="s", user=_text("u2"), purpose=Purpose.TEXT_EXTRACT, actor_id="system:x", json_schema=schema
        )
    events = log.read(kind=AuditKind.LLM_CALL)
    assert len(events) == 2
    assert {e.payload["purpose"] for e in events} == {Purpose.TEXT_EXTRACT}
    assert all("model" in e.payload for e in events)
    # the prompt text itself is not copied into the audit payload
    assert all(v not in ("u", "u2") for e in events for v in e.payload.values())


def test_model_is_configurable(patched: list[dict[str, Any]]) -> None:
    gw = LiteLLMGateway(model="ollama/llama3.1", audit_log=InMemoryAuditLog())
    gw.complete(system="s", user=_text("u"), purpose=Purpose.ASK_NARRATE, actor_id="u1")
    assert patched[0]["model"] == "ollama/llama3.1"
    assert json.dumps(patched[0]["messages"])  # serialisable


def test_rate_limit_is_retried_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    litellm = pytest.importorskip("litellm")
    n = {"calls": 0}

    def limited(**kw: Any) -> Any:
        n["calls"] += 1
        if n["calls"] < 3:
            raise litellm.RateLimitError("slow down", llm_provider="test", model="test-model")
        return _reply("fine")

    monkeypatch.setattr(litellm, "completion", limited)
    log = InMemoryAuditLog()
    gw = LiteLLMGateway(model="test-model", audit_log=log, max_retries=2, backoff_s=0)
    assert gw.complete(system="s", user=_text("u"), purpose=Purpose.ASK_NARRATE, actor_id="u1").text == "fine"
    (event,) = log.read(kind=AuditKind.LLM_CALL)
    assert event.payload["attempts"] == 3

    n["calls"] = -10  # never succeeds within the retry budget
    with pytest.raises(litellm.RateLimitError):
        gw.complete(
            system="s", user=_text("u2"), purpose=Purpose.ASK_NARRATE, actor_id="u1"
        )  # not the cached one
    assert log.read(kind=AuditKind.LLM_CALL)[-1].payload["ok"] is False


def test_a_repeated_prompt_is_answered_from_the_cache_and_still_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm = pytest.importorskip("litellm")
    n = {"calls": 0}

    def flaky(**kw: Any) -> Any:  # one 503 first: transient errors are retried, not just rate limits
        n["calls"] += 1
        if n["calls"] == 1:
            raise litellm.ServiceUnavailableError("busy", llm_provider="test", model="test-model")
        return _reply('{"ok": true}')

    monkeypatch.setattr(litellm, "completion", flaky)
    log = InMemoryAuditLog()
    gw = LiteLLMGateway(model="test-model", audit_log=log, backoff_s=0)
    ask = {"system": "s", "purpose": Purpose.ASK_SQL, "actor_id": "u1", "json_schema": {"type": "object"}}
    first = gw.complete(user=_text("same"), **ask)  # type: ignore[arg-type]
    again = gw.complete(user=_text("same"), **ask)  # type: ignore[arg-type]
    assert first.parsed == again.parsed == {"ok": True} and n["calls"] == 2  # 503, then one real reply
    events = log.read(kind=AuditKind.LLM_CALL)
    assert len(events) == 2 and events[1].payload["cached"] is True
    gw.complete(user=_text("same"), temperature=0.3, **ask)  # type: ignore[arg-type]
    assert n["calls"] == 3  # sampled replies are never cached
