"""PK tumpukan adalah stok yang bisa keluar; PK di silo adalah bahan proses.

Pemilik dan saldo tetap diperiksa untuk penjualan serta pengambilan jasa.
Riwayat pengeluaran silo lama tetap harus dapat dibaca dan dibatalkan.
"""
from __future__ import annotations
from tests.pg.formulir import cap_formulir

from datetime import date
from sqlalchemy import select

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai):
    """Gudang 1 & 2, satu silo PK Gudang 2 ("C"), superadmin, dua pesanan
    jasa (Bu Sri, Pak Budi) — masing-masing pelanggan & pesanan sendiri."""
    from sqlalchemy import select

    from app.models import Jasa, Pelanggan, Silo, User, Warehouse

    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
            await db.flush()
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
            db.add(g1)
            await db.flush()
        silo_c = Silo(nama_silo="Silo C", warehouse_id=g2.id, status="kosong")
        silo_g1 = Silo(nama_silo="Silo G1-X", warehouse_id=g1.id, status="kosong")
        db.add_all([silo_c, silo_g1])
        await db.flush()

        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        u.role = "superadmin"      # satu orang menempuh semua jalan di uji ini

        bu_sri = Pelanggan(nama_pelanggan="Bu Sri")
        pak_budi = Pelanggan(nama_pelanggan="Pak Budi")
        db.add_all([bu_sri, pak_budi])
        await db.flush()
        jasa_a = Jasa(kode="JAS-2610-010", pelanggan_id=bu_sri.id, status="berjalan")
        jasa_b = Jasa(kode="JAS-2610-011", pelanggan_id=pak_budi.id, status="berjalan")
        db.add_all([jasa_a, jasa_b])
        await db.commit()
        return {"g1": g1.id, "g2": g2.id, "silo_c": silo_c.id,
                "silo_g1": silo_g1.id, "user": u.id,
                "jasa_a": jasa_a.id, "jasa_b": jasa_b.id,
                "pelanggan_a": bu_sri.id, "pelanggan_b": pak_budi.id}


