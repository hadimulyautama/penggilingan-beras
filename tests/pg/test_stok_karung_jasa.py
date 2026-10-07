"""Karung jadi punya pemilik — keputusan pemilik 7 Oktober 2026.

"di stok harus punya sub-menu stok karung dan stok karung jasa" →
"ubah jadi stok terpisah per pemilik." Lalu koreksi susulan hari yang
sama: "jalur masuk karung untuk jasa bukan berdasarkan proses jasa. tetapi
berdasarkan kontak pelanggan" — jadi pemiliknya `Pelanggan`, BUKAN `Jasa`
(beda dari sebelas tabel ber-`jasa_id` lain di app ini — lihat catatan
panjang di `packaging.pindah_kepemilikan_karung`).

Karung tak punya tiket timbang (beda dari PK/beras/gabah) — jadi
SATU-SATUNYA jalan sebuah baris pembelian jadi milik pelanggan adalah
dipindah SESUDAH dibeli, arah KEBALIKAN dari "Pindah kepemilikan produk"
(yang bergerak jasa → pabrik). Berkas ini menjaga di Postgres sungguhan:

  · `hitung_stok_kemasan(pelanggan_id=...)` menyaring KETIGA suku (beli,
    hilang, terpakai) sekaligus — pabrik & pelanggan menjawab pertanyaan
    yang BERBEDA, bukan dua cara menanyakan hal yang sama;
  · suku `terpakai` diterjemahkan lewat SELURUH `jasa_id` milik pelanggan
    itu (sub-kueri `Jasa.pelanggan_id`) — dua pesanan satu pelanggan
    digabung jadi SATU rekening karung, bukan dua;
  · `pindah_kepemilikan_karung` FIFO, baris tertua dulu, dipecah bila
    jumlahnya jatuh di tengah satu baris — total pabrik+pelanggan tetap
    sama sebelum dan sesudah pindah;
  · pagar menolak memindahkan lebih daripada stok pabrik;
  · `pelanggan_ids_dengan_karung` + `stok_kemasan_rinci(pelanggan_id=...)`
    langsung dari kolom `PackagingPurchase.pelanggan_id` — tanpa
    indirection lewat `Jasa` sama sekali.
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
        tanggal=date(2026, 10, 7), waktu=now_local(), input_by=pemakai.id))
    await db.commit()
    return mat.id, size.id, (brand.id if brand else None)


@pytest.fixture
async def pelanggan(pg):
    """Satu kontak pelanggan, siap jadi tujuan pindah kepemilikan."""
    from app.models import Pelanggan

    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.commit()
        await db.refresh(pel)
        return pel.id


async def test_hitung_stok_kemasan_menyaring_pemilik_di_ketiga_suku(pg, kms, pemakai, pelanggan):
    from app.penggilingan.inventory import models

    async with pg() as db:
        mat_id, size_id, brand_id = await _beli(
            db, models, pemakai=pemakai, lembar=1000, kode="PKP-UJIJ-01")

    async with pg() as db:
        pabrik_sebelum = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, pelanggan_id=None)
        pel_sebelum = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, pelanggan_id=pelanggan)
    assert pabrik_sebelum == 1000
    assert pel_sebelum == 0, "belum ada yang dipindah — stok pelanggan 0, bukan ikut stok pabrik"

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        dipindah = await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", pelanggan_id=pelanggan, jumlah_lembar=300)
    assert dipindah == 300

    async with pg() as db:
        pabrik_sesudah = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, pelanggan_id=None)
        pel_sesudah = await kms.hitung_stok_kemasan(db, mat_id, size_id, brand_id, pelanggan_id=pelanggan)
    assert pabrik_sesudah == 700, "pabrik berkurang persis sejumlah yang dipindah"
    assert pel_sesudah == 300
    assert pabrik_sesudah + pel_sesudah == pabrik_sebelum, "total tak berubah, cuma pemiliknya"


async def test_pindah_kepemilikan_karung_fifo_memecah_baris_tertua(pg, kms, pemakai, pelanggan):
    """Dua baris pembelian (200 lalu 500) — pindah 300 lembar harus
    menghabiskan baris PERTAMA (200) dan memecah baris KEDUA jadi 100
    (dipindah) + 400 (tetap pabrik), bukan menyentuh baris kedua lebih dulu."""
    from sqlalchemy import select

    from app.penggilingan.inventory import models

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=200, kode="PKP-UJIJ-02")
        await _beli(db, models, pemakai=pemakai, lembar=500, kode="PKP-UJIJ-03")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", pelanggan_id=pelanggan, jumlah_lembar=300)

    async with pg() as db:
        baris = (await db.execute(
            select(models.PackagingPurchase)
            .where(models.PackagingPurchase.kode.in_(("PKP-UJIJ-02", "PKP-UJIJ-03")))
            .order_by(models.PackagingPurchase.kode)
        )).scalars().all()
        assert len(baris) == 2
        b1, b2 = baris
        assert b1.jumlah_lembar == 200 and b1.pelanggan_id == pelanggan, \
            "baris tertua dipindah UTUH"
        assert b2.jumlah_lembar == 400 and b2.pelanggan_id is None, \
            "baris kedua tersisa 400, TETAP pabrik"
        # Baris pecahan baru (100 lembar, milik pelanggan) — kode BARU,
        # bukan menimpa baris 500 yang asli.
        pecah = (await db.execute(
            select(models.PackagingPurchase)
            .where(models.PackagingPurchase.pelanggan_id == pelanggan,
                   models.PackagingPurchase.jumlah_lembar == 100)
        )).scalars().first()
        assert pecah is not None, "baris pecahan 100 lembar milik pelanggan tak ditemukan"


async def test_pindah_kepemilikan_karung_menolak_lebih_dari_stok_pabrik(pg, kms, pemakai, pelanggan):
    from app.penggilingan.inventory import models

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=100, kode="PKP-UJIJ-04")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        with pytest.raises(kms.InventoryError):
            await kms.pindah_kepemilikan_karung(
                db, user=u, material_kode="laminasi", ukuran=25,
                brand_nama="Cap Padi Emas", pelanggan_id=pelanggan, jumlah_lembar=101)


async def test_pelanggan_ids_dengan_karung_dan_rinci_langsung_dari_kolom(pg, kms, pemakai):
    """Satu pelanggan, dua PINDAHAN terpisah (bukan dua pesanan jasa — tak
    ada `Jasa` yang terlibat sama sekali di sini) — WAJIB muncul sebagai
    SATU rekening digabung, murni dari `PackagingPurchase.pelanggan_id`."""
    from app.models import Pelanggan
    from app.penggilingan.inventory import models

    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Pak Budi")
        db.add(pel)
        await db.commit()
        await db.refresh(pel)
        pelanggan_id = pel.id

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=200, kode="PKP-UJIJ-05")

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", pelanggan_id=pelanggan_id, jumlah_lembar=50)

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=80, kode="PKP-UJIJ-06")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", pelanggan_id=pelanggan_id, jumlah_lembar=30)

    async with pg() as db:
        ids = await kms.pelanggan_ids_dengan_karung(db)
    assert pelanggan_id in ids

    async with pg() as db:
        baris = await kms.stok_kemasan_rinci(db, pelanggan_id=pelanggan_id)
    laminasi = next(b for b in baris if b["nama"] == "Karung Laminasi")
    assert laminasi["lembar"] == 50 + 30, "kedua pindahan pelanggan ini digabung satu angka"


async def test_terpakai_menyaring_lintas_seluruh_pesanan_pelanggan(pg, kms, pemakai, pelanggan):
    """Suku `terpakai` (packing) membaca `FinishedGoodsStock.jasa_id`, bukan
    `pelanggan_id` — jadi packing yang dilakukan di BAWAH pesanan jasa
    MANA PUN milik pelanggan ini wajib ikut mengurangi stok karungnya,
    walau karungnya sendiri dipindah lewat kolom `pelanggan_id` yang
    terpisah dari `Jasa` sama sekali."""
    from sqlalchemy import select

    from app.models import Jasa
    from app.penggilingan.inventory import models

    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, lembar=500, kode="PKP-UJIJ-07")
        u = await db.get(User, pemakai.id)
        await kms.pindah_kepemilikan_karung(
            db, user=u, material_kode="laminasi", ukuran=25,
            brand_nama="Cap Padi Emas", pelanggan_id=pelanggan, jumlah_lembar=200)

    async with pg() as db:
        j = Jasa(kode="JAS-2610-013", pelanggan_id=pelanggan, status="berjalan")
        db.add(j)
        await db.flush()
        mat = (await db.execute(select(models.PackagingMaterial)
                                .where(models.PackagingMaterial.kode == "laminasi"))
               ).scalars().first()
        size = (await db.execute(select(models.PackageSize)
                                 .where(models.PackageSize.ukuran_kg == 25))
                ).scalars().first()
        brand = (await db.execute(select(models.Brand)
                                  .where(models.Brand.nama == "Cap Padi Emas"))
                 ).scalars().first()
        sku = models.ProductSku(kategori="beras_putih", brand_id=brand.id,
                                packaging_material_id=mat.id, package_size_id=size.id,
                                aktif=True)
        db.add(sku)
        await db.flush()
        db.add(models.FinishedGoodsStock(
            product_sku_id=sku.id, source_type="giling", source_id=None,
            jumlah_karung=60, berat_total_kg=1500, waktu=now_local(),
            input_by=pemakai.id, jasa_id=j.id))
        await db.commit()

    async with pg() as db:
        pel_sesudah = await kms.hitung_stok_kemasan(
            db, mat.id, size.id, brand.id, pelanggan_id=pelanggan)
    assert pel_sesudah == 200 - 60, "packing di bawah pesanan jasa pelanggan ini ikut terpakai"
