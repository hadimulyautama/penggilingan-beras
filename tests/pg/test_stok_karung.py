"""Stok karung di Postgres — satu hitungan, dua pembaca.

Keputusan pemilik 23 September 2026: stok karung punya bloknya sendiri di layar
Stok, tidak lagi hanya di laporan teks. Supaya keduanya tak pernah berselisih,
hitungannya diangkat ke `stok_kemasan_rinci` dan laporan teks disusun DARI
hasilnya. Uji di sini menjaga premis itu pada basis data sungguhan — setiap uji
lain menirukan fungsinya, jadi tanpa berkas ini angka yang dipakai memutuskan
kapan memesan karung tak pernah dihitung sekali pun.

Yang dijaga:
  · hitungannya = beli − hilang − terpakai, per (jenis, ukuran, MERK);
  · `menipis` menyala tepat di batas `min_kemasan_lembar`, bukan di bawahnya;
  · karung PK jatuh ke Gudang 1, sisanya Gudang 2 — itulah pembagian yang
    dipakai layar untuk memutuskan siapa melihat apa;
  · laporan teks dan blok layar membaca angka yang SAMA.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.database import now_local


@pytest.fixture
def kms():
    from app.penggilingan.inventory import packaging

    return packaging


async def _beli(db, models, *, pemakai, kode_mat, nama_mat, ukuran, lembar,
               merk=None, kode="PKP-UJI-01"):
    """Satu pembelian karung, beserta baris master yang diperlukannya."""
    from sqlalchemy import select

    mat = (await db.execute(select(models.PackagingMaterial)
                            .where(models.PackagingMaterial.kode == kode_mat))
           ).scalars().first()
    if mat is None:
        mat = models.PackagingMaterial(kode=kode_mat, nama=nama_mat, aktif=True)
        db.add(mat)
        await db.flush()
    size = (await db.execute(select(models.PackageSize)
                             .where(models.PackageSize.ukuran_kg == ukuran))
            ).scalars().first()
    if size is None:
        size = models.PackageSize(ukuran_kg=ukuran, aktif=True)
        db.add(size)
        await db.flush()
    brand = None
    if merk:
        brand = (await db.execute(select(models.Brand)
                                  .where(models.Brand.nama == merk))
                 ).scalars().first()
        if brand is None:
            brand = models.Brand(nama=merk, tipe="house", aktif=True)
            db.add(brand)
            await db.flush()
    db.add(models.PackagingPurchase(
        kode=kode, packaging_material_id=mat.id, package_size_id=size.id,
        brand_id=brand.id if brand else None, jumlah_lembar=lembar,
        harga_per_lembar=1200, tanggal=date(2026, 9, 23),
        waktu=now_local(), input_by=pemakai.id))
    await db.commit()


async def test_hitungan_gudang_dan_menipis(pg, kms, pemakai):
    from app.config import settings
    from app.penggilingan.inventory import models

    batas = settings.min_kemasan_lembar
    async with pg() as db:
        # Di ATAS batas → tidak menipis. Tepat DI batas → menipis: batas yang
        # baru menyala sesudah dilewati adalah batas yang memberi tahu terlambat.
        await _beli(db, models, pemakai=pemakai, kode_mat="laminasi", nama_mat="Karung Laminasi",
                    ukuran=5, lembar=batas + 1, merk="Cap Padi Emas",
                    kode="PKP-UJI-01")
        await _beli(db, models, pemakai=pemakai, kode_mat="karung_pk", nama_mat="Karung PK",
                    ukuran=50, lembar=batas, kode="PKP-UJI-02")

    async with pg() as db:
        baris = await kms.stok_kemasan_rinci(db)

    per_nama = {b["nama"]: b for b in baris}
    assert set(per_nama) == {"Karung Laminasi", "Karung PK"}

    lam = per_nama["Karung Laminasi"]
    assert lam["lembar"] == batas + 1 and lam["menipis"] is False
    assert lam["gudang"] == "Gudang 2", "karung pengemas beras jadi = Gudang 2"
    assert lam["merk"] == "Cap Padi Emas" and lam["ukuran"] == 5

    pk = per_nama["Karung PK"]
    assert pk["lembar"] == batas and pk["menipis"] is True, "batas tak menyala"
    assert pk["gudang"] == "Gudang 1", "karung PK bukan barang Gudang 2"
    assert pk["merk"] is None

    # Gudang 2 lebih dulu: di sanalah karung habis.
    assert [b["gudang"] for b in baris] == ["Gudang 2", "Gudang 1"]

    # Tak ada harga yang ikut, meski pembeliannya punya harga per lembar.
    for b in baris:
        assert set(b) == {"gudang", "kode", "nama", "merk", "ukuran",
                          "lembar", "menipis"}, b


async def test_terpakai_dan_hilang_ikut_dikurangi(pg, kms, pemakai):
    """Stok = beli − hilang − terpakai, dan KETIGA kakinya diuji.

    Kalau yang hilang tak ikut dikurangi, angkanya terlalu besar justru pada
    karung yang sudah tak ada. Dan kalau yang TERPAKAI tak ikut dikurangi,
    stoknya tak pernah turun sama sekali — blok "menipis" jadi hiasan yang
    tak pernah menyala, yaitu satu-satunya alasan bloknya dibuat.
    """
    from sqlalchemy import select

    from app.penggilingan.inventory import models

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, kode_mat="polos",
                    nama_mat="Karung Polos", ukuran=25, lembar=500,
                    kode="PKP-UJI-03")
        mat = (await db.execute(select(models.PackagingMaterial)
                                .where(models.PackagingMaterial.kode == "polos"))
               ).scalars().first()
        size = (await db.execute(select(models.PackageSize)
                                 .where(models.PackageSize.ukuran_kg == 25))
                ).scalars().first()
        # ── hilang ──
        db.add(models.PackagingLoss(
            packaging_material_id=mat.id, package_size_id=size.id,
            brand_id=None, jumlah_lembar=120, tanggal=date(2026, 9, 23),
            alasan="rusak kena air", waktu=now_local(), input_by=pemakai.id))
        # ── terpakai: karung yang sudah berisi beras jadi ──
        sku = models.ProductSku(kategori="medium", brand_id=None,
                                packaging_material_id=mat.id,
                                package_size_id=size.id, aktif=True)
        db.add(sku)
        await db.flush()
        db.add(models.FinishedGoodsStock(
            product_sku_id=sku.id, source_type="giling", source_id=None,
            jumlah_karung=60, berat_total_kg=1500, waktu=now_local(),
            input_by=pemakai.id))
        await db.commit()

    async with pg() as db:
        baris = await kms.stok_kemasan_rinci(db)
    polos = next(b for b in baris if b["nama"] == "Karung Polos")
    assert polos["lembar"] == 500 - 120 - 60, "beli − hilang − terpakai"


async def test_laporan_teks_membaca_angka_yang_sama(pg, kms, pemakai):
    """Premis seluruh refaktor ini: laporan teks disusun DARI
    `stok_kemasan_rinci`, bukan menghitung ulang. Dua hitungan untuk satu
    pertanyaan akan berselisih pada perubahan berikutnya — justru pada angka
    yang dipakai memutuskan kapan memesan."""
    from app.penggilingan.inventory import models

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, kode_mat="laminasi", nama_mat="Karung Laminasi",
                    ukuran=5, lembar=1840, merk="Cap Padi Emas",
                    kode="PKP-UJI-04")
        await _beli(db, models, pemakai=pemakai, kode_mat="karung_pk", nama_mat="Karung PK",
                    ukuran=50, lembar=90, kode="PKP-UJI-05")

    async with pg() as db:
        baris = await kms.stok_kemasan_rinci(db)
        teks = await kms.laporan_stok_kemasan(db)

    for b in baris:
        assert f"{b['lembar']:,}".replace(",", ".") in teks, b["nama"]
        assert b["nama"] in teks
    # Babnya per gudang, dan urutannya sama dengan daftar rincinya.
    assert teks.index("Gudang 2") < teks.index("Gudang 1")


async def test_belum_ada_pembelian_bukan_galat(pg, kms):
    """Basis data pabrik baru: daftarnya kosong, laporannya berkalimat, dan
    layar tak menggambar judul di atas kartu hampa (`{% if karung %}`)."""
    async with pg() as db:
        assert await kms.stok_kemasan_rinci(db) == []
        assert "Belum ada stok kemasan" in await kms.laporan_stok_kemasan(db)