async def _masuk_tumpukan(pg, user_id: int, kode: str, kg: float,
                          jasa_id: int | None, supplier_id: int | None = None) -> int:
    """PK luar (titipan `jasa_id`, atau pabrik bila None) → tumpukan G2.

    → id intake-nya, supaya bisa dipindah ke silo atau diambil langsung.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar

    async with pg() as db:
        u = await db.get(User, user_id)
        db.add(PkPurchaseBatch(
            kode_batch=kode, jasa_id=jasa_id, supplier_id=supplier_id,
            berat_total_kg=kg,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
    async with pg() as db:
        u = await db.get(User, user_id)
        r = await masukkan_pk_luar(db, user=u, kode=kode, tujuan="ditumpuk")
        return r.intake.id


async def _pindah_ke_silo(pg, user_id: int, intake_id: int, silo_nama: str,
                          berat: float) -> None:
    from app.models import User
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo

    async with pg() as db:
        u = await db.get(User, user_id)
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=intake_id,
                                      nama_silo=silo_nama, berat=berat)


async def _perintah_lama(db, *, user, jasa_id, baris):
    """Data perintah sebelum larangan PK G2, bukan jalur penerbitan baru.

    Pemuat dan pembaca saldo tetap memakai layanan sungguhan. Menghapus
    penjaga riwayat hanya karena formulir baru ditutup bisa mengembalikan
    barang yang sudah dikirim ke angka stok.
    """
    from app.services import barang_keluar as bk
    if all(b.silo_id is None for b in baris):
        return await bk.buat_perintah(db, user=user, jasa_id=jasa_id, baris=baris)
    from types import SimpleNamespace
    from sqlalchemy import func
    from app.database import now_local
    from app.models import Jasa
    from app.penggilingan.inventory.models import OutgoingItem, OutgoingRecord

    pesanan = await db.get(Jasa, jasa_id)
    nomor = await db.scalar(select(func.count(OutgoingRecord.id)))
    rec = OutgoingRecord(
        kode=f"OUT-LAMA-{nomor + 1}", jasa_id=jasa_id,
        pelanggan_id=pesanan.pelanggan_id, status="perintah",
        tanggal=now_local().date(), waktu=now_local(), input_by=user.id,
        diperintah_oleh=user.id, waktu_perintah=now_local())
    db.add(rec)
    await db.flush()
    items = []
    for b in baris:
        assert b.tipe == "pk_g2"
        it = OutgoingItem(
            outgoing_record_id=rec.id, item_type=b.tipe, silo_id=b.silo_id,
            jasa_id=jasa_id, berat_perintah_kg=b.berat_kg,
            berat_kg=0, jumlah_karung=0)
        db.add(it)
        items.append(it)
    await db.commit()
    return SimpleNamespace(rec=rec, baris=items)


@pytest.mark.parametrize("tempat", ["tumpukan", "silo"])
@pytest.mark.parametrize("pemilik", ["jasa", "pabrik"])
async def test_perintah_pk_g2_tumpukan_boleh_silo_ditolak(pg, pabrik, pemasok,
                                                          tempat, pemilik):
    from app.models import User
    from sqlalchemy import func
    from fastapi import HTTPException
    from app.penggilingan.inventory.models import OutgoingRecord
    from app.web.aksi_inventory import _satu_baris
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang2.service import hitung_stok_silo, hitung_stok_tumpukan

    jid = pabrik["jasa_a"] if pemilik == "jasa" else None
    intake = await _masuk_tumpukan(pg, pabrik["user"], "PKB-LARANG", 2_000,
                                   jid, pemasok.id if jid is None else None)
    sid = None
    if tempat == "silo":
        await _pindah_ke_silo(pg, pabrik["user"], intake, "C", 2_000)
        sid = pabrik["silo_c"]
    async with pg() as db:
        async def perintah():
            return await bk.buat_perintah(db, user=await db.get(User, pabrik["user"]),
                jasa_id=jid, pelanggan_id=pabrik["pelanggan_a"],
                baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=sid, berat_kg=1_000)])
        if tempat == "silo":
            with pytest.raises(bk.BarangKeluarError, match="bahan proses"):
                await perintah()
        else:
            hasil = await perintah()
            assert hasil.baris[0].berat_kg == 0
            await bk.muat_semua(db, user=await db.get(User, pabrik["user"]), rec_id=hasil.rec.id)
    async with pg() as db:
        saldo = (await hitung_stok_silo(db, sid) if sid is not None
                 else await hitung_stok_tumpukan(db))
        assert saldo == (2_000 if tempat == "silo" else 1_000)
        assert await db.scalar(select(func.count(OutgoingRecord.id))) == (0 if sid is not None else 1)
        pilihan = "g2:tumpukan" if sid is None else f"g2:silo:{sid}"
        if jid is not None:
            pilihan += f"@{jid}"
        if sid is not None:
            with pytest.raises(HTTPException) as e:
                await _satu_baris(db, pilihan, 1_000)
            assert e.value.status_code == 400
            assert "bahan proses" in e.value.detail
        else:
            b = await _satu_baris(db, pilihan, 1_000)
            assert b.tipe == "pk_g2" and b.silo_id is None and b.jasa_id == jid


# ───────────────── Tumpukan: ambil penuh, pesanan jadi bisa ditutup ─────────────────

async def test_riwayat_ambil_penuh_dari_tumpukan_mengosongkan_stok_dan_menutup_pesanan(pg, pabrik):
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.jasa import boleh_ditutup, sisa_jasa

    await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-01", 7_000, pabrik["jasa_a"])

    async with pg() as db:
        sisa = await sisa_jasa(db, pabrik["jasa_a"])
        assert sisa.pk_g2_kg == 7_000
        boleh, sebab = await boleh_ditutup(db, pabrik["jasa_a"])
        assert not boleh and "PK Gudang 2" in sebab

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await _perintah_lama(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=None, berat_kg=7_000)])
        rec_id = r.rec.id
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        from app.penggilingan.gudang2.service import hitung_stok_tumpukan
        assert await hitung_stok_tumpukan(db, pemilik="jasa") == 0
        sisa = await sisa_jasa(db, pabrik["jasa_a"])
        assert sisa.pk_g2_kg == 0
        boleh, sebab = await boleh_ditutup(db, pabrik["jasa_a"])
        assert boleh, sebab


async def test_riwayat_kartu_tumpukan_di_stok_berkurang_sesudah_diambil(pg, pabrik):
    """Laporan lapangan 12 Oktober 2026: "pak pras juga ada punya barang di
    stok pk jasa. kenapa tidak ada di pilihan?" — kartu PK Gudang 2 di
    `/stok`/`/stok-pk-jasa` (`stok.pk_gudang2`) dulu cuma menyaring yang
    sudah DIPINDAH ke silo, tak pernah yang sudah DIAMBIL pemiliknya lewat
    perintah barang keluar — picker "Barang yang diambil" sudah benar
    (`hitung_stok_tumpukan` menyaring `keluar`), tapi kartunya tetap
    menampilkan PK yang sudah tak ada lagi di lantai.
    """
    from app.models import User
    from app.services import barang_keluar as bk
    from app.services.stok import pk_gudang2

    await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-02", 5_000, pabrik["jasa_a"])

    async with pg() as db:
        kartu = await pk_gudang2(db)
        satu = next(k for k in kartu if k.pemilik and "JAS" in k.pemilik)
        assert satu.tersedia == 5_000

    # Ambil SEBAGIAN — kartunya wajib ikut menyusut, bukan tetap 5.000.
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await _perintah_lama(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=None, berat_kg=3_000)])
        rec_id = r.rec.id
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        kartu = await pk_gudang2(db)
        satu = next(k for k in kartu if k.pemilik and "JAS" in k.pemilik)
        assert satu.tersedia == 2_000, \
            "kartu Stok tak ikut berkurang sesudah PK-nya diambil"

    # Ambil SISANYA — kartunya wajib HILANG, bukan nol lalu diam-diam negatif.
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r2 = await _perintah_lama(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=None, berat_kg=2_000)])
        rec2_id = r2.rec.id
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec2_id)

    async with pg() as db:
        kartu = await pk_gudang2(db)
        assert not any(k.pemilik and "JAS" in k.pemilik for k in kartu), \
            "kartu yang sudah habis diambil masih terdaftar"


# ───────────────────────── Silo: ambil sebagian ─────────────────────────

async def test_riwayat_ambil_sebagian_dari_silo_mengurangi_stok_persis(pg, pabrik):
    from app.models import User
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang2.service import hitung_stok_silo

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-02", 10_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 10_000)

    async with pg() as db:
        assert await hitung_stok_silo(db, pabrik["silo_c"], pemilik="jasa") == 10_000

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await _perintah_lama(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                    berat_kg=4_000)])
        rec_id = r.rec.id
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        assert await hitung_stok_silo(db, pabrik["silo_c"], pemilik="jasa") == 6_000
        assert await hitung_stok_silo(db, pabrik["silo_c"]) == 6_000


async def test_pk_g2_tak_bisa_ditambahkan_ke_perintah_lama(pg, pabrik):
    """Larangan penerbitan juga berlaku untuk penambahan barang."""
    from app.models import User
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang2.service import hitung_stok_silo

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-08", 10_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 10_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await _perintah_lama(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                    berat_kg=2_000)])
        rec_id = r.rec.id

    # Baris KEDUA, barang yang SAMA (silo C, pemiliknya jasa_a juga) —
    # ditambahkan ke PERINTAH YANG SAMA lewat tambah_baris, bukan buat_perintah.
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        with pytest.raises(bk.BarangKeluarError, match="tidak bisa ditambahkan"):
            await bk.tambah_baris(
                db, user=u, rec_id=rec_id,
                baris=bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                       berat_kg=3_000))

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        assert await hitung_stok_silo(db, pabrik["silo_c"], pemilik="jasa") == 8_000


async def test_riwayat_defisit_toleransi_silo_tidak_memotong_stok_pemilik_berikutnya(
        pg, pabrik, pemasok):
    """Selisih timbang 0,5 kg yang diizinkan saat pengambilan tak boleh
    menjadi saldo negatif yang ikut mengurangi intake pemilik berikutnya."""
    from app.models import User
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import hitung_stok_silo

    jasa_intake = await _masuk_tumpukan(
        pg, pabrik["user"], "PKB-G2K-NEG-01", 1_000, pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], jasa_intake, "C", 1_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        perintah = await _perintah_lama(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                    berat_kg=1_000.5)])
        rec_id = perintah.rec.id
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        assert await hitung_stok_silo(db, pabrik["silo_c"]) == 0

    pabrik_intake = await _masuk_tumpukan(
        pg, pabrik["user"], "PKB-G2K-NEG-02", 2_500, None, pemasok.id)
    await _pindah_ke_silo(pg, pabrik["user"], pabrik_intake, "C", 2_500)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        proses = await mulai_penyosohan(db, user=u, nama_silos=["C"])
        assert proses.berat_awal_total == 2_500


async def test_sisa_setengah_kg_tidak_menjadi_kartu_stok_nol(pg, pabrik, pemasok):
    from app.services.stok import pk_gudang2

    intake = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-ROUND-01", 500,
                                   None, pemasok.id)
    await _pindah_ke_silo(pg, pabrik["user"], intake, "C", 499.5)
    async with pg() as db:
        assert not any(k.intake_id == intake for k in await pk_gudang2(db))


# ───────────────────── Dua arah, dua pesanan ─────────────────────

async def test_pesanan_lain_tak_bisa_mengambil_silo_pesanan_ini(pg, pabrik):
    from app.models import User
    from app.services import barang_keluar as bk

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-03", 5_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 5_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.tersedia(db, bk.BarisPerintah(
                tipe="pk_g2", silo_id=pabrik["silo_c"], berat_kg=1_000,
                jasa_id=pabrik["jasa_b"]))
    assert "bukan barang pesanan ini" in str(e.value)


async def test_pabrik_tak_bisa_menjual_pk_g2_titipan(pg, pabrik):
    from app.models import Pelanggan, User
    from app.services import barang_keluar as bk

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-04", 3_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 3_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        klien = Pelanggan(nama_pelanggan="Toko Beras Uji")
        db.add(klien)
        await db.flush()
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.tersedia(db, bk.BarisPerintah(
                tipe="pk_g2", silo_id=pabrik["silo_c"], berat_kg=1_000))
    assert "tidak dijual pabrik" in str(e.value)


# ───────────────────────────── Picker ─────────────────────────────

async def test_picker_barang_jasa_menawarkan_tumpukan_tanpa_silo(pg, pabrik):
    from app.models import User
    from app.web.aksi_inventory import barang_jasa

    await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-05", 2_000, pabrik["jasa_a"])
    intake_b = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-06", 6_000,
                                     pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_b, "C", 6_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    opsi = await barang_jasa(induk=str(pabrik["pelanggan_a"]), user=u)
    nilai = {o["value"] for o in opsi}
    assert f"g2:tumpukan@{pabrik['jasa_a']}" in nilai
    assert not any(v.startswith("g2:silo:") for v in nilai)


async def test_picker_tak_menawarkan_silo_pesanan_lain(pg, pabrik):
    from app.models import User
    from app.web.aksi_inventory import barang_jasa

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-07", 4_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 4_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    opsi = await barang_jasa(induk=str(pabrik["pelanggan_b"]), user=u)
    nilai = {o["value"] for o in opsi}
    assert not any(v.startswith(f"g2:silo:{pabrik['silo_c']}") for v in nilai)
    assert not any(v.startswith("g2:tumpukan") for v in nilai)


async def test_pelanggan_dengan_pk_tumpukan_g2_bisa_mengambil(pg, pabrik):
    """PK di tumpukan saja cukup untuk menawarkan pengambilan pemiliknya."""
    from app.models import User
    from app.web.aksi_inventory import barang_jasa, pelanggan_ada_barang_jasa

    await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-09", 3_000, pabrik["jasa_a"])

    async with pg() as db:
        u = await db.get(User, pabrik["user"])

    pelanggan = await pelanggan_ada_barang_jasa(user=u)
    assert str(pabrik["pelanggan_a"]) in {o["value"] for o in pelanggan}
    barang = await barang_jasa(induk=str(pabrik["pelanggan_a"]), user=u)
    assert any(o["value"] == f"g2:tumpukan@{pabrik['jasa_a']}" for o in barang)

async def test_satu_truk_menggabung_dua_pesanan_pelanggan_sama(pg, pabrik):
    """PK dari dua lot G1: pemilik per baris tetap benar lintas pesanan."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Jasa, MillingProcess, MillingProgressLog, User
    from app.services import barang_keluar as bk
    from app.services.jasa import sisa_jasa
    from app.web.aksi_inventory import _satu_baris, barang_jasa

    async with pg() as db:
        jasa_a2 = Jasa(kode="JAS-2610-012", pelanggan_id=pabrik["pelanggan_a"],
                       status="berjalan")
        db.add(jasa_a2)
        await db.flush()
        jasa_a2_id = jasa_a2.id

        proc = MillingProcess(kode_proses="LOT-G2K-01", status="selesai",
                              silo_id=pabrik["silo_g1"], jasa_id=pabrik["jasa_a"],
                              berat_gabah_masuk_kg=4_000, waktu_mulai=now_local(),
                              waktu_selesai=now_local(), created_by=pabrik["user"])
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id,
                                  berat_kumulatif_kg=3_000,
                                  waktu_update=now_local(), input_by=pabrik["user"]))
        await db.commit()

    async with pg() as db:
        proc2 = MillingProcess(
            kode_proses="LOT-G2K-02", status="selesai", silo_id=pabrik["silo_g1"],
            jasa_id=jasa_a2_id, berat_gabah_masuk_kg=3_000,
            waktu_mulai=now_local(), waktu_selesai=now_local(),
            created_by=pabrik["user"])
        db.add(proc2)
        await db.flush()
        db.add(MillingProgressLog(
            milling_process_id=proc2.id, berat_kumulatif_kg=2_000,
            waktu_update=now_local(), input_by=pabrik["user"]))
        await db.commit()

    async with pg() as db:
        u = await db.get(User, pabrik["user"])

    barang = await barang_jasa(induk=str(pabrik["pelanggan_a"]), user=u)
    nilai = {o["value"] for o in barang}
    assert f"pk:LOT-G2K-01@{pabrik['jasa_a']}" in nilai
    assert f"pk:LOT-G2K-02@{jasa_a2_id}" in nilai

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        b1 = await _satu_baris(db, f"pk:LOT-G2K-01@{pabrik['jasa_a']}", 3_000)
        b2 = await _satu_baris(db, f"pk:LOT-G2K-02@{jasa_a2_id}", 2_000)
        assert b1.jasa_id == pabrik["jasa_a"]
        assert b2.jasa_id == jasa_a2_id
        r = await bk.buat_perintah(db, user=u, baris=[b1, b2])
        rec_id = r.rec.id
        assert r.rec.jasa_id is None, \
            "truk menggabung dua pesanan — tak boleh menyebut salah satu saja"
        assert r.rec.pelanggan_id == pabrik["pelanggan_a"]

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        from app.penggilingan.inventory.models import OutgoingItem

        item_jasa = dict((await db.execute(
            select(OutgoingItem.jasa_id, OutgoingItem.berat_kg)
            .where(OutgoingItem.outgoing_record_id == rec_id))).all())
        assert sorted(item_jasa) == sorted([pabrik["jasa_a"], jasa_a2_id])

        sisa_a = await sisa_jasa(db, pabrik["jasa_a"])
        assert sisa_a.pk_g1_kg == 0, sisa_a
        sisa_a2 = await sisa_jasa(db, jasa_a2_id)
        assert sisa_a2.pk_g1_kg == 0, sisa_a2


