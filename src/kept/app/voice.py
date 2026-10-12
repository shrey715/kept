"""Recorded calls for the case page's Calls panel: Whisper's transcript of each recording, read like a note
(scripts/voice_wer.py, then scripts/voice_extract.py). Display only: the card already reads the same call from
the release's transcript, so these never reach a decision."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from kept.contracts.features import TextExtraction


class CallOut(BaseModel):
    voice_sample_id: str
    call_start: datetime
    duration_sec: int
    transcript: str  # Whisper's, redacted (the extraction's quote offsets point into it)
    extraction: TextExtraction | None  # None when the model gave no usable reply


class VoiceCalls:
    """voice_extractions.parquet indexed by case. A missing file means no calls, not an error."""

    def __init__(self, extractions: Path, audio_dir: Path) -> None:
        self._audio = audio_dir
        df = pd.read_parquet(extractions) if extractions.exists() else pd.DataFrame(columns=["case_id"])
        self._case_of: dict[str, str] = dict(zip(df.get("voice_sample_id", []), df.case_id, strict=True))
        self._by_case: dict[str, list[CallOut]] = {}
        records: list[dict[Any, Any]] = (
            df.sort_values("call_start", ascending=False).to_dict("records") if len(df) else []
        )
        for r in records:
            self._by_case.setdefault(r["case_id"], []).append(
                CallOut(
                    voice_sample_id=r["voice_sample_id"],
                    call_start=r["call_start"],
                    duration_sec=int(r["duration_sec"]),
                    transcript=r["redacted_text"],
                    extraction=TextExtraction.model_validate_json(r["extraction"])
                    if r["extraction"]
                    else None,
                )
            )

    def for_case(self, case_id: str) -> list[CallOut]:
        return self._by_case.get(case_id, [])

    def case_of(self, voice_sample_id: str) -> str | None:
        return self._case_of.get(voice_sample_id)

    def audio(self, voice_sample_id: str) -> Path | None:
        """The recording, if the voice pack is on this machine. IDs are checked against the index first."""
        if voice_sample_id not in self._case_of:
            return None
        path = self._audio / f"{voice_sample_id}.wav"
        return path if path.is_file() else None
