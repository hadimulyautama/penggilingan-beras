"""Setiap catatan QC berisi dua bacaan; lima catatan melengkapi satu truk."""
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


def _isi(n: int, *, lamur: bool | None = None, sak: int | None = None):
    return dict(kadar_air_1=20 + n, kadar_air_2=20.5 + n,
                biji_hijau=("sedikit", "sedang", "banyak", "hampir_tidak_ada", "sedang")[n - 1],
                densiti=("padat", "sedang", "empuk", "padat", "sedang")[n - 1],
                lamur=lamur, jumlah_sak_lamur=sak)


async def test_lima_catatan_berisi_mutu_masing_masing_dan_rata_rata_sepuluh_bacaan(
    pg, pemakai, pemasok,
):
    from app.models import PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample, User
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah

    kode = "GB-QC-BASAH-01"
    await _buat_batch(pg, pemakai, pemasok, "basah", kode)
    hasil = []
    for n in range(1, 6):
        async with pg() as db:
            user = await db.get(User, pemakai.id)
            qc, rata, jumlah = await catat_qc_gabah(
                db, user=user, kode_batch=kode, **_isi(n, lamur=n % 2 == 1, sak=5 if n % 2 else 0))
            hasil.append((rata, jumlah, qc.id))
    assert [item[1] for item in hasil] == [1, 2, 3, 4, 5]
    assert hasil[-1][0] == pytest.approx(23.25)

    async with pg() as db:
        batch = (await db.execute(select(PurchaseBatch).where(
            PurchaseBatch.kode_batch == kode))).scalar_one()
        qc = (await db.execute(select(PurchaseBatchQc).where(
            PurchaseBatchQc.purchase_batch_id == batch.id))).scalar_one()
        entries = (await db.execute(select(PurchaseBatchQcSample).where(
            PurchaseBatchQcSample.purchase_batch_qc_id == qc.id
        ).order_by(PurchaseBatchQcSample.nomor_sampel))).scalars().all()
        assert len(entries) == 5
        assert batch.kadar_air_awal_persen == pytest.approx(23.25)
        assert qc.lamur is True and qc.jumlah_sak_lamur == 15
        assert [entry.nomor_sampel for entry in entries] == [1, 2, 3, 4, 5]
        assert [entry.biji_hijau for entry in entries] == [
            "sedikit", "sedang", "banyak", "hampir_tidak_ada", "sedang"]
        assert [entry.jumlah_sak_lamur for entry in entries] == [5, 0, 5, 0, 5]
        assert all(entry.input_by == pemakai.id for entry in entries)


async def test_qc_gabah_basah_wajib_memuat_lamur_dan_jumlah_sak(pg, pemakai, pemasok):
    from app.models import User
    from app.penggilingan.gudang1.services.qc_gabah import QcGabahError, catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "basah", "GB-QC-BASAH-02")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(QcGabahError, match="status Lamur"):
            await catat_qc_gabah(db, user=user, kode_batch="GB-QC-BASAH-02",
                                 **{k: v for k, v in _isi(1).items()
                                    if k not in {"lamur", "jumlah_sak_lamur"}})


async def test_qc_gabah_kering_tidak_menerima_komponen_lamur(pg, pemakai, pemasok):
    from app.models import User
    from app.penggilingan.gudang1.services.qc_gabah import QcGabahError, catat_qc_gabah

    await _buat_batch(pg, pemakai, pemasok, "kering", "GB-QC-KERING-01")
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(QcGabahError, match="tidak memiliki komponen Lamur"):
            await catat_qc_gabah(db, user=user, kode_batch="GB-QC-KERING-01",
                                 **_isi(1, lamur=False, sak=0))


async def test_qc_kering_satu_catatan_sukses_dan_catatan_ke_enam_ditolak(pg, pemakai, pemasok):
    from app.models import PurchaseBatchQc, PurchaseBatchQcSample, User
    from app.penggilingan.gudang1.services.qc_gabah import QcGabahError, catat_qc_gabah

    kode = "GB-QC-KERING-03"
    await _buat_batch(pg, pemakai, pemasok, "kering", kode)
    for n in range(1, 6):
        async with pg() as db:
            user = await db.get(User, pemakai.id)
            qc, rata, jumlah = await catat_qc_gabah(
                db, user=user, kode_batch=kode,
                **{k: v for k, v in _isi(n).items()
                   if k not in {"lamur", "jumlah_sak_lamur"}})
            assert jumlah == n
            if n == 1:
                assert rata == pytest.approx(21.25)
                assert qc.lamur is None and qc.jumlah_sak_lamur is None
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(QcGabahError, match="5 dari 5"):
            await catat_qc_gabah(db, user=user, kode_batch=kode,
                                 **{k: v for k, v in _isi(1).items()
                                    if k not in {"lamur", "jumlah_sak_lamur"}})
    async with pg() as db:
        qc = (await db.execute(select(PurchaseBatchQc))).scalar_one()
        entries = (await db.execute(select(PurchaseBatchQcSample).where(
            PurchaseBatchQcSample.purchase_batch_qc_id == qc.id))).scalars().all()
        assert len(entries) == 5


async def test_kartu_mutu_tetap_ada_sampai_catatan_kelima(pg, pemakai, pemasok):
    from app.services.berjalan import untuk_staff
    from app.models import User
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah

    kode = "GB-QC-KARTU-01"
    await _buat_batch(pg, pemakai, pemasok, "basah", kode)
    for n in range(6):
        async with pg() as db:
            daftar = await untuk_staff(db)
        kartu = next((x for x in daftar.meja if x.kode == kode), None)
        if n < 5:
            assert kartu is not None
            assert f"{n}/5" in kartu.isi
            if n:
                assert any(pilihan[0] == "qc_gabah_tutup" for pilihan in kartu.pilihan)
            async with pg() as db:
                user = await db.get(User, pemakai.id)
                await catat_qc_gabah(db, user=user, kode_batch=kode,
                                     **_isi(n + 1, lamur=False, sak=0))
        else:
            assert kartu is None


async def test_proses_qc_bisa_ditutup_setelah_satu_catatan(pg, pemakai, pemasok):
    from app.models import PurchaseBatchQc, User
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah, tutup_qc_gabah
    from app.services.berjalan import untuk_staff

    kode = "GB-QC-TUTUP-01"
    await _buat_batch(pg, pemakai, pemasok, "basah", kode)
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        await catat_qc_gabah(db, user=user, kode_batch=kode,
                             **_isi(1, lamur=False, sak=0))
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        qc, jumlah = await tutup_qc_gabah(db, user=user, kode_batch=kode,
                                            alasan="Truk harus segera diproses")
        assert jumlah == 1
        assert qc.ditutup_pada is not None
        assert qc.ditutup_by == pemakai.id
    async with pg() as db:
        daftar = await untuk_staff(db)
        assert not any(kartu.kode == kode for kartu in daftar.meja)
    async with pg() as db:
        user = await db.get(User, pemakai.id)
        with pytest.raises(ValueError, match="sudah ditutup"):
            await catat_qc_gabah(db, user=user, kode_batch=kode,
                                 **_isi(2, lamur=True, sak=1))