# ───────────────────── Tak pernah jadi barang jualan pabrik ─────────────────────

async def test_pk_g2_tak_pernah_di_picker_penjualan(pg, pabrik):
    """`barang-bisa-keluar` & `pk-siap-keluar` tak pernah menyebut `pk_g2` —
    PK Gudang 2 keluar hanya lewat pengambilan jasa, tak pernah lewat
    penjualan pabrik (desain yang sama sejak awal, diuji di sini supaya
    jelas tak berubah oleh fitur ini)."""
    from app.models import User
    from app.web.aksi_inventory import barang_bisa_keluar, pk_siap_keluar

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-08", 3_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 3_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    for opsi in (await barang_bisa_keluar(user=u), await pk_siap_keluar(user=u)):
        assert not any(str(o["value"]).startswith("g2:") for o in opsi)


async def test_tumpukan_pabrik_di_picker_penjualan_dan_parser(pg, pabrik, pemasok):
    from app.models import User
    from app.web.aksi_inventory import barang_bisa_keluar, _satu_baris
    await _masuk_tumpukan(pg, pabrik['user'], 'PKB-JUAL-G2', 3000, None, pemasok.id)
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
    opsi = await barang_bisa_keluar(user=u)
    assert 'g2:tumpukan' in {o['value'] for o in opsi}
    async with pg() as db:
        b = await _satu_baris(db, 'g2:tumpukan', 1000)
        assert b.tipe == 'pk_g2' and b.silo_id is None
        assert b.berat_kg == 1000
        from fastapi import HTTPException
        with pytest.raises(HTTPException, match='bahan proses'):
            await _satu_baris(db, f"g2:silo:{pabrik['silo_c']}", 1000)


