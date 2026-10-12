"""QC gabah tercatat per truk lewat lima sampel dan sepuluh pembacaan air."""
from datetime import date

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _buat_batch(pg, pemakai, pemasok, kondisi: str, kode: str):
    from app.database import now_local
    from app.models import PurchaseBatch, User

    async with pg() as db:
        user = await db.get(User, pemakai.id)
        batch = PurchaseBatch(
            kode_batch=kode, supplier_id=pemasok.id, berat_total_kg=10_000,
            kondisi_gabah=kondisi, tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=user.id, status_batch="baru",
            sumber_berat="manual",
        )
        db.add(batch)
        await db.commit()


def _sampel():
    return [
        {"kadar_air_1": 10 + i, "kadar_air_2": 11 + i}
        for i in range(1, 6)
    ]


async def test_lima_sampel_dua_pembacaan_rata_ratakan_sepuluh_data(
    pg, pemakai, pemasok,
):
    from app.models import PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample, User
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "basah", "GB-QC-BASAH-01")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        _, rata = await catat_qc_gabah(
            db, user=user, kode_batch="GB-QC-BASAH-01", sampel=_sampel(),
            biji_hijau="sedang", densiti="padat", lamur=True, jumlah_sak_lamur=3,
        )
    assert rata == pytest.approx(13.5)
    async with pg() as db:
        batch = (await db.execute(select(PurchaseBatch)
                                  .where(PurchaseBatch.kode_batch == "GB-QC-BASAH-01"))).scalar_one()
        qc = (await db.execute(select(PurchaseBatchQc)
                               .where(PurchaseBatchQc.purchase_batch_id == batch.id))).scalar_one()
        samples = (await db.execute(select(PurchaseBatchQcSample)
                                    .where(PurchaseBatchQcSample.purchase_batch_qc_id == qc.id)
                                    .order_by(PurchaseBatchQcSample.nomor_sampel))).scalars().all()
        assert len(samples) == 5
        assert batch.kadar_air_awal_persen == pytest.approx(13.5)
        assert qc.lamur is True and qc.jumlah_sak_lamur == 3
        assert [s.nomor_sampel for s in samples] == [1, 2, 3, 4, 5]


async def test_qc_gabah_basah_wajib_memuat_lamur_dan_jumlah_sak(pg, pemakai, pemasok):
    from app.models import User
    from app.penggilingan.gudang1.services.qc_gabah import QcGabahError, catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "basah", "GB-QC-BASAH-02")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(QcGabahError, match="status Lamur"):
            await catat_qc_gabah(db, user=user, kode_batch="GB-QC-BASAH-02",
                                 sampel=_sampel(), biji_hijau="sedang", densiti="padat")


async def test_qc_gabah_kering_tidak_menerima_komponen_lamur(pg, pemakai, pemasok):
    from app.models import User
    from app.penggilingan.gudang1.services.qc_gabah import QcGabahError, catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "kering", "GB-QC-KERING-01")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(QcGabahError, match="tidak memiliki komponen Lamur"):
            await catat_qc_gabah(db, user=user, kode_batch="GB-QC-KERING-01",
                                 sampel=_sampel(), biji_hijau="sedang", densiti="padat",
                                 lamur=False, jumlah_sak_lamur=0)


async def test_qc_gabah_kering_sukses_tanpa_lamur(pg, pemakai, pemasok):
    from app.models import PurchaseBatchQc, User
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "kering", "GB-QC-KERING-03")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        qc, rata = await catat_qc_gabah(
            db, user=user, kode_batch="GB-QC-KERING-03", sampel=_sampel(),
            biji_hijau="sedang", densiti="padat",
        )
        assert rata == pytest.approx(13.5)
        assert qc.lamur is None and qc.jumlah_sak_lamur is None
        assert (await db.execute(select(PurchaseBatchQc.id).where(
            PurchaseBatchQc.purchase_batch_id == qc.purchase_batch_id
        ))).scalar_one() == qc.id


async def test_qc_gabah_mewajibkan_tepat_lima_sampel(pg, pemakai, pemasok):
    from app.models import User
    from app.penggilingan.gudang1.services.qc_gabah import QcGabahError, catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "kering", "GB-QC-KERING-02")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(QcGabahError, match="tepat 5 sampel"):
            await catat_qc_gabah(db, user=user, kode_batch="GB-QC-KERING-02",
                                 sampel=_sampel()[:4], biji_hijau="sedang", densiti="padat")
