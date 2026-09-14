"""Penanda keadaan Pos Produksi (`/miniapp/keadaan`) — di Postgres.

Penandanya dulu membulatkan `updated_at` tiket timbang ke DETIK. Tiket yang
dibuat lalu ditimbang kedua pada detik yang sama menghasilkan penanda yang
sama, jadi perubahan kedua tak pernah terlihat perangkat mana pun — hilang
selamanya, tanpa galat. Ditemukan lebih dulu di timbangan (b9a3789) oleh uji
yang menyimpan dua langkah berturut-turut. Ruas `versi` ikut dijaga (syarat
N-A-03): ponsel tahu berkasnya lama dari kanal yang sama.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES ('TB-UJI-01', :tanggal, 'MASUK', 'GABAH_BASAH', 'DUA_KALI', :supplier_id, 'Pak Uji',
            'B 1 UJ', 12000, :waktu, 9800, 0, 'TERBUKA', 'AKTIF')
    RETURNING id
""")


async def _penanda(pemakai) -> dict:
    from app.web.miniapp import keadaan

    return await keadaan(user=pemakai)


async def test_dua_perubahan_dalam_satu_detik_dua_penanda(pg, pemakai, pemasok):
    from app.database import now_local

    async with pg() as db:
        tid = (await db.execute(_SQL_TIKET, {
            "tanggal": now_local().date(), "supplier_id": pemasok.id,
            "waktu": datetime.now(timezone.utc)})).scalar_one()
        await db.commit()
    n0 = (await _penanda(pemakai))["n"]

    # Timbang kedua lalu koreksi — dua transaksi terpisah, detik yang sama.
    # Rumusnya `now()` seperti `onupdate=func.now()` milik modelnya.
    hasil = []
    for _ in range(2):
        async with pg() as db:
            await db.execute(text("UPDATE timbangan_transaksi SET updated_at = now() WHERE id = :t"),
                             {"t": tid})
            await db.commit()
        hasil.append((await _penanda(pemakai))["n"])
    n1, n2 = hasil
    assert n0 != n1, "timbang kedua tak menggerakkan penanda"
    assert n1 != n2, "perubahan kedua pada detik yang sama hilang"


async def test_penanda_membawa_versi(pg, pemakai):
    from app.web.tampilan import VERSI

    j = await _penanda(pemakai)
    assert j["versi"] == VERSI and "n" in j
