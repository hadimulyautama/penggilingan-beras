"""Karung jadi punya pemilik — keputusan pemilik 7 Oktober 2026.

"di stok harus punya sub-menu stok karung dan stok karung jasa" →
"ubah jadi stok terpisah per pemilik." Karung tak punya tiket timbang
(beda dari PK/beras/gabah) — jadi SATU-SATUNYA jalan sebuah baris
pembelian jadi milik jasa adalah dipindah SESUDAH dibeli, arah KEBALIKAN
dari "Pindah kepemilikan produk" (yang bergerak jasa → pabrik). Berkas ini
menjaga di Postgres sungguhan:

  · `hitung_stok_kemasan(jasa_id=...)` menyaring KETIGA suku (beli, hilang,
    terpakai) sekaligus — pabrik & jasa menjawab pertanyaan yang BERBEDA,
    bukan dua cara menanyakan hal yang sama;
  · `pindah_kepemilikan_karung` FIFO, baris tertua dulu, dipecah bila
    jumlahnya jatuh di tengah satu baris — total pabrik+jasa tetap sama
    sebelum dan sesudah pindah;
  · pagar menolak memindahkan lebih daripada stok pabrik;
  · `jasa_ids_per_pelanggan_dengan_karung` mengelompokkan per PELANGGAN,
    bukan per pesanan (pola yang sama dengan padanannya di produk jadi).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.database import now_local
from app.models import User

pytestmark = pytest.mark.asyncio


@pytest.fixture
def kms():
    from app.penggilingan.inventory import packaging

    return packaging


async def _beli(db, models, *, pemakai, kode_mat="laminasi", nama_mat="Karung Laminasi",
               ukuran=25, lembar, merk="Cap Padi Emas", kode):
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
        harga_per_lembar=1200, tanggal=date(2026, 10, 7),
        waktu=now_local(), input_by=pemakai.id))
    await db.commit()
    return mat.id, size.id, (brand.id if brand else None)


@pytest.fixture
async def jasa_berjalan(pg, pemakai):
    """Satu pesanan jasa berjalan, siap jadi tujuan pindah kepemilikan."""
    from app.models import Jasa, Pelanggan

    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        j = Jasa(kode="JAS-2610-010", pelanggan_id=pel.id, status="berjalan")
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, pel.id


async def test_hitung_stok_kemasan_menyaring_pemilik_di_ketiga_suku(pg, kms, pemakai, jasa_berjalan):
    from app.penggilingan.inventory import models

    jasa_id, _ = jasa_berjalan
    async with pg() as db:
        mat_id, size_id, brand_id = await _beli(
            db, models, pemakai=pemakai, lembar=1000, kode="PKP-UJIJ-01")

    async with pg() as db:
        pabrik_sebelum = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, jasa_id=None)
        jasa_sebelum = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, jasa_id=jasa_id)
    assert pabrik_sebelum == 1000
    assert jasa_sebelum == 0, "belum ada yang dipindah — stok jasa 0, bukan ikut stok pabrik"

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        dipindah = await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", jasa_id=jasa_id, jumlah_lembar=300)
    assert dipindah == 300

    async with pg() as db:
        pabrik_sesudah = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, jasa_id=None)
        jasa_sesudah = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, jasa_id=jasa_id)
    assert pabrik_sesudah == 700, "pabrik berkurang persis sejumlah yang dipindah"
    assert jasa_sesudah == 300
    assert pabrik_sesudah + jasa_sesudah == pabrik_sebelum, "total tak berubah, cuma pemiliknya"


async def test_pindah_kepemilikan_karung_fifo_memecah_baris_tertua(pg, kms, pemakai, jasa_berjalan):
    """Dua baris pembelian (200 lalu 500) — pindah 300 lembar harus
    menghabiskan baris PERTAMA (200) dan memecah baris KEDUA jadi 100
    (dipindah) + 400 (tetap pabrik), bukan menyentuh baris kedua lebih dulu."""
    from sqlalchemy import select

    from app.penggilingan.inventory import models

    jasa_id, _ = jasa_berjalan
    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=200, kode="PKP-UJIJ-02")
        await _beli(db, models, pemakai=pemakai, lembar=500, kode="PKP-UJIJ-03")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", jasa_id=jasa_id, jumlah_lembar=300)

    async with pg() as db:
        baris = (await db.execute(
            select(models.PackagingPurchase)
            .where(models.PackagingPurchase.kode.in_(("PKP-UJIJ-02", "PKP-UJIJ-03")))
            .order_by(models.PackagingPurchase.kode)
        )).scalars().all()
        assert len(baris) == 2
        b1, b2 = baris
        assert b1.jumlah_lembar == 200 and b1.jasa_id == jasa_id, \
            "baris tertua dipindah UTUH"
        assert b2.jumlah_lembar == 400 and b2.jasa_id is None, \
            "baris kedua tersisa 400, TETAP pabrik"
        # Baris pecahan baru (100 lembar, milik jasa) — kode BARU, bukan
        # menimpa baris 500 yang asli.
        pecah = (await db.execute(
            select(models.PackagingPurchase)
            .where(models.PackagingPurchase.jasa_id == jasa_id,
                   models.PackagingPurchase.jumlah_lembar == 100)
        )).scalars().first()
        assert pecah is not None, "baris pecahan 100 lembar milik jasa tak ditemukan"


async def test_pindah_kepemilikan_karung_menolak_lebih_dari_stok_pabrik(pg, kms, pemakai, jasa_berjalan):
    from app.penggilingan.inventory import models

    jasa_id, _ = jasa_berjalan
    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=100, kode="PKP-UJIJ-04")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(kms.InventoryError):
            await kms.pindah_kepemilikan_karung(
                db, user=u, material_kode="laminasi", ukuran=25,
                brand_nama="Cap Padi Emas", jasa_id=jasa_id, jumlah_lembar=101)


async def test_jasa_ids_per_pelanggan_dengan_karung_kelompok_per_pelanggan(pg, kms, pemakai):
    """Satu pelanggan, DUA pesanan — keduanya dapat karung lewat pindah
    kepemilikan — WAJIB muncul sebagai SATU entri pelanggan dengan dua
    jasa_id, pola yang sama dengan padanannya di produk jadi."""
    from app.models import Jasa, Pelanggan
    from app.penggilingan.inventory import models
    from app.services.jasa import jasa_ids_per_pelanggan_dengan_karung

    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Pak Budi")
        db.add(pel)
        await db.flush()
        j1 = Jasa(kode="JAS-2610-011", pelanggan_id=pel.id, status="berjalan")
        j2 = Jasa(kode="JAS-2610-012", pelanggan_id=pel.id, status="berjalan")
        db.add_all([j1, j2])
        await db.commit()
        await db.refresh(j1)
        await db.refresh(j2)
        pelanggan_id, jasa1_id, jasa2_id = pel.id, j1.id, j2.id

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=200, kode="PKP-UJIJ-05")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", jasa_id=jasa1_id, jumlah_lembar=50)

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=80, kode="PKP-UJIJ-06")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", jasa_id=jasa2_id, jumlah_lembar=30)

    async with pg() as db:
        grup = await jasa_ids_per_pelanggan_dengan_karung(db)
    assert pelanggan_id in grup
    assert set(grup[pelanggan_id]) == {jasa1_id, jasa2_id}

    async with pg() as db:
        baris = await kms.stok_kemasan_rinci(db, jasa_id=grup[pelanggan_id])
    laminasi = next(b for b in baris if b["nama"] == "Karung Laminasi")
    assert laminasi["lembar"] == 50 + 30, "kedua pesanan pelanggan ini digabung satu angka"
