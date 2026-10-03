"""Whisper transcription of call audio. First thing we cut if behind.
Voice features never reach the model (voice is a proxy, design §9); only the transcript text does."""

from __future__ import annotations

from pathlib import Path


def transcribe(audio_path: Path, *, model_size: str = "base") -> str:
    raise NotImplementedError("Track C (cut first)")
