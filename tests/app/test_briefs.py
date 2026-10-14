"""Briefs: the model writes cited bullets; uncited or ungrounded ones never reach the reader."""

from dataclasses import replace

from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.briefs import Source, check, write
from kept.app.demo import demo_services

from ..fakes import ScriptedLLM

SOURCES = [
    Source(id="F1", kind="fact", label="Sized promise", text="$140.00 × 3, first due 2026-10-17"),
    Source(id="E1", kind="quote", label="Note N-1 · hardship", text="lost my shifts at the plant"),
]


def test_check_keeps_cited_grounded_bullets_only() -> None:
    kept, dropped = check(
        [
            {"text": "Offer $140 a month, three times [F1].", "cites": ["F1"]},  # grounded, cite tag stripped
            {"text": "She lost her shifts.", "cites": ["E1", "E9"]},  # E9 doesn't exist: dropped from cites
            {"text": "Offer $200.", "cites": ["F1"]},  # 200 is in no source
            {"text": "She is fine.", "cites": []},  # cites nothing
        ],
        SOURCES,
    )
    assert [b.text for b in kept] == ["Offer $140 a month, three times.", "She lost her shifts."]
    assert kept[1].cites == ["E1"] and dropped == 2


def test_write_uses_the_model_then_falls_back_when_nothing_survives() -> None:
    good = ScriptedLLM([{"bullets": [{"text": "Customer lost shifts.", "cites": ["E1"]}]}])
    brief = write(good, system="s", sources=SOURCES, fallback=[], purpose="p", actor_id="u")
    assert brief.model is not None and brief.bullets[0].cites == ["E1"]
    assert good.calls[0]["user"].redactor_version == "fixed-text"  # computed facts and redacted quotes only
    bad = ScriptedLLM([{"bullets": [{"text": "Owes $999.", "cites": ["F1"]}]}])
    fb = write(
        bad,
        system="s",
        sources=SOURCES,
        fallback=check([{"text": "x", "cites": ["F1"]}], SOURCES)[0],
        purpose="p",
        actor_id="u",
    )
    assert fb.model is None and [b.text for b in fb.bullets] == ["x"]
    down = write(
        ScriptedLLM([RuntimeError("ollama down")]),
        system="s",
        sources=SOURCES,
        fallback=[],
        purpose="p",
        actor_id="u",
    )
    assert down.model is None and down.bullets == []


def test_case_brief_route_cites_the_card_and_caches() -> None:
    services = replace(demo_services(), brief_llm=None)  # no model: the template brief
    client = TestClient(create_app(services))
    q = {"user_id": "agent-7", "role": "agent"}
    case = client.get("/queue", params=q).json()[0]["case_id"]
    b = client.get(f"/cases/{case}/brief", params=q).json()
    assert b["model"] is None and b["bullets"] and b["bullets"][0]["cites"] == ["F1"]
    assert {s["id"] for s in b["sources"]} >= {"F1"}
    assert client.get(f"/cases/{case}/brief", params=q).json()["generated_at"] == b["generated_at"]  # cached
