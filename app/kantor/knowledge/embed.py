"""Embedding teks via Voyage AI — untuk pencarian MAKNA di otak perusahaan.

Ringan: hanya panggil HTTP (tak ada model berat di server). Env:
  VOYAGE_API_KEY : kunci API Voyage (wajib)
  VOYAGE_MODEL   : model (opsional, default 'voyage-3.5-lite')
Bila key tak ada → terkonfigurasi()=False; pemanggil jatuh ke pencarian keyword.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request

_URL = "https://api.voyageai.com/v1/embeddings"


def _model() -> str:
    return os.getenv("VOYAGE_MODEL", "voyage-3.5-lite")


def terkonfigurasi() -> bool:
    return bool(os.getenv("VOYAGE_API_KEY"))


def embed(teks: list[str], *, input_type: str = "document") -> list[list[float]]:
    """Embed daftar teks → daftar vektor. `input_type`: 'document' (saat simpan) /
    'query' (saat cari) — Voyage mengoptimalkan retrieval asimetris."""
    teks = [t for t in teks if (t or "").strip()]
    if not teks:
        return []
    body = json.dumps({"input": teks, "model": _model(), "input_type": input_type}).encode()
    req = urllib.request.Request(_URL, body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    return [d["embedding"] for d in data.get("data", [])]


def kemiripan(a: list[float], b: list[float]) -> float:
    """Cosine similarity dua vektor (0..1 untuk teks mirip)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
