"""Pengaman biaya LLM (Tahap 0): kill-switch, spend-cap, jejak pemakaian.

SEMUA panggilan LLM sebaiknya lewat `panggil()` agar:
  - dihentikan bila kill-switch aktif (LayananLLMMati),
  - dihentikan bila spend bulan berjalan ≥ batas (BatasBiayaLLM),
  - pemakaian token tercatat (dasar pantauan biaya),
  - error 'batas pemakaian API' diubah jadi BatasBiayaLLM (untuk degradasi anggun).

Best-effort: kegagalan baca konfig / pencatatan TAK boleh menambah kegagalan
panggilan (fail-open untuk konfig, fail-safe untuk pencatatan).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import anthropic
from sqlalchemy import func, select

from app.ai.claude_client import get_client
from app.database import SessionLocal
from app.kantor.models import KantorConfig, KantorLLMUsage

log = logging.getLogger("ai.guard")

# USD per 1 juta token → (input, output). Sumber: harga API Anthropic.
_HARGA: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}
_DEFAULT_HARGA = (3.0, 15.0)

_YA = {"on", "1", "true", "ya", "aktif"}


class LayananLLMMati(Exception):
    """Kill-switch aktif — layanan LLM sengaja dimatikan sementara."""


class BatasBiayaLLM(Exception):
    """Batas biaya bulanan tercapai / API menolak karena batas pemakaian."""


def est_biaya(model: str, input_tokens: int, output_tokens: int) -> float:
    """Perkiraan biaya USD sebuah panggilan dari jumlah token."""
    inp, out = _HARGA.get(model, _DEFAULT_HARGA)
    return (input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out


async def _konfig(kunci: str, default: str | None = None) -> str | None:
    try:
        async with SessionLocal() as s:
            nilai = (
                await s.execute(
                    select(KantorConfig.nilai).where(KantorConfig.kunci == kunci)
                )
            ).scalar_one_or_none()
            return nilai if nilai is not None else default
    except Exception:
        return default  # fail-open: jangan blokir hanya karena konfig tak terbaca


async def set_konfig(kunci: str, nilai: str) -> None:
    """Setel/ubah satu konfig runtime (upsert). Mis. kill-switch & spend-cap."""
    async with SessionLocal() as s:
        row = (
            await s.execute(select(KantorConfig).where(KantorConfig.kunci == kunci))
        ).scalar_one_or_none()
        if row is None:
            s.add(KantorConfig(kunci=kunci, nilai=nilai))
        else:
            row.nilai = nilai
        await s.commit()


async def status_biaya() -> dict:
    """Ringkasan untuk pemantauan: kill-switch, cap, spend bulan berjalan."""
    return {
        "kill_switch": (await _konfig("kill_switch", "off")),
        "spend_cap_usd_bulan": (await _konfig("spend_cap_usd_bulan", "0")),
        "spend_bulan_ini_usd": round(await _spend_bulan_ini(), 4),
    }


async def _spend_bulan_ini() -> float:
    try:
        awal = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        async with SessionLocal() as s:
            total = (
                await s.execute(
                    select(func.coalesce(func.sum(KantorLLMUsage.est_biaya_usd), 0)).where(
                        KantorLLMUsage.created_at >= awal
                    )
                )
            ).scalar_one()
            return float(total or 0)
    except Exception:
        return 0.0  # fail-open


async def _catat(model: str, pemanggil: str, in_tok: int, out_tok: int, status: str) -> None:
    try:
        async with SessionLocal() as s:
            s.add(
                KantorLLMUsage(
                    model=model,
                    pemanggil=(pemanggil or "?")[:60],
                    input_tokens=int(in_tok or 0),
                    output_tokens=int(out_tok or 0),
                    est_biaya_usd=est_biaya(model, int(in_tok or 0), int(out_tok or 0)),
                    status=status,
                )
            )
            await s.commit()
    except Exception as e:  # pragma: no cover - best effort
        log.warning("gagal catat pemakaian LLM: %s", e)


async def periksa_boleh() -> None:
    """Raise bila kill-switch aktif atau spend bulan ini ≥ batas."""
    ks = (await _konfig("kill_switch", "off") or "off").strip().lower()
    if ks in _YA:
        raise LayananLLMMati("Layanan AI dimatikan sementara (kill-switch).")
    try:
        cap = float(await _konfig("spend_cap_usd_bulan", "0") or 0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap > 0:
        spend = await _spend_bulan_ini()
        if spend >= cap:
            raise BatasBiayaLLM(
                f"Batas biaya bulanan tercapai (${spend:.2f} ≥ ${cap:.2f})."
            )


def _adalah_batas_pemakaian(err: Exception) -> bool:
    msg = str(getattr(err, "message", "") or err).lower()
    return any(t in msg for t in ("usage limit", "usage limits", "credit balance"))


async def panggil(*, model: str, pemanggil: str = "?", **kwargs):
    """Panggilan LLM TERJAGA — pengganti `get_client().messages.create()`.

    Contoh:
        resp = await guard.panggil(model=settings.agent_model, pemanggil="agent",
                                   max_tokens=1024, messages=[...])
    """
    await periksa_boleh()
    try:
        resp = await get_client().messages.create(model=model, **kwargs)
    except anthropic.APIStatusError as e:
        if _adalah_batas_pemakaian(e):
            await _catat(model, pemanggil, 0, 0, "blocked")
            raise BatasBiayaLLM(str(getattr(e, "message", "") or e)) from e
        raise
    u = getattr(resp, "usage", None)
    await _catat(
        model,
        pemanggil,
        getattr(u, "input_tokens", 0) or 0,
        getattr(u, "output_tokens", 0) or 0,
        "ok",
    )
    return resp