async def test_tumpukan_antar_pemilik_tidak_saling_mengurangi(pg, pabrik, pemasok):
    from app.models import User
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan
    await _masuk_tumpukan(pg, pabrik['user'], 'PKB-A-G2', 2000, pabrik['jasa_a'])
    await _masuk_tumpukan(pg, pabrik['user'], 'PKB-B-G2', 6000, pabrik['jasa_b'])
    await _masuk_tumpukan(pg, pabrik['user'], 'PKB-P-G2', 3000, None, pemasok.id)
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
        r = await bk.buat_perintah(db, user=u, jasa_id=pabrik['jasa_a'],
            baris=[bk.BarisPerintah(tipe='pk_g2', berat_kg=1500)])
        # Reservasi A tidak boleh mengurangi saldo tersedia B.
        ada, _ = await bk.tersedia(db, bk.BarisPerintah(tipe='pk_g2', jasa_id=pabrik['jasa_b']))
        assert ada == 6000
        with pytest.raises(bk.BarangKeluarError, match='tinggal'):
            await bk.buat_perintah(db, user=u, jasa_id=pabrik['jasa_a'],
                baris=[bk.BarisPerintah(tipe='pk_g2', berat_kg=1000)])
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
        await bk.muat_semua(db, user=u, rec_id=r.rec.id)
        assert await hitung_stok_tumpukan(db, jasa_id=pabrik['jasa_a']) == 500
        assert await hitung_stok_tumpukan(db, jasa_id=pabrik['jasa_b']) == 6000
        assert await hitung_stok_tumpukan(db, jasa_id=None) == 3000


