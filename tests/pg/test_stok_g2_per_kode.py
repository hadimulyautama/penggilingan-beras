"""`stok.pk_gudang2` — satu kartu per kode bahan, dibuktikan di Postgres.

Keputusan pemilik 5 Oktober 2026: kartu Tumpukan Gudang 2 berhenti dibungkus
jadi satu kartu beranak dan jadi satu kartu PER PEMASUKAN (`stok.LotPkG2`),
dengan mutu langsung terlihat. Dua permintaan susulan pada hari yang sama
menambah dua fakta lagi ke kartu itu: *"berapa yang sudah masuk silo dari
berat awal yang ada"* dan *"kondisi kl atau ks."*

Berkas ini membuktikan jalur SUNGGUHAN — `masukkan_pk_luar`/
`create_internal_transfer` lalu `pk_gudang2` membacanya kembali — bukan
cuma struktur templatnya (itu `tests/test_view.py`).
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dunia(pg, pemakai):
    """Gudang 1 + Gudang 2, satu lot giling sendiri (gabah basah → KS, QC
    tercatat) dipindah ke tumpukan G2, dan satu PK beli luar (jenis `kl`,
    QC lengkap) juga di tumpukan."""
    from app.database import now_local
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch,
                            Silo, Supplier, User, Warehouse)
    from app.penggilingan.gudang1.services.milling import log_qc_milling
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import log_pk_qc, masukkan_pk_luar
    from app.services.transfer import create_internal_transfer
    from sqlalchemy import select

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        silo_g1 = Silo(nama_silo="Silo Selepan", warehouse_id=g1.id)
        db.add(silo_g1)
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        u = await db.get(User, pemakai.id)
        # Admin: `log_pk_qc` menuntutnya (`PERAN_ADMIN_KEATAS`) sementara
        # `masukkan_pk_luar`/`create_internal_transfer`/`pindah_tumpukan_ke_silo`
        # tak menjaga peran sama sekali di lapisan servis (gerbangnya di
        # rute) — jadi satu user admin cukup untuk seluruh fixture ini.
        u.role = "admin"
        u.default_warehouse_id = g2.id
        pemasok_gabah = Supplier(nama_supplier="Pak Tani Basah")
        pemasok_pk = Supplier(nama_supplier="UD Kode Bahan")
        db.add_all([pemasok_gabah, pemasok_pk])
        await db.flush()

        gb = PurchaseBatch(
            kode_batch="GB-KODE-01", supplier_id=pemasok_gabah.id,
            berat_total_kg=10_000, kondisi_gabah="basah",
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, flag_unverified=False, sumber_berat="timbangan")
        db.add(gb)
        await db.flush()
        proc = MillingProcess(
            kode_proses="LOT-KODE-01", status="selesai", silo_id=silo_g1.id,
            berat_gabah_masuk_kg=10_000, purchase_batch_id=gb.id,
            waktu_mulai=now_local(), waktu_selesai=now_local(), created_by=u.id)
        db.add(proc)
        await db.flush()
        # Hasil giling — tanpa ini `create_internal_transfer` menolak dengan
        # "hasil giling belum dicatat": stok PK siap kirim dihitung dari
        # produksi (`MillingProgressLog`), bukan dari gabah masuk.
        db.add(MillingProgressLog(milling_process_id=proc.id, berat_kumulatif_kg=8_000,
                                  waktu_update=now_local(), input_by=u.id))
        db.add(PkPurchaseBatch(
            kode_batch="PKB-KODE-01", supplier_id=pemasok_pk.id,
            berat_total_kg=9_000, jenis_pk="kl",
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)

        await log_qc_milling(db, user=u, kode_proses="LOT-KODE-01",
                             kadar_air=13.2, broken=4.0, susut=1.5, kondisi=None)
        giling = await create_internal_transfer(
            db, user=u, kode_proses="LOT-KODE-01", lokasi_tujuan="ditumpuk",
            berat=6_000)

        beli = await masukkan_pk_luar(db, user=u, kode="PKB-KODE-01", tujuan="ditumpuk")
        await log_pk_qc(db, user=u, kode="PKB-KODE-01", kadar_air=13.8,
                        broken=3.5, penyusutan_persen=1.9, butir_kuning="sedang",
                        gabah="bersih", merang="sedikit", catatan_lab="Uji kode bahan")

        from app.models import PkGudang2Intake
        giling_intake_id = (await db.execute(
            select(PkGudang2Intake.id)
            .where(PkGudang2Intake.internal_transfer_id == giling.transfer.id)
        )).scalar_one()

        return {"user": u, "g1": g1.id, "g2": g2.id,
                "giling_intake_id": giling_intake_id, "beli_intake_id": beli.intake.id}


async def test_kartu_giling_sendiri_menyebut_asal_mutu_dan_kelas(pg, dunia):
    """Giling sendiri: judul "Giling sendiri · kode", mutu dari QC giling
    (`log_qc_milling`), kelas KS karena gabah sumbernya basah."""
    from app.services import stok

    async with pg() as db:
        kartu = await stok.pk_gudang2(db)
    giling = next(k for k in kartu if k.intake_id == dunia["giling_intake_id"])
    assert giling.kode == "Giling sendiri · LOT-KODE-01"
    assert giling.kelas == "KS", "gabah sumbernya basah — kelasnya KS, sama dengan Gudang 1"
    assert ("Kadar air", "13,2%") in giling.mutu
    assert ("Butir patah", "4,0%") in giling.mutu
    assert ("Susut", "1,5%") in giling.mutu
    assert giling.tersedia == pytest.approx(6_000)
    assert giling.berat_awal == pytest.approx(6_000)
    assert giling.bobot_final is True


async def test_kartu_beli_luar_menyebut_asal_mutu_dan_kelas(pg, dunia):
    """Beli luar: judul "pemasok · kode batch", mutu DARI `log_pk_qc`
    (ketujuh elemen, termasuk yang kualitatif & catatan lab), kelas dari
    `jenis_pk` lewat label yang SAMA dengan katalog `catat_pk_luar`."""
    from app.services import stok

    async with pg() as db:
        kartu = await stok.pk_gudang2(db)
    beli = next(k for k in kartu if k.intake_id == dunia["beli_intake_id"])
    assert beli.kode == "UD Kode Bahan · PKB-KODE-01"
    assert beli.kelas == "KL"
    assert ("Kadar air", "13,8%") in beli.mutu
    assert ("Butir patah", "3,5%") in beli.mutu
    assert ("Susut", "1,9%") in beli.mutu
    assert ("Butir kuning", "Sedang") in beli.mutu
    assert ("Gabah", "Bersih") in beli.mutu
    assert ("Merang", "Sedikit") in beli.mutu
    assert ("Catatan lab", "Uji kode bahan") in beli.mutu
    assert beli.tersedia == pytest.approx(9_000)
    assert beli.berat_awal == pytest.approx(9_000)


async def test_sudah_ke_silo_dihitung_dari_selisih_berat_awal(pg, dunia):
    """⭐ "berapa yang sudah masuk silo dari berat awal yang ada" — kartu
    tak menyimpan angka itu sendiri (lihat `LotPkG2.berat_awal`); ia
    DITURUNKAN dari `berat_awal - tersedia`, sama seperti templatnya."""
    from app.models import User
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    from app.services import stok

    async with pg() as db:
        u = await db.get(User, dunia["user"].id)
        await pindah_tumpukan_ke_silo(
            db, user=u, intake_id=dunia["beli_intake_id"], nama_silo="A", berat=3_500)

    async with pg() as db:
        kartu = await stok.pk_gudang2(db)
    beli = next(k for k in kartu if k.intake_id == dunia["beli_intake_id"])
    assert beli.berat_awal == pytest.approx(9_000), "berat awal tak boleh ikut berubah"
    assert beli.tersedia == pytest.approx(5_500)
    sudah_ke_silo = beli.berat_awal - beli.tersedia
    assert sudah_ke_silo == pytest.approx(3_500)

    # Dan pemasukan yang BELUM tersentuh tak punya apa pun untuk dilaporkan
    # di baris ini — bukan "0 dari 6.000", baris itu memang tak ada gunanya.
    giling = next(k for k in kartu if k.intake_id == dunia["giling_intake_id"])
    assert giling.berat_awal == giling.tersedia


async def test_berat_belum_diketahui_tak_punya_berat_awal(pg, pemakai):
    """P6-02: truk yang belum ditimbang kedua tak punya angka sama sekali.
    `berat_awal` harus 0.0 — bukan sisa yang kebetulan nol — supaya templat
    tak menggambar baris "Sudah ke silo" untuk pemasukan yang beratnya
    sendiri belum ada."""
    from app.database import now_local
    from app.models import PkGudang2Intake, Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.services import stok

    async with pg() as db:
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(g2)
        await db.flush()
        db.add(Silo(nama_silo="Silo A", warehouse_id=g2.id))
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        s = Supplier(nama_supplier="UD Belum Timbang")
        db.add(s)
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-BELUM-01", supplier_id=s.id, berat_total_kg=None,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="baru", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)
        r = await masukkan_pk_luar(db, user=u, kode="PKB-BELUM-01", tujuan="ditumpuk")
        intake = await db.get(PkGudang2Intake, r.intake.id)
        assert intake.berat_kg is None, "pengaturan uji salah — beratnya sudah terisi"

    async with pg() as db:
        kartu = await stok.pk_gudang2(db)
    baris = next((k for k in kartu if k.intake_id == r.intake.id), None)
    assert baris is not None, "pemasukan tanpa berat tetap harus terlihat"
    assert baris.bobot_final is False
    assert baris.berat_awal == 0.0
    assert baris.tersedia == 0.0
