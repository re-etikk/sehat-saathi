"""Rime TTS proxy — the API key never leaves the server.

Language-aware voice routing (a deliberate multilingual design choice):
  hi  -> RIME_SPEAKER_HI
  en  -> RIME_SPEAKER_EN
Coda/Mist take delivery cues from wording and punctuation (no SSML), so the agent
writes short spoken turns with natural punctuation — see agent.py system prompt.

Endpoint + payload follow docs.rime.ai (verify model/voice names against
docs.rime.ai/docs/models and /docs/voices before the final demo; validate the
EXACT model+voice+transport you will use on stage).
"""
import base64
import time

import httpx

import config


class RimeError(RuntimeError):
    pass


def synthesize(text: str, lang: str = "hi") -> dict:
    """Returns {audio_b64, content_type, latency_ms, speaker, model}."""
    if config.MOCK_MODE or not config.RIME_API_KEY:
        # frontend falls back to browser speechSynthesis in mock mode
        return {"audio_b64": None, "content_type": None, "latency_ms": 0,
                "speaker": "browser-tts(mock)", "model": "mock"}

    speaker = config.RIME_SPEAKER_HI if lang == "hi" else config.RIME_SPEAKER_EN
    payload = {
        "text": text,
        "speaker": speaker,
        "modelId": config.RIME_MODEL,
        "lang": "hin" if lang == "hi" else "eng",
        "audioFormat": "mp3",
        "samplingRate": 22050,
        "speedAlpha": 1.0,
    }
    headers = {
        "Authorization": f"Bearer {config.RIME_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "audio/mp3",
    }
    t0 = time.perf_counter()
    with httpx.Client(timeout=30) as http:
        r = http.post(config.RIME_TTS_URL, json=payload, headers=headers)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        raise RimeError(f"Rime TTS failed ({r.status_code}): {r.text[:300]}")
    return {
        "audio_b64": base64.b64encode(r.content).decode(),
        "content_type": "audio/mp3",
        "latency_ms": latency_ms,
        "speaker": speaker,
        "model": config.RIME_MODEL,
    }
