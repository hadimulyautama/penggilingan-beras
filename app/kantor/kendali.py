"""Kendali layanan AI: lihat biaya/pemakaian & matikan/nyalakan (kill-switch).

- status/biaya  : via tool agen `status_biaya` ATAU pintasan kata di bot.
- matikan/nyalakan : pintasan kata DETERMINISTIK di bot (BUKAN tool agen) — harus
  bekerja walau AI mati (agen butuh LLM, jadi tak bisa menyalakan dirinya), dan
  hanya untuk admin/Direksi.
"""
from __future__ import annotations

from app.ai import guard

_YA = {"on", "1", "true", "ya", "aktif"}

NAMA_TOOL = {"status_biaya"}

TOOLS = [
    {
        "name": "status_biaya",
        "description": (
            "Lihat pemakaian & biaya layanan AI: status (nyala/mati), batas biaya "
            "bulanan, dan biaya yang sudah dikeluarkan bulan ini. Pakai untuk 'lihat "
            "spend', 'berapa biaya AI bulan ini', 'sisa budget AI'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def status_teks() -> str:
    s = await guard.status_biaya()
    cap = float(s.get("spend_cap_usd_bulan") or 0)
    spend = float(s.get("spend_bulan_ini_usd") or 0)
    mati = str(s.get("kill_switch") or "off").strip().lower() in _YA
    baris = ["🛑 Layanan AI: MATI (kill-switch aktif)" if mati else "🟢 Layanan AI: nyala"]
    if cap > 0:
        sisa = max(0.0, cap - spend)
        baris.append(f"💵 Biaya bulan ini: ${spend:.2f} / batas ${cap:.2f} (sisa ${sisa:.2f})")
    else:
        baris.append(f"💵 Biaya bulan ini: ${spend:.2f} (batas belum disetel)")
    return "\n".join(baris)


async def set_mati(mati: bool) -> None:
    """Matikan (True) / nyalakan (False) layanan AI via kill-switch."""
    await guard.set_konfig("kill_switch", "on" if mati else "off")


async def jalankan(name: str, args: dict, role: str) -> str:
    if name == "status_biaya":
        return await status_teks()
    return "Perintah kendali tak dikenal."