async def test_tumpukan_dapat_ditambah_ke_perintah_tanpa_mencatat_muatan(pg, pabrik):
    from app.models import User
    from app.services import barang_keluar as bk
    await _masuk_tumpukan(pg, pabrik['user'], 'PKB-TAMBAH-G2', 5000, pabrik['jasa_a'])
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
        r = await bk.buat_perintah(db, user=u, jasa_id=pabrik['jasa_a'],
            baris=[bk.BarisPerintah(tipe='pk_g2', berat_kg=1000)])
        h = await bk.tambah_baris(db, user=u, rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe='pk_g2', berat_kg=2000))
        assert float(h.baris[0].berat_perintah_kg) == 3000
        assert float(h.baris[0].berat_kg) == 0


@pytest.mark.parametrize('milik_jasa', [False, True])
async def test_api_pk_tumpukan_dari_picker_sampai_muat(pg, pabrik, pemasok, milik_jasa):
    from app.models import User
    from app.services import barang_keluar as bk
    from app.web import csrf
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan
    from tests.pg.test_barang_keluar import _klien
    jid = pabrik['jasa_a'] if milik_jasa else None
    await _masuk_tumpukan(pg, pabrik['user'], 'PKB-HTTP-G2', 2000, jid,
                          pemasok.id if jid is None else None)
    c = await _klien(pg, pabrik['user'], 'uji_pk_http')
    async with c:
        headers = {'X-CSRF-Token':cap_formulir(c)}
        if milik_jasa:
            opsi = (await c.get('/api/actions/barang-jasa', params={'induk':pabrik['pelanggan_a']})).json()
            nilai = f'g2:tumpukan@{jid}'
            url = '/api/actions/ambil-jasa'
        else:
            opsi = (await c.get('/api/actions/barang-bisa-keluar')).json()
            nilai = 'g2:tumpukan'
            url = '/api/actions/perintah-keluar'
        assert nilai in {o['value'] for o in opsi}
        r = await c.post(url, json={'pelanggan':str(pabrik['pelanggan_a']),
            'barang':[{'pilih':nilai,'jumlah':1000}]}, headers=headers)
        assert r.status_code == 200, r.text
        async with pg() as db:
            from app.penggilingan.inventory.models import OutgoingRecord
            rec = (await db.execute(select(OutgoingRecord))).scalars().one()
            rid = rec.id
            assert await hitung_stok_tumpukan(db, jasa_id=jid) == 2000
        ringkas = await c.get('/api/actions/pratinjau-muat', params={'perintah':rid})
        assert ringkas.status_code == 200, ringkas.text
        r = await c.post('/api/actions/muat-semua', json={'perintah':str(rid),
            'dasar':ringkas.json()['dasar']}, headers=headers)
        assert r.status_code == 200, r.text
    async with pg() as db:
        assert await hitung_stok_tumpukan(db, jasa_id=jid) == 1000
