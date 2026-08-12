"""Transkripsi VOICE NOTE (Fase 5) via Groq (Whisper) — audio → teks Indonesia.

Claude tak punya API audio & free-tier Gemini tak tersedia untuk region ini, jadi
transkripsi memakai Groq (Whisper-large-v3) — gratis, tanpa kartu, ASR Indonesia
bagus, dukung audio/ogg dari Telegram. HTTP multipart via stdlib (tanpa dependensi).

ENV: GROQ_API_KEY (dari https://console.groq.com/keys). Opsional GROQ_MODEL.
Bila key kosong → terkonfigurasi()=False (fitur suara nonaktif; bot minta ketik).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request

log = logging.getLogger("kantor.suara")

_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODEL = os.getenv("GROQ_MODEL", "whisper-large-v3-turbo")
_BOUNDARY = "----kantorAIvoiceboundary7f3a91"
# Telegram voice = audio/ogg (opus). Whisper butuh ekstensi yang benar utk deteksi format.
_EXT = {"audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
        "audio/mp4": "m4a", "audio/m4a": "m4a", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/webm": "webm", "audio/aac": "aac", "audio/flac": "flac"}


def terkonfigurasi() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _multipart(fields: dict, filename: str, filedata: bytes, filemime: str) -> bytes:
    out = b""
    for k, v in fields.items():
        out += (f"--{_BOUNDARY}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    out += (f"--{_BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {filemime}\r\n\r\n").encode()
    out += filedata + f"\r\n--{_BOUNDARY}--\r\n".encode()
    return out


def _transkrip_sync(data: bytes, mime: str) -> str:
    key = os.environ["GROQ_API_KEY"]
    ext = _EXT.get(mime, "ogg")
    body = _multipart(
        {"model": _MODEL, "language": "id", "response_format": "json"},
        f"voice.{ext}", data, mime or "audio/ogg")
    req = urllib.request.Request(
        _URL, data=body, method="POST",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    return (d.get("text") or "").strip()


async def transkrip(data: bytes, mime: str = "audio/ogg") -> str:
    """Transkrip audio → teks. '' bila gagal/kosong."""
    try:
        return await asyncio.to_thread(_transkrip_sync, data, mime or "audio/ogg")
    except Exception:  # noqa: BLE001
        log.warning("transkrip Groq gagal", exc_info=True)
        return ""
