"""Kanal dorong `/api/aliran` — Tahap C rasa native, di Postgres.

Sesi B mengubah data (baris activity_logs — jalur yang memang dipantau
penanda), sesi A menerima DORONGAN tanpa meminta: pesan pertama datang
seketika saat tersambung, pesan berikutnya begitu penandanya bergerak.
Penandanya sama persis dengan /api/keadaan (nomor naik + mikrodetik tiket
timbang) dan membawa `versi`.
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.asyncio


class _Pendengar:
    """Sesi A: membaca aliran di tugas latar, supaya menunggu-dengan-batas
    tidak membatalkan generatornya (CancelledError menutup async generator)."""

    def __init__(self, gen):
        self.antrean: asyncio.Queue = asyncio.Queue()
        self.gen = gen
        self.tugas = asyncio.create_task(self._baca())

    async def _baca(self):
        async for potongan in self.gen:
            if potongan.startswith("data:"):
                await self.antrean.put(json.loads(potongan[len("data:"):].strip()))

    async def ambil(self, batas: float) -> dict:
        return await asyncio.wait_for(self.antrean.get(), batas)

    async def tutup(self):
        self.tugas.cancel()
        try:
            await self.tugas
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


async def test_sesi_b_mengubah_sesi_a_menerima_dorongan(pg, pemakai):
    from app.services.activity_log import log_activity
    from app.web import api
    from app.web.tampilan import VERSI

    a = _Pendengar(api.aliran_penanda(jeda=0.2))
    pertama = await a.ambil(3)
    assert pertama["versi"] == VERSI and pertama["n"]

    # Tak ada yang berubah: tak ada pesan (hanya denyut hidup, bukan data).
    with pytest.raises(asyncio.TimeoutError):
        await a.ambil(1.0)

    async with pg() as db:                      # sesi B
        await log_activity(db, table_name="purchase_batches", record_id=1,
                           action="INSERT", changed_by=pemakai.id)
        await db.commit()
    kedua = await a.ambil(3)
    assert kedua["n"] != pertama["n"]
    await a.tutup()
