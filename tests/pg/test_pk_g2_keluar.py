"""PK Gudang 2 bisa keluar — Lubang kedua, pesan kerja 7 Oktober 2026 butir 4.

Sebelum ini: PK titipan pelanggan yang sudah berdiri di silo ATAU tumpukan
Gudang 2 tak punya jalan keluar sama sekali — jenis barang `pk_g2` tak
dikenal `barang_keluar.tersedia()`, dan `sisa_jasa()` menghitung PK Gudang 2
murni "masuk − disosoh" tanpa suku "diambil". Pesanan yang berhenti di tahap
ini tak bisa pernah ditutup walau barangnya sudah di tangan pemiliknya.

Suku KELUAR ditambahkan bersamaan ke `hitung_stok_silo`, `hitung_stok_
tumpukan`, DAN `sisa_jasa()` — ketiganya, bukan salah satu: yang terpisah
membuat stok (atau sisa pesanan) berbohong sejak pemakaian pertama.
"""
from __future__ import annotations

from datetime import date

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
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        silo_c = Silo(nama_silo="Silo C", warehouse_id=g2.id, status="kosong")
        db.add(silo_c)
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
        return {"g1": g1.id, "g2": g2.id, "silo_c": silo_c.id, "user": u.id,
                "jasa_a": jasa_a.id, "jasa_b": jasa_b.id}


async def _masuk_tumpukan(pg, user_id: int, kode: str, kg: float,
                          jasa_id: int | None) -> int:
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
            kode_batch=kode, jasa_id=jasa_id, berat_total_kg=kg,
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


# ───────────────── Tumpukan: ambil penuh, pesanan jadi bisa ditutup ─────────────────

async def test_ambil_penuh_dari_tumpukan_mengosongkan_stok_dan_menutup_pesanan(pg, pabrik):
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
        r = await bk.buat_perintah(
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


# ───────────────────────── Silo: ambil sebagian ─────────────────────────

async def test_ambil_sebagian_dari_silo_mengurangi_stok_persis(pg, pabrik):
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
        r = await bk.buat_perintah(
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


async def test_tambah_baris_pesanan_sendiri_tak_lagi_ditolak_salah_arah(pg, pabrik):
    """Laporan lapangan 10 Oktober 2026: `tambah_baris` ("➕ Tambah barang ke
    transaksi") dulu tak pernah menurunkan `baris.jasa_id` dari `rec.jasa_id`
    — berbeda dari `buat_perintah`, yang melakukannya. Akibatnya pagar
    dua-arah di `tersedia()` (`pk_g2`) membandingkan `silo.jasa_id` (jasa_a)
    terhadap `b.jasa_id` yang SELALU `None`, dan menolak penambahan barang
    MILIK SENDIRI dengan pesan "barang jasa tidak dijual pabrik" — padahal
    perintahnya sendiri memang milik jasa_a.
    """
    from app.models import User
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang2.service import hitung_stok_silo

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-08", 10_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 10_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await bk.buat_perintah(
            db, user=u, jasa_id=pabrik["jasa_a"],
            baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                    berat_kg=2_000)])
        rec_id = r.rec.id

    # Baris KEDUA, barang yang SAMA (silo C, pemiliknya jasa_a juga) —
    # ditambahkan ke PERINTAH YANG SAMA lewat tambah_baris, bukan buat_perintah.
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        h = await bk.tambah_baris(
            db, user=u, rec_id=rec_id,
            baris=bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                   berat_kg=3_000))
        assert len(h.baris) == 1, "barang yang sama digabung jadi satu baris"
        assert float(h.baris[0].berat_perintah_kg) == 5_000

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        assert await hitung_stok_silo(db, pabrik["silo_c"], pemilik="jasa") == 5_000


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
            await bk.buat_perintah(
                db, user=u, jasa_id=pabrik["jasa_b"],
                baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                        berat_kg=1_000)])
    assert "bukan barang pesanan ini" in str(e.value)


async def test_pabrik_tak_bisa_menjual_pk_g2_titipan(pg, pabrik):
    from app.models import User
    from app.services import barang_keluar as bk

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-04", 3_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 3_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        with pytest.raises(bk.BarangKeluarError) as e:
            await bk.buat_perintah(
                db, user=u, nama_pembeli="Toko Beras Uji",
                baris=[bk.BarisPerintah(tipe="pk_g2", silo_id=pabrik["silo_c"],
                                        berat_kg=1_000)])
    assert "tidak dijual pabrik" in str(e.value)


# ───────────────────────────── Picker ─────────────────────────────

async def test_picker_barang_jasa_menawarkan_tumpukan_dan_silo(pg, pabrik):
    from app.models import User
    from app.web.aksi_inventory import barang_jasa

    await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-05", 2_000, pabrik["jasa_a"])
    intake_b = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-06", 6_000,
                                     pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_b, "C", 6_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    opsi = await barang_jasa(jasa=str(pabrik["jasa_a"]), user=u)
    nilai = {o["value"] for o in opsi}
    assert "g2:tumpukan" in nilai
    assert f"g2:silo:{pabrik['silo_c']}" in nilai


async def test_picker_tak_menawarkan_silo_pesanan_lain(pg, pabrik):
    from app.models import User
    from app.web.aksi_inventory import barang_jasa

    intake_id = await _masuk_tumpukan(pg, pabrik["user"], "PKB-G2K-07", 4_000,
                                      pabrik["jasa_a"])
    await _pindah_ke_silo(pg, pabrik["user"], intake_id, "C", 4_000)

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    opsi = await barang_jasa(jasa=str(pabrik["jasa_b"]), user=u)
    nilai = {o["value"] for o in opsi}
    assert f"g2:silo:{pabrik['silo_c']}" not in nilai
    assert "g2:tumpukan" not in nilai


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
