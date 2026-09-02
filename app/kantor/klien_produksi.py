"""Klien HTTP ke API internal PRODUKSI — SATU-SATUNYA jalur Kantor ke data pabrik.

Kantor AI berdiri sebagai repo & service sendiri; ia tidak mengimpor kode
produksi. Tiga kebutuhan nyata (delegasi pertanyaan ke agen pabrik, simulasi HPP,
ringkasan operasional untuk briefing pagi) dilayani lewat `/internal/produksi/*`.

Konfigurasi (env):
  PRODUKSI_API_URL    alamat service produksi, mis. https://xxx.up.railway.app
                      (selama Kantor masih satu proses dgn produksi: http://127.0.0.1:8000)
  PRODUKSI_API_TOKEN  harus sama dengan INTERNAL_API_TOKEN di sisi produksi.

Semua fungsi FAIL-SOFT: bila belum dikonfigurasi / service produksi sedang mati,
lempar `ProduksiTakTersedia` dengan pesan siap-tampil, bukan traceback.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("kantor.klien_produksi")


class ProduksiTakTersedia(Exception):
    """Service produksi belum dikonfigurasi / tak bisa dihubungi."""


def terkonfigurasi() -> bool:
    return bool(settings.produksi_api_url and settings.produksi_api_token)


async def _minta(metode: str, path: str, *, json: dict | None = None) -> dict:
    if not terkonfigurasi():
        raise ProduksiTakTersedia(
            "Sambungan ke sistem produksi belum diatur (PRODUKSI_API_URL/TOKEN)."
        )
    url = settings.produksi_api_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=settings.produksi_api_timeout) as c:
            r = await c.request(
                metode, url, json=json,
                headers={"X-Internal-Token": settings.produksi_api_token},
            )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        kode = e.response.status_code
        log.warning("API produksi menolak %s (%s)", path, kode)
        if kode in (403, 404):
            raise ProduksiTakTersedia(
                "Sistem produksi menolak permintaan (token/API internal belum aktif)."
            ) from e
        raise ProduksiTakTersedia("Sistem produksi sedang bermasalah.") from e
    except httpx.HTTPError as e:
        log.warning("API produksi tak terjangkau %s", path, exc_info=True)
        raise ProduksiTakTersedia("Sistem produksi sedang tak bisa dihubungi.") from e


async def tanya(pertanyaan: str, *, role: str, financial: bool) -> str:
    """Delegasikan pertanyaan pabrik ke AI Agent produksi (read-only)."""
    data = await _minta("POST", "/internal/produksi/tanya", json={
        "pertanyaan": pertanyaan, "role": role, "financial": financial,
    })
    return (data.get("teks") or "").strip()


async def simulasi_hpp(
    harga_gabah: float | None, rendemen_persen: float | None, *,
    kondisi: str = "basah", langsung_silo: bool = False,
    berat_bahan: float | None = None, berat_hasil: float | None = None,
) -> str:
    """What-if HPP dari harga gabah & rendemen (tarif resmi ada di sisi produksi)."""
    data = await _minta("POST", "/internal/produksi/hpp", json={
        "harga_gabah": harga_gabah, "rendemen_persen": rendemen_persen,
        "kondisi": kondisi, "langsung_silo": langsung_silo,
        "berat_bahan": berat_bahan, "berat_hasil": berat_hasil,
    })
    return (data.get("teks") or "").strip()


async def operasional() -> dict:
    """Ringkasan operasional hari ini (gabah masuk, pengeringan, silo, giling, PK)."""
    return await _minta("GET", "/internal/produksi/operasional")
