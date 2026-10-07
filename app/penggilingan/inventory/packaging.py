"""Layanan inventory sub-fase 1: master lookup, SKU on-demand, stok kemasan.

Stok kemasan DITURUNKAN = beli − terpakai − hilang. 'terpakai' menyusul di
sub-fase 2 (packing barang jadi). HPP kemasan = rata-rata tertimbang harga/lembar.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import input_time, now_local
from app.models import (
    Brand,
    FinishedGoodsStock,
    PackageSize,
    PackagingLoss,
    PackagingMaterial,
    PackagingPurchase,
    ProductSku,
    RiceQualityStandard,
    User,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_packaging_purchase_code
from app.services.notification import create_notification


class InventoryError(Exception):
    """Kesalahan inventory dengan pesan siap-tampil (args[0])."""


# ─────────────────────────── Lookup master ───────────────────────────
async def get_material(db: AsyncSession, kode: str) -> PackagingMaterial | None:
    return (
        await db.execute(select(PackagingMaterial).where(PackagingMaterial.kode == kode.lower()))
    ).scalars().first()


async def get_size(db: AsyncSession, ukuran_kg: int) -> PackageSize | None:
    return (
        await db.execute(select(PackageSize).where(PackageSize.ukuran_kg == int(ukuran_kg)))
    ).scalars().first()


async def get_brand(db: AsyncSession, nama: str) -> Brand | None:
    return (
        await db.execute(
            select(Brand).where(func.lower(Brand.nama) == nama.lower(), Brand.deleted_at.is_(None))
        )
    ).scalars().first()


async def get_standard(db: AsyncSession, kode: str) -> RiceQualityStandard | None:
    return (
        await db.execute(select(RiceQualityStandard).where(RiceQualityStandard.kode == kode.lower()))
    ).scalars().first()


# Aturan kemasan per kategori (validasi kombinasi).
KEMASAN_VALID = {
    "beras_putih": {("biasa", None), ("laminasi", None)},  # ukuran: _BERAS_SIZES
    "beras_b": {("biasa", None), ("laminasi", None)},
    "broken": {("putih", 50), ("polos", 25)},
    "menir": {("putih", 50)},
    # Bekatul boleh dikemas SEJAK 28 September 2026 (keterangan pemilik: karung
    # bekas 40 kg) — dan ia satu-satunya barang yang punya DUA jalan sekaligus:
    # sebagian dijual curah lewat "Catat bekatul (curah)" & "Bekatul keluar",
    # sebagian dikarungi lewat packing. Pemilik memilih keduanya dengan sadar.
    #
    # ⚠ DUA JALAN KE SATU TUMPUKAN. Keduanya mengambil dari angka yang sama —
    # bekatul yang keluar mesin pada penyosohan itu — jadi keduanya WAJIB saling
    # mengurangi. Tanpa itu, 1.000 kg bisa dibukukan curah lalu dikarungi lagi,
    # dan stoknya jadi 2.000 kg tanpa satu pesan pun. Pagarnya
    # `finished_goods._bekatul_terpakai`, dibaca kedua pencatat.
    # 20 kg ditambahkan 30 September 2026 atas jawaban pemilik: bekatul
    # dikemas 40 kg DAN 20 kg di lapangan, sementara app cuma menawarkan 40.
    # Operator yang memegang karung 20 kg tak punya pilihan yang benar, dan
    # yang dipilihnya kemudian adalah yang salah.
    "bekatul": {("bekas", 40), ("bekas", 20)},
    "reject": {("bekas", 50)},
    "pk": {("karung_pk", 50)},
}
#: Ukuran karung beras yang dipakai pabrik. 20 dan 40 kg ditambahkan 28
#: September 2026 atas keterangan pemilik — keduanya sudah dipakai di lapangan,
#: dan yang belum ada di sini.
#:
#: ⚠ DUA TEMPAT, DAN KEDUANYA WAJIB SEPAKAT. Daftar ini yang MENAWARKAN
#: ukurannya di borang (`aksi_inventory.kombinasi_kemasan`); yang MENERIMANYA
#: saat disimpan adalah baris `package_sizes` di basis data
#: (`find_or_create_sku` → `get_size`). Ukuran yang ada di sini tetapi tak
#: disemai berakhir sebagai pilihan yang bisa ditekan lalu ditolak — "Ukuran 20
#: kg tidak terdaftar", sesudah operator mengetik jumlah karungnya. Pagarnya
#: `tests/test_ukuran_kemasan.py`, bukan ingatan.
_BERAS_SIZES = {5, 10, 20, 25, 40, 48, 50}


def _validate_kemasan(kategori: str, material_kode: str, ukuran: int) -> None:
    rules = KEMASAN_VALID.get(kategori)
    if rules is None:
        raise InventoryError(f"Kategori produk tidak dikenal: {kategori}.")
    for mat, size in rules:
        if mat == material_kode and (size is None or size == ukuran):
            if size is None and ukuran not in _BERAS_SIZES:
                break
            return
    raise InventoryError(
        f"Kombinasi kemasan tak valid untuk {kategori}: {material_kode} {ukuran}kg."
    )


async def find_or_create_sku(
    db: AsyncSession, *, kategori: str, material_kode: str, ukuran: int,
    brand_nama: str | None = None,
) -> ProductSku:
    """Ambil SKU (kategori×merk×karung×ukuran) atau buat bila belum ada."""
    _validate_kemasan(kategori, material_kode, ukuran)
    material = await get_material(db, material_kode)
    if material is None:
        raise InventoryError(f"Jenis karung '{material_kode}' tidak ada.")
    size = await get_size(db, ukuran)
    if size is None:
        raise InventoryError(f"Ukuran {ukuran}kg tidak terdaftar.")
    brand_id = None
    if brand_nama and kategori in ("beras_putih", "beras_b"):
        brand = await get_brand(db, brand_nama)
        if brand is None:
            raise InventoryError(f"Merk '{brand_nama}' tidak ada.")
        brand_id = brand.id
    sku = (
        await db.execute(
            select(ProductSku).where(
                ProductSku.kategori == kategori,
                ProductSku.brand_id.is_(brand_id) if brand_id is None else ProductSku.brand_id == brand_id,
                ProductSku.packaging_material_id == material.id,
                ProductSku.package_size_id == size.id,
            )
        )
    ).scalars().first()
    if sku is None:
        sku = ProductSku(
            kategori=kategori, brand_id=brand_id,
            packaging_material_id=material.id, package_size_id=size.id,
        )
        db.add(sku)
        await db.flush()
    return sku


# ─────────────────────────── Stok kemasan ───────────────────────────
async def hitung_stok_kemasan(
    db: AsyncSession, material_id: int, size_id: int, brand_id: int | None = None,
    *, pelanggan_id: int | list[int] | None = None,
) -> int:
    """Stok karung (lembar) per (jenis, ukuran, MERK, PEMILIK) = beli − hilang − terpakai.

    `brand_id`=None → cocokkan baris tanpa merk (data lama / byproduct).
    Terpakai = jumlah karung packing (SKU dgn merk+jenis+ukuran sama).

    `pelanggan_id`=None (bawaan) → PABRIK. Sejak keputusan pemilik 7 Oktober
    2026 ("ubah jadi stok terpisah per pemilik" — "berdasarkan kontak
    pelanggan, bukan proses jasa"), karung BOLEH berpindah milik ke KONTAK
    pelanggan lewat `pindah_kepemilikan_karung` — jadi KETIGA suku rumus
    kini ikut saringan pemilik, bukan cuma dua. Pembelian (`beli_kemasan`)
    sendiri TETAP selalu menulis `pelanggan_id=NULL`: karung tak punya
    tiket timbang untuk menurunkan pemiliknya saat masuk, jadi satu-satunya
    jalan sebuah baris jadi milik pelanggan adalah dipindah sesudahnya.

    ⚠ Suku `terpakai` membaca `FinishedGoodsStock.jasa_id` (per PESANAN,
    pola jasa_id biasa — lihat `app/services/jasa.py`), bukan `pelanggan_id`
    langsung: kolom itu tak ada di tabel ini. `pelanggan_id` diterjemahkan
    jadi seluruh `jasa_id` milik kontak itu lewat sub-kueri `Jasa.
    pelanggan_id` — konsisten dengan `beli`/`hilang` tanpa menambah kolom
    `pelanggan_id` ke `finished_goods_stock`.
    """
    def _brand(col):
        return col.is_(None) if brand_id is None else col == brand_id

    def _pelanggan(col):
        if pelanggan_id is None:
            return col.is_(None)
        if isinstance(pelanggan_id, list):
            return col.in_(pelanggan_id)
        return col == pelanggan_id

    def _jasa_milik_pelanggan(col):
        if pelanggan_id is None:
            return col.is_(None)
        from app.models import Jasa
        kondisi = (Jasa.pelanggan_id.in_(pelanggan_id)
                  if isinstance(pelanggan_id, list) else Jasa.pelanggan_id == pelanggan_id)
        return col.in_(select(Jasa.id).where(kondisi))

    beli = (
        await db.execute(
            select(func.coalesce(func.sum(PackagingPurchase.jumlah_lembar), 0)).where(
                PackagingPurchase.packaging_material_id == material_id,
                PackagingPurchase.package_size_id == size_id,
                _brand(PackagingPurchase.brand_id),
                _pelanggan(PackagingPurchase.pelanggan_id),
            )
        )
    ).scalar_one()
    hilang = (
        await db.execute(
            select(func.coalesce(func.sum(PackagingLoss.jumlah_lembar), 0)).where(
                PackagingLoss.packaging_material_id == material_id,
                PackagingLoss.package_size_id == size_id,
                _brand(PackagingLoss.brand_id),
                _pelanggan(PackagingLoss.pelanggan_id),
            )
        )
    ).scalar_one()
    terpakai = (
        await db.execute(
            select(func.coalesce(func.sum(FinishedGoodsStock.jumlah_karung), 0))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(
                ProductSku.packaging_material_id == material_id,
                ProductSku.package_size_id == size_id,
                _brand(ProductSku.brand_id),
                _jasa_milik_pelanggan(FinishedGoodsStock.jasa_id),
            )
        )
    ).scalar_one()
    return int(beli) - int(hilang) - int(terpakai)


# `hpp_kemasan_wavg` DIBUANG 28 September 2026. Satu-satunya pembacanya
# `hitung_hpp_beras`, yang ikut dibuang bersama seluruh harga.
#
# Yang MENULIS harga karung tetap ada dan memang harus: "Beli karung" adalah
# catatan pembelian sungguhan, bukan penilaian ulang. Kolomnya terisi untuk
# keuangan; yang berhenti cuma menghitung rata-ratanya di sini. Kode yang tak
# punya pembaca akan dikira masih dipakai.


# ─────────────────────────── Beli / hilang ───────────────────────────
@dataclass
class BeliKemasanResult:
    purchase: PackagingPurchase
    material_nama: str
    ukuran: int
    stok_baru: int
    brand_nama: str | None = None


# Jenis karung BERAS yang WAJIB bermerk (merk atau 'polos'). karung_pk & polos
# (karung byproduct) tidak memakai dimensi merk.
_KARUNG_BERMERK = {"biasa", "laminasi", "putih", "bekas"}


async def beli_kemasan(
    db: AsyncSession, *, user: User, material_kode: str | None, ukuran: int | None,
    jumlah: int | None, brand_nama: str | None = None, tanggal=None, jam=None,
) -> BeliKemasanResult:
    """Catat pembelian karung (staff/admin). Karung beras WAJIB bermerk.

    TANPA HARGA sejak 29 September 2026 (keputusan pemilik). Yang dicatat di
    sini berapa LEMBAR masuk gudang — itu yang dipakai memutuskan kapan membeli
    lagi. Berapa rupiahnya dicatat di tempat uang dicatat.
    """
    if not material_kode or not ukuran or not jumlah:
        raise InventoryError(
            "Sebutkan jenis karung, ukuran, dan jumlah. Contoh: "
            "`beli karung LosPulen laminasi 25kg 2000 lembar`"
        )
    material = await get_material(db, material_kode)
    if material is None:
        raise InventoryError(f"Jenis karung '{material_kode}' tidak ada.")
    size = await get_size(db, ukuran)
    if size is None:
        raise InventoryError(f"Ukuran {ukuran}kg tidak terdaftar.")
    brand_id = None
    if brand_nama:
        brand = await get_brand(db, brand_nama)
        if brand is None:
            raise InventoryError(
                f"Merk '{brand_nama}' tidak ada. Pakai merk terdaftar atau 'polos'."
            )
        brand_id = brand.id
    elif material_kode in _KARUNG_BERMERK:
        raise InventoryError(
            "Sebutkan merk karung (atau `polos`). Contoh: "
            "`beli karung LosPulen laminasi 25kg 1000 lembar`"
        )
    now = input_time(tanggal, jam)
    p = PackagingPurchase(
        kode=await next_packaging_purchase_code(db, now.date()),
        packaging_material_id=material.id, package_size_id=size.id, brand_id=brand_id,
        jumlah_lembar=int(jumlah),
        tanggal=now.date(), waktu=now, input_by=user.id,
    )
    db.add(p)
    await db.flush()
    await log_activity(
        db, table_name="packaging_purchases", record_id=p.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{p.kode} | {brand_nama or '-'} {material.kode} {ukuran}kg x{jumlah}",
    )
    await db.commit()
    await db.refresh(p)
    stok = await hitung_stok_kemasan(db, material.id, size.id, brand_id)
    return BeliKemasanResult(purchase=p, material_nama=material.nama, ukuran=ukuran,
                             stok_baru=stok, brand_nama=brand_nama)


# ─────────────────────────── Pindah kepemilikan ───────────────────────────
#
# Kebalikan ARAH dari `pindah_kepemilikan_barang_jadi`/`_broken_curah`
# (finished_goods.py): di sana barang MULAI milik jasa (diturunkan dari
# tiket timbang) dan admin mengambil SISA yang tak terpakai balik ke pabrik.
# Karung tak punya tiket — `beli_kemasan()` selalu menulis `pelanggan_id=
# NULL` — jadi satu-satunya arah yang berarti di sini kebalikannya: admin
# mengetik SEBAGIAN lembar yang sudah dibeli pabrik untuk dipindah MENJADI
# milik satu KONTAK pelanggan (dicatat sebagai biaya/alokasi tersendiri).
# Mekanismenya SAMA (FIFO, baris tertua dulu, dipecah bila jumlahnya jatuh
# di tengah satu baris) — cuma arahnya yang dibalik, mengikuti dari mana
# karung ini sesungguhnya BERASAL (selalu pabrik).
#
# ⚠ PELANGGAN, BUKAN JASA — koreksi pemilik 7 Oktober 2026: *"jalur masuk
# karung untuk jasa bukan berdasarkan proses jasa. tetapi berdasarkan
# kontak pelanggan."* Karung bukan barang yang "dikembalikan" per pesanan
# (beda dari gabah/PK/beras/broken/bekatul, sebelas tabel ber-`jasa_id`
# lain) — yang dilacak rekening per KONTAK, supaya pelanggan yang datang
# berulang (`Jasa` baru tiap kedatangan) tetap SATU rekening karung, bukan
# terpecah ulang tiap kedatangan.
async def pindah_kepemilikan_karung(
    db: AsyncSession, *, user: User, material_kode: str, ukuran: int,
    brand_nama: str | None, pelanggan_id: int, jumlah_lembar: int,
) -> int:
    """Pindah N lembar karung dari milik PABRIK ke satu KONTAK pelanggan.

    Identitas kombinasinya KODE/nama, bukan id mentah — sama persis dengan
    `beli_kemasan()`, supaya kartu stok (`karung_blok`) bisa membangun nilai
    tombolnya langsung dari field yang SUDAH ADA di baris `stok_kemasan_
    rinci` (`kode`, `ukuran`, `merk`), tanpa membawa id database ke markup.

    Mengembalikan jumlah lembar yang berpindah (selalu `jumlah_lembar`
    persis — dipecah dari baris pembelian pabrik, FIFO, tertua dulu).
    """
    if not pelanggan_id:
        raise InventoryError("Sebutkan pelanggan tujuan.")
    if not jumlah_lembar or jumlah_lembar <= 0:
        raise InventoryError("Sebutkan jumlah lembar yang dipindah, lebih dari 0.")
    material = await get_material(db, material_kode)
    if material is None:
        raise InventoryError(f"Jenis karung '{material_kode}' tidak ada.")
    size = await get_size(db, ukuran)
    if size is None:
        raise InventoryError(f"Ukuran {ukuran}kg tidak terdaftar.")
    brand_id = None
    if brand_nama:
        brand = await get_brand(db, brand_nama)
        if brand is None:
            raise InventoryError(f"Merk '{brand_nama}' tidak ada.")
        brand_id = brand.id
    material_id, size_id = material.id, size.id
    tersedia = await hitung_stok_kemasan(db, material_id, size_id, brand_id, pelanggan_id=None)
    if jumlah_lembar > tersedia:
        raise InventoryError(
            f"Stok karung pabrik tinggal {tersedia} lembar — "
            f"tak bisa memindahkan {jumlah_lembar} lembar.")

    def _brand(col):
        return col.is_(None) if brand_id is None else col == brand_id

    # Baris sumbernya DIKUNCI sebelum dipecah — dua admin yang memindahkan
    # kombinasi karung yang sama pada detik yang sama akan memecah baris
    # yang sama, bukan dua baris berbeda yang jumlahnya diam-diam dobel.
    rows = (await db.execute(
        select(PackagingPurchase)
        .where(PackagingPurchase.packaging_material_id == material_id,
               PackagingPurchase.package_size_id == size_id,
               _brand(PackagingPurchase.brand_id),
               PackagingPurchase.pelanggan_id.is_(None))
        .order_by(PackagingPurchase.tanggal.asc(), PackagingPurchase.waktu.asc(),
                   PackagingPurchase.id.asc())
        .with_for_update()
    )).scalars().all()

    sisa = jumlah_lembar
    now = now_local()
    baris_disentuh: list[int] = []
    for row in rows:
        if sisa <= 0:
            break
        baris_disentuh.append(row.id)
        if row.jumlah_lembar <= sisa:
            row.pelanggan_id = pelanggan_id
            sisa -= row.jumlah_lembar
        else:
            row.jumlah_lembar -= sisa
            # TANPA `harga_per_lembar` — kolom uang, dan sejak 29 September
            # 2026 tak boleh ditulis lagi oleh layanan mana pun (keputusan
            # pemilik), termasuk menyalinnya dari baris asal.
            db.add(PackagingPurchase(
                kode=await next_packaging_purchase_code(db, now.date()),
                packaging_material_id=row.packaging_material_id,
                package_size_id=row.package_size_id, brand_id=row.brand_id,
                jumlah_lembar=sisa,
                tanggal=now.date(), waktu=now, input_by=user.id,
                pelanggan_id=pelanggan_id,
            ))
            sisa = 0
    await log_activity(
        db, table_name="packaging_purchases", record_id=baris_disentuh[0],
        action="UPDATE", changed_by=user.id, field_name="pelanggan_id",
        new_value=f"{jumlah_lembar} lembar → pelanggan",
        aksi="pindah_kepemilikan_karung",
    )
    await db.commit()
    return jumlah_lembar


def kemasan_gudang(material_kode: str | None) -> str:
    """Lokasi fisik kemasan: karung PK selalu di GUDANG 1 (membungkus PK), semua
    kemasan lain di GUDANG 2 (mengemas beras jadi)."""
    return "Gudang 1" if (material_kode or "").lower() == "karung_pk" else "Gudang 2"


#: Urutan gudang pada daftar stok karung. Gudang 2 lebih dulu karena di
#: sanalah karung habis: hampir seluruh kemasan dipakai mengemas beras jadi,
#: dan karung PK di Gudang 1 cuma satu jenis.
_URUT_GUDANG = ("Gudang 2", "Gudang 1")


async def stok_kemasan_rinci(
    db: AsyncSession, *, pelanggan_id: int | list[int] | None = None,
) -> list[dict]:
    """Stok tiap kombinasi karung yang pernah dibeli — satu baris per kombinasi.

    `pelanggan_id`=None (bawaan) → PABRIK, dipakai `/stok-karung`. Daftar KOMBINASI
    (jenis×ukuran×merk) sendiri selalu diturunkan dari SELURUH pembelian tanpa
    saring pemilik — kombinasi yang sama dipakai menanyakan stok pabrik MAUPUN
    stok jasa, cuma angkanya yang berbeda per pemanggilan `/stok-karung-jasa`.

    Satu sumber untuk DUA pembaca: laporan teks "Stok karung" dan blok Stok
    karung di layar Stok (Meja & Pos Produksi, keputusan pemilik 23 September
    2026). Dulu hitungannya hidup di dalam penyusun teks laporan, jadi layar
    yang ingin menggambarnya harus menyusun ulang aturan yang sama — dan
    aturan yang disalin ke dua tempat akan berselisih pada perubahan
    berikutnya, justru pada angka yang dipakai memutuskan kapan memesan.

    Tidak ada HARGA di sini, dan itu bukan kelupaan: blok ini dibaca juga oleh
    yang tak boleh melihat angka uang, dan satuan yang ditanyakan orang saat
    melihat tumpukan karung adalah LEMBAR. Harga rata-ratanya ada pada
    `hpp_kemasan_wavg` bagi yang memang memerlukannya.

    `menipis` dihitung di sini, bukan di layar: batasnya satu setelan
    (`min_kemasan_lembar`), dan dua layar yang masing-masing
    membandingkannya sendiri adalah dua layar yang bisa berbeda pendapat
    tentang kapan karung disebut hampir habis.
    """
    combos = (
        await db.execute(
            select(PackagingPurchase.packaging_material_id,
                   PackagingPurchase.package_size_id,
                   PackagingPurchase.brand_id)
            .distinct()
        )
    ).all()
    minimum = settings.min_kemasan_lembar
    keluar: list[dict] = []
    for mat_id, size_id, brand_id in combos:
        mat = await db.get(PackagingMaterial, mat_id)
        size = await db.get(PackageSize, size_id)
        brand = await db.get(Brand, brand_id) if brand_id else None
        stok = await hitung_stok_kemasan(db, mat_id, size_id, brand_id, pelanggan_id=pelanggan_id)
        keluar.append({
            "gudang": kemasan_gudang(mat.kode if mat else None),
            "kode": mat.kode if mat else None,
            "nama": mat.nama if mat else "-",
            "merk": brand.nama if brand else None,
            "ukuran": int(size.ukuran_kg) if size else 0,
            "lembar": int(stok),
            "menipis": stok <= minimum,
        })
    keluar.sort(key=lambda b: (_URUT_GUDANG.index(b["gudang"])
                               if b["gudang"] in _URUT_GUDANG else 9,
                               b["nama"], b["merk"] or "", b["ukuran"]))
    return keluar


async def pelanggan_ids_dengan_karung(db: AsyncSession) -> list[int]:
    """Kontak pelanggan yang punya karung dialokasikan ke mereka — dipakai
    `/stok-karung-jasa`.

    Langsung dari `PackagingPurchase.pelanggan_id` (DISTINCT), tanpa
    indirection lewat `Jasa` — beda dari padanan di produk jadi
    (`jasa_ids_per_pelanggan_dengan_hasil`), sebab kolomnya sendiri sudah
    menunjuk KONTAK, bukan pesanan (lihat catatan panjang di
    `pindah_kepemilikan_karung`).
    """
    return list((await db.execute(
        select(PackagingPurchase.pelanggan_id.distinct())
        .where(PackagingPurchase.pelanggan_id.isnot(None))
        .order_by(PackagingPurchase.pelanggan_id)
    )).scalars().all())


async def laporan_stok_kemasan(db: AsyncSession) -> str:
    """Stok kombinasi karung yang pernah dibeli, DIKELOMPOKKAN per gudang
    (karung PK di Gudang 1, sisanya di Gudang 2) + warn di bawah minimum."""
    baris = await stok_kemasan_rinci(db)
    if not baris:
        return "📦 Belum ada stok kemasan (belum ada pembelian karung)."
    per_gudang: dict[str, list[str]] = {}
    for b in baris:
        merk = f"{b['merk']} " if b["merk"] else ""
        teks = (
            f"• {merk}{b['nama']} {b['ukuran']}kg: "
            f"{b['lembar']:,} lembar{'  ⚠️ menipis' if b['menipis'] else ''}"
        ).replace(",", ".")
        per_gudang.setdefault(b["gudang"], []).append(teks)
    lines = ["📦 Stok kemasan:"]
    for gudang in _URUT_GUDANG:
        if gudang in per_gudang:
            lines.append(f"\n🏬 {gudang}:")
            lines.extend(per_gudang[gudang])
    return "\n".join(lines)
