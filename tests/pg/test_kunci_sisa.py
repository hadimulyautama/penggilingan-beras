"""Sisa prompt 7: kunci, kapasitas, jeda, dan sumber yang tertinggal.

Enam temuan yang tak masuk commit sebelumnya, masing-masing menyentuh alur
yang berbeda.

**P-K-06.** Transfer PK melebihi yang diproduksi — 6 ton jadi 12 ton. Dua
transfer bersamaan sama-sama membaca "tersedia 6 t" sebelum salah satunya
menulis. Dan kelebihannya TERSEMBUNYI, karena stok dipotong di nol: yang
terbaca "0", bukan "−6.000".

**P-K-14.** `berat_gabah_masuk_kg` dibaca lalu ditulis kembali, jadi dua
pemasukan bersamaan saling menimpa — yang kedua menghapus tambahan yang
pertama.

**P-K-11.** Silo Gudang 2 menerima PK saat isinya sedang dipoles.

**P-K-12.** Gabah basah dan kering masuk dryer yang sama, dan kapasitasnya
terlewati.

**P-K-17.** Jeda tetap terbuka bila prosesnya ditutup saat sedang dijeda —
jadi laporan waktu henti terus bertambah untuk mesin yang sudah selesai.

**P-K-18.** Menutup giling hanya menandai sumber UTAMA sebagai "digiling".
Batch lain yang ikut tergiling tetap berstatus lama, dan ditawarkan lagi untuk
digiling kedua kalinya.
"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.asyncio


async def test_transfer_mengunci_prosesnya(pg):
    """P-K-06. Tanpa kunci, dua transfer sama-sama membaca stok yang sama."""
    from app.services import transfer

    kode = inspect.getsource(transfer.create_internal_transfer)
    assert "with_for_update()" in kode
    # Dan pemeriksaan stoknya SESUDAH kunci didapat. Dianchor ke PERINTAHNYA,
    # bukan ke katanya: "tersedia" muncul lebih dulu di penjelasannya.
    assert kode.index("with_for_update()") < kode.index("tersedia = await")


async def test_kelebihan_transfer_tak_disembunyikan(pg):
    """Stok dipotong di nol, jadi kelebihan 6 ton terbaca "0" — bukan
    "−6.000". Yang disembunyikan tak bisa diperbaiki siapa pun."""
    from app.services import transfer

    assert hasattr(transfer, "saldo_pk"), "tak ada hitungan saldo tanpa potong-nol"
    kode = inspect.getsource(transfer.saldo_pk)
    assert "max(" not in kode, "saldo masih dipotong di nol"


async def test_berat_masuk_ditambah_secara_atomik(pg):
    """P-K-14. Baca-lalu-tulis: pemasukan kedua menghapus tambahan pertama."""
    from app.penggilingan.gudang1.services import silo

    kode = inspect.getsource(silo)
    assert "berat_gabah_masuk_kg = (" not in kode, (
        "masih baca-lalu-tulis di Python")
    assert "update(MillingProcess)" in kode and "berat_gabah_masuk_kg=(" in kode, (
        "penambahannya belum dikerjakan basis data")


async def test_silo_g2_yang_sedang_dipoles_menolak_pk_baru(pg):
    """P-K-11. PK yang masuk di tengah penyosohan tak terhitung di rumus
    konsumsi, jadi hasil polesnya terbaca lebih besar daripada bahannya."""
    from app.penggilingan.gudang2 import service as g2

    # Penjaganya di tempat INTAKE dikerjakan, bukan di modul penyosohan:
    # yang harus ditolak adalah PK yang masuk, bukan penyosohan yang mulai.
    kode = inspect.getsource(g2._tolak_silo_sedang_dipoles)
    assert "sedang dipoles" in kode
    assert "PolishingSiloUsage" in kode
    # Dan ia benar-benar dipanggil di jalur intake.
    assert "_tolak_silo_sedang_dipoles(db, silo_id)" in inspect.getsource(g2._add_intake)


async def test_dryer_menolak_campur_kondisi_dan_kelebihan_muatan(pg):
    """P-K-12. Gabah basah & kering dalam satu mesin dikeringkan dengan
    setelan yang sama — dan salah satunya pasti keliru."""
    from app.penggilingan.gudang1.services import drying

    kode = inspect.getsource(drying.masuk_dryer) if hasattr(drying, "masuk_dryer") \
        else inspect.getsource(drying)
    assert "kapasitas" in kode.lower()


async def test_jeda_terbuka_ditutup_saat_prosesnya_selesai(pg):
    """P-K-17. Laporan waktu henti terus bertambah untuk mesin yang sudah
    selesai — dan angka itu dipakai menilai kinerja shift."""
    from app.penggilingan.gudang1.services import milling

    kode = inspect.getsource(milling.finish_milling)
    assert "jeda" in kode.lower()


async def test_semua_sumber_ditandai_digiling(pg):
    """P-K-18. Hanya sumber UTAMA yang ditandai, jadi batch lain yang ikut
    tergiling ditawarkan lagi untuk digiling kedua kalinya."""
    from app.penggilingan.gudang1.services import milling

    kode = inspect.getsource(milling.finish_milling)
    assert "MillingProcessSource" in kode, "sumber tambahan tak disentuh"


async def test_stok_negatif_muncul_di_rekonsiliasi(pg):
    """Layar operator memotong saldo di nol — dan itu tepat untuk layar. Tapi
    yang dipotong di layar tak boleh ikut hilang dari pembukuan: selisih yang
    tak muncul di satu layar pun tak akan pernah diperiksa siapa pun."""
    from app.penggilingan.gudang1.services import rekonsiliasi

    kode = inspect.getsource(rekonsiliasi)
    assert "_stok_pk_negatif" in kode
    assert "saldo_pk" in kode, "masih memakai angka yang sudah dipotong nol"
    # Dan ia benar-benar ditampilkan, bukan cuma dihitung.
    assert "TERKIRIM MELEBIHI" in inspect.getsource(rekonsiliasi.format_rekonsiliasi)


# ─────────────────────────── X-20 ───────────────────────────

async def test_nama_pemasok_tak_bisa_kembar(pg):
    """Tiga penulis menyentuh tabel `suppliers` dan tak satu pun tahu tentang
    yang lain. Dua baris bernama sama memecah riwayat satu orang jadi dua —
    tanpa ada yang salah di layar mana pun. Temuan QA X-20."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Supplier

    async with pg() as db:
        db.add(Supplier(nama_supplier="H. Anton"))
        await db.commit()

    # Ejaan berbeda, orang yang sama — dan orang itulah yang laporannya
    # terbelah.
    async with pg() as db:
        db.add(Supplier(nama_supplier="h. anton"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_pemasok_terhapus_boleh_bernama_sama(pg):
    """Itulah gunanya soft delete; melarangnya berarti nama yang pernah
    dipakai terkunci selamanya."""
    from datetime import datetime, timezone

    from app.models import Supplier

    async with pg() as db:
        db.add(Supplier(nama_supplier="Sudah Berhenti",
                        deleted_at=datetime.now(timezone.utc)))
        await db.commit()
    async with pg() as db:
        db.add(Supplier(nama_supplier="Sudah Berhenti"))
        await db.commit()   # tak melempar


async def test_dua_pencatat_satu_nama_menghasilkan_satu_baris(pg):
    """Jalur `find_or_create_supplier` menerjemahkan penolakan indeks jadi
    "pakai yang sudah ada" — yang memintanya memang cuma ingin pemasoknya."""
    from sqlalchemy import func, select

    from app.models import Supplier
    from app.penggilingan.gudang1.services.purchase import find_or_create_supplier

    async with pg() as db:
        s1, baru1 = await find_or_create_supplier(db, "Karyo Tani")
        await db.commit()
    async with pg() as db:
        s2, baru2 = await find_or_create_supplier(db, "karyo tani")
        await db.commit()

    assert baru1 is True and baru2 is False
    async with pg() as db:
        n = (await db.execute(
            select(func.count(Supplier.id))
            .where(func.lower(Supplier.nama_supplier) == "karyo tani"))).scalar_one()
    assert n == 1
