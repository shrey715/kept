"""The Calls panel: a case's recordings, read by Whisper, behind the same role check as the case."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from kept.app.api import Services, create_app
from kept.app.voice import VoiceCalls
from kept.contracts import ExtractedValue, HardshipSignal, StatedReason, TextExtraction
from kept.contracts.features import Evidence
from kept.contracts.identity import GoldenCustomer
from tests.fakes import DictC360Reader, InMemoryAuditLog

TEXT = "My shifts were cut at the plant, I can pay fifty on the fifteenth."


def _calls(tmp: Path) -> VoiceCalls:
    quote = "My shifts were cut at the plant"
    x = TextExtraction(
        source_id="VS-1",
        case_id="C-1",
        hardship_signal=ExtractedValue(
            value=HardshipSignal.CLEAR,
            evidence=Evidence(quote=quote, source_id="VS-1", char_start=0, char_end=len(quote)),
            confidence=0.9,
        ),
        stated_reason=ExtractedValue(value=StatedReason.REDUCED_INCOME, confidence=0.9),
        promise_intent=ExtractedValue(value=False, confidence=0.9),
        promised_date=ExtractedValue(value=None, confidence=0.9),
        promised_amount=ExtractedValue(value=None, confidence=0.9),
        dispute=ExtractedValue(value=False, confidence=0.9),
        cease_request=ExtractedValue(value=False, confidence=0.9),
        third_party_present=ExtractedValue(value=False, confidence=0.9),
        extractor="llm:extract-v4+cease-rule",
        extracted_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    pd.DataFrame(
        [
            {
                "voice_sample_id": "VS-1",
                "case_id": "C-1",
                "call_start": datetime(2026, 9, 1, 15),
                "duration_sec": 90,
                "redacted_text": TEXT,
                "extraction": x.model_dump_json(),
            }
        ]
    ).to_parquet(tmp / "x.parquet")
    (tmp / "voice").mkdir()
    (tmp / "voice" / "VS-1.wav").write_bytes(b"RIFF....WAVE")
    return VoiceCalls(tmp / "x.parquet", tmp / "voice")


def test_a_case_lists_its_calls_and_plays_them_only_for_its_agent(
    tmp_path: Path, make_customer: Callable[..., GoldenCustomer]
) -> None:
    c360 = DictC360Reader({"G-1": make_customer(open_case_id="C-1", assigned_agent_id="AG-1")})
    app = create_app(Services(None, None, None, c360, InMemoryAuditLog(), calls=_calls(tmp_path)))  # type: ignore[arg-type]
    client = TestClient(app)
    (call,) = client.get("/cases/C-1/calls", params={"user_id": "AG-1", "role": "agent"}).json()
    ev = call["extraction"]["hardship_signal"]["evidence"]
    assert call["transcript"][ev["char_start"] : ev["char_end"]] == "My shifts were cut at the plant"
    audio = client.get("/calls/VS-1/audio", params={"user_id": "AG-1", "role": "agent"})
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    assert client.get("/calls/VS-1/audio", params={"user_id": "AG-2", "role": "agent"}).status_code == 403
    assert client.get("/calls/VS-9/audio", params={"user_id": "AG-1", "role": "agent"}).status_code == 404


def test_no_recordings_on_this_machine_means_no_panel(tmp_path: Path) -> None:
    assert VoiceCalls(tmp_path / "missing.parquet", tmp_path).for_case("C-1") == []
