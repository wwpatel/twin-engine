from __future__ import annotations

import os

import httpx


FISH_TTS_URL = "https://api.fish.audio/v1/tts"


def reference_id_for_twin(twin_id: str) -> str | None:
    """Prefer an approved per-Twin synthetic voice, with an optional shared demo fallback."""
    specific_key = f"FISH_AUDIO_REFERENCE_ID_{twin_id.upper().replace('-', '_')}"
    return os.getenv(specific_key) or os.getenv("FISH_AUDIO_REFERENCE_ID")


def synthesize(text: str, twin_id: str) -> bytes:
    """Call Fish Audio TTS with an approved configured synthetic voice only."""
    api_key = os.getenv("FISH_AUDIO_API_KEY")
    reference_id = reference_id_for_twin(twin_id)
    if not api_key:
        raise RuntimeError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")
    model = os.getenv("FISH_AUDIO_MODEL", "s2.1-pro")
    payload = {"text": text, "format": "mp3"}
    if reference_id:
        payload["reference_id"] = reference_id
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                FISH_TTS_URL,
                headers={"Authorization": f"Bearer {api_key}", "model": model},
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Fish Audio provider request failed: {exc}") from exc
    if not response.content:
        raise RuntimeError("Fish Audio provider returned empty audio.")
    return response.content
