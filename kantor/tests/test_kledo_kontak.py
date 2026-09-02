"""Uji sinkronisasi kontak vendor Kledo → `suppliers`.

Yang dijaga di sini adalah janji-janji yang mahal bila dilanggar:

  · hanya kontak bertipe VENDOR yang disalin — bukan karyawan, pelanggan,
    atau beban seperti PLN dan Pertamina;
  · tidak pernah menghapus supplier lokal, karena riwayat timbangan dan
    pembelian masih menunjuk ke sana;
  · nama lokal yang ambigu tidak ditebak — menebak berarti timbangan tercatat
    atas nama orang yang salah;
  · dijalankan berapa kali pun hasilnya sama.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.kantor.models  # noqa: F401  — daftarkan tabel kantor_* ke metadata
from app.database import Base
from app.kantor import kledo_kontak
from hmu_core import Supplier


def kontak(kid: int, nama: str, tipe=(1,), **beda) -> dict:
    d = {"id": kid, "name": nama, "type_ids": list(tipe), "is_archive": 0,
         "phone": None, "address": None}
    d.update(beda)
    return d


#: Cerminan data sungguhan: vendor bertipe 1; PLN & karyawan bukan.
CONTOH = [
    kontak(572, "Catur"),
    kontak(515, "Umar Arifuddin", phone="0812-1111", address="Sragen"),
    kontak(1054, "Widiyanto"),
    kontak(77, "PLN", tipe=(4,)),                       # beban, bukan vendor
    kontak(88, "Ahmad Wahid Nurhani", tipe=(2,)),       # karyawan
    kontak(99, "Walk-in Customer", tipe=(3,)),          # pelanggan
    kontak(66, "Vendor Lama", tipe=(1,), is_archive=1),  # diarsipkan
    # Vendor SEKALIGUS pelanggan. Bukan kasus buatan: 24 kontak sungguhan
    # memang begitu — menjual gabah pagi, membeli beras sore.
    kontak(310, "Toko Beras Handoko", tipe=(1, 3)),
]


@pytest_asyncio.fixture
async def db():
    mesin = create_async_engine("sqlite+aiosqlite://")
    async with mesin.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)
    async with Sesi() as sesi:
        yield sesi
    await mesin.dispose()


@pytest.fixture
def kledo(monkeypatch):
    """Ganti panggilan jaringan dengan contoh tetap.

    Ditambal pada `ambil_kontak`, bukan `ambil_vendor`: sejak sinkronisasi
    vendor dan pelanggan berbagi satu kode, di situlah satu-satunya tempat
    jaringan benar-benar disentuh. Menambal pembungkusnya akan meloloskan
    panggilan sungguhan lewat jalur pelanggan tanpa gejala.
    """
    async def palsu(tipe: int):
        return [k for k in CONTOH
                if tipe in k["type_ids"] and not k["is_archive"]]
    monkeypatch.setattr(kledo_kontak, "ambil_kontak", palsu)


async def nama_supplier(db) -> list[str]:
    return sorted(
        s.nama_supplier for s in (await db.execute(select(Supplier))).scalars()
    )


# ─────────────────── Penyaringan jenis kontak ───────────────────

async def test_hanya_vendor_yang_disalin(db, kledo):
    """PLN, karyawan, dan pelanggan tidak boleh masuk daftar pos timbang."""
    hasil = await kledo_kontak.sinkron(db)
    assert hasil.dibuat == 4
    assert await nama_supplier(db) == [
        "Catur", "Toko Beras Handoko", "Umar Arifuddin", "Widiyanto"]


async def test_kontak_diarsipkan_dilewati(db, kledo):
    await kledo_kontak.sinkron(db)
    assert "Vendor Lama" not in await nama_supplier(db)


def test_tipe_vendor_adalah_satu():
    """Bukan 4. Tipe 4 berisi PLN dan Pertamina — beban, bukan pemasok.

    Nyaris tertukar saat perancangan; angka ini dikunci agar tidak bergeser
    diam-diam saat kode disalin-tempel.
    """
    assert kledo_kontak.TIPE_VENDOR == 1


# ─────────────────── Penautan ───────────────────

async def test_supplier_lama_ditaut_bukan_diduplikasi(db, kledo):
    db.add(Supplier(nama_supplier="Catur"))
    await db.commit()

    hasil = await kledo_kontak.sinkron(db)
    assert hasil.ditaut == 1
    assert hasil.dibuat == 3

    baris = list((await db.execute(
        select(Supplier).where(Supplier.nama_supplier == "Catur")
    )).scalars())
    assert len(baris) == 1                 # tidak kembar
    assert baris[0].kledo_contact_id == 572


async def test_nama_kembar_tidak_pernah_ditebak(db, kledo):
    """Dua 'Agus' lokal: menebak berarti timbangan tercatat atas nama salah."""
    db.add_all([Supplier(nama_supplier="Agus"), Supplier(nama_supplier="Agus")])
    await db.commit()

    hasil = await kledo_kontak.sinkron(db)
    assert hasil.ambigu == ["Agus", "Agus"]

    for s in (await db.execute(
        select(Supplier).where(Supplier.nama_supplier == "Agus")
    )).scalars():
        assert s.kledo_contact_id is None


async def test_supplier_tanpa_padanan_kledo_dibiarkan(db, kledo):
    """'pak lasno' tidak ada di Kledo — tidak boleh hilang dari pos timbang."""
    db.add(Supplier(nama_supplier="pak lasno"))
    await db.commit()

    await kledo_kontak.sinkron(db)
    assert "pak lasno" in await nama_supplier(db)


# ─────────────────── Pembaruan & idempotensi ───────────────────

async def test_identitas_diperbarui_dari_kledo(db, kledo):
    await kledo_kontak.sinkron(db)
    s = (await db.execute(
        select(Supplier).where(Supplier.kledo_contact_id == 515)
    )).scalars().one()
    assert s.no_telfon == "0812-1111" and s.alamat == "Sragen"


async def test_kledo_kosong_tidak_mengosongkan_data_lokal(db, kledo):
    """Telepon yang sudah dicatat manual jangan dihapus hanya karena Kledo kosong."""
    db.add(Supplier(nama_supplier="Catur", no_telfon="0899-lokal"))
    await db.commit()

    await kledo_kontak.sinkron(db)
    s = (await db.execute(
        select(Supplier).where(Supplier.kledo_contact_id == 572)
    )).scalars().one()
    assert s.no_telfon == "0899-lokal"


async def test_dijalankan_berulang_hasilnya_sama(db, kledo):
    pertama = await kledo_kontak.sinkron(db)
    kedua = await kledo_kontak.sinkron(db)
    assert pertama.dibuat == 4
    assert (kedua.dibuat, kedua.ditaut, kedua.diperbarui) == (0, 0, 0)
    assert len(await nama_supplier(db)) == 4


async def test_mode_hitung_saja_tidak_menyentuh_database(db, kledo):
    hasil = await kledo_kontak.sinkron(db, terapkan=False)
    assert hasil.dibuat == 4
    assert await nama_supplier(db) == []


async def test_kledo_kosong_tidak_merusak_apa_pun(db, monkeypatch):
    """Gangguan Kledo tidak boleh berakhir dengan master supplier terhapus."""
    async def kosong(tipe: int):
        return []
    monkeypatch.setattr(kledo_kontak, "ambil_kontak", kosong)

    db.add(Supplier(nama_supplier="Catur", kledo_contact_id=572))
    await db.commit()

    hasil = await kledo_kontak.sinkron(db)
    assert hasil.dibuat == 0
    assert await nama_supplier(db) == ["Catur"]


# ─────────────── Pelanggan ───────────────

async def nama_pelanggan(db) -> list[str]:
    from hmu_core import Pelanggan

    return sorted(
        p.nama_pelanggan for p in (await db.execute(select(Pelanggan))).scalars()
    )


async def test_pelanggan_disalin_dari_tipe_tiga(db, kledo):
    """Tipe 3 diperiksa pada data sungguhan: 301 dari 601 kontak, dan hanya di
    sanalah "Walk-in Customer" — kontak pelanggan bawaan Kledo — muncul."""
    hasil = await kledo_kontak.sinkron(db, kledo_kontak.PELANGGAN)
    assert hasil.dibuat > 0
    nama = await nama_pelanggan(db)
    assert nama
    # Vendor tidak boleh ikut masuk ke tabel pelanggan.
    from hmu_core import Supplier
    assert (await db.execute(select(Supplier))).scalars().all() == []


async def test_kontak_bertipe_ganda_masuk_ke_kedua_tabel(db, kledo):
    """24 kontak sungguhan bertipe vendor SEKALIGUS pelanggan. Itu wajar:
    orang yang menjual gabah pagi bisa membeli beras sore. Perannya ditentukan
    transaksinya, bukan kontaknya."""
    ganda = [k["name"] for k in CONTOH
             if {1, 3} <= set(k["type_ids"]) and not k["is_archive"]]
    if not ganda:
        pytest.skip("contoh tidak memuat kontak bertipe ganda")

    await kledo_kontak.sinkron_semua(db)
    for nama in ganda:
        assert nama in await nama_supplier(db)
        assert nama in await nama_pelanggan(db)


async def test_sinkron_semua_mengerjakan_keduanya(db, kledo):
    hasil = await kledo_kontak.sinkron_semua(db)
    assert set(hasil) == {"vendor", "pelanggan"}
    assert await nama_supplier(db) and await nama_pelanggan(db)


async def test_pelanggan_dijalankan_berulang_hasilnya_sama(db, kledo):
    await kledo_kontak.sinkron(db, kledo_kontak.PELANGGAN)
    pertama = await nama_pelanggan(db)
    kedua_kali = await kledo_kontak.sinkron(db, kledo_kontak.PELANGGAN)
    assert kedua_kali.dibuat == 0
    assert await nama_pelanggan(db) == pertama
