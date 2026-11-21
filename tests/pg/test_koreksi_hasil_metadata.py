"""Pembacaan kelompok harus setara dengan jalur saldo per sumber yang lama."""
import pytest
from sqlalchemy import select
from app import performa
from app.models import User, PkGudang2Intake
from app.services import koreksi_bahan_berjalan as koreksi
from tests.pg.test_koreksi_bahan_berjalan import running, dunia, batch_baru


@pytest.mark.asyncio
async def test_konteks_kelompok_mempertahankan_seluruh_nilai_dan_sidik(pg, running, dunia, monkeypatch):
    uid, kode, _, _ = running
    async with pg() as db:
        for i in range(6):
            await batch_baru(db, dunia, n=20, w=None if i == 2 else 998,
                            kode=f'PKB-METADATA-{i}', sumber='perkiraan' if i == 2 else 'timbangan')
    pembaca_lama = koreksi.g2_sumber
    async with pg() as db:
        intakes = (await db.scalars(select(PkGudang2Intake).order_by(PkGudang2Intake.id))).all()
        metadata = await koreksi._g2_metadata_banyak(db, intakes)
        for intake in intakes:
            performa.lupakan_cache()
            lama = await pembaca_lama(db, intake)
            performa.lupakan_cache()
            kelompok = await pembaca_lama(db, intake, metadata=metadata[intake.id])
            assert kelompok == lama
    async with pg() as db:
        performa.lupakan_cache()
        kelompok = await koreksi.konteks(db, jenis='sosoh', kode=kode, user=await db.get(User, uid))
    async def tanpa_metadata(db, intake, **_):
        return await pembaca_lama(db, intake)
    monkeypatch.setattr(koreksi, 'g2_sumber', tanpa_metadata)
    async with pg() as db:
        performa.lupakan_cache()
        lama = await koreksi.konteks(db, jenis='sosoh', kode=kode, user=await db.get(User, uid))
    assert kelompok == lama  # termasuk dasar, saldo, satuan, urutan, sumber dan dependensi
