"""Layanan inventory sub-fase 1: master lookup, SKU on-demand, stok kemasan.

Stok kemasan DITURUNKAN = beli − terpakai − hilang. 'terpakai' menyusul di
sub-fase 2 (packing barang jadi). HPP kemasan = rata-rata tertimbang harga/lembar.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import input_time
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
    "beras_putih": {("biasa", None), ("laminasi", None)},  # ukuran 5/10/25/48/50
    "beras_b": {("biasa", None), ("laminasi", None)},
    "broken": {("putih", 50), ("polos", 25)},
    "menir": {("putih", 50)},
    "reject": {("bekas", 50)},
    "pk": {("karung_pk", 50)},
}
_BERAS_SIZES = {5, 10, 25, 48, 50}


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
    db: AsyncSession, material_id: int, size_id: int, brand_id: int | None = None
) -> int:
    """Stok karung (lembar) per (jenis, ukuran, MERK) = beli − hilang − terpakai.

    `brand_id`=None → cocokkan baris tanpa merk (data lama / byproduct).
    Terpakai = jumlah karung packing (SKU dgn merk+jenis+ukuran sama)."""
    def _brand(col):
        return col.is_(None) if brand_id is None else col == brand_id
    beli = (
        await db.execute(
            select(func.coalesce(func.sum(PackagingPurchase.jumlah_lembar), 0)).where(
                PackagingPurchase.packaging_material_id == material_id,
                PackagingPurchase.package_size_id == size_id,
                _brand(PackagingPurchase.brand_id),
            )
        )
    ).scalar_one()
    hilang = (
        await db.execute(
            select(func.coalesce(func.sum(PackagingLoss.jumlah_lembar), 0)).where(
                PackagingLoss.packaging_material_id == material_id,
                PackagingLoss.package_size_id == size_id,
                _brand(PackagingLoss.brand_id),
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
            )
        )
    ).scalar_one()
    return int(beli) - int(hilang) - int(terpakai)


async def hpp_kemasan_wavg(
    db: AsyncSession, material_id: int, size_id: int, brand_id: int | None = None
) -> float | None:
    """Harga rata-rata tertimbang per lembar (per jenis, ukuran, MERK)."""
    nilai, lembar = (
        await db.execute(
            select(
                func.coalesce(func.sum(PackagingPurchase.jumlah_lembar * PackagingPurchase.harga_per_lembar), 0),
                func.coalesce(func.sum(PackagingPurchase.jumlah_lembar), 0),
            ).where(
                PackagingPurchase.packaging_material_id == material_id,
                PackagingPurchase.package_size_id == size_id,
                PackagingPurchase.brand_id.is_(None) if brand_id is None else PackagingPurchase.brand_id == brand_id,
                PackagingPurchase.harga_per_lembar.isnot(None),
            )
        )
    ).one()
    return float(nilai) / float(lembar) if float(lembar) > 0 else None


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
    jumlah: int | None, brand_nama: str | None = None,
    harga_per_lembar: float | None = None, tanggal=None, jam=None,
) -> BeliKemasanResult:
    """Catat pembelian karung (staff/admin). Karung beras WAJIB bermerk."""
    if not material_kode or not ukuran or not jumlah:
        raise InventoryError(
            "Sebutkan jenis karung, ukuran, dan jumlah. Contoh: "
            "`beli karung LosPulen laminasi 25kg 2000 lembar harga 1500`"
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
        jumlah_lembar=int(jumlah), harga_per_lembar=harga_per_lembar,
        tanggal=now.date(), waktu=now, input_by=user.id,
    )
    db.add(p)
    await db.flush()
    await log_activity(
        db, table_name="packaging_purchases", record_id=p.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{p.kode} | {brand_nama or '-'} {material.kode} {ukuran}kg x{jumlah} @ {harga_per_lembar}",
    )
    await db.commit()
    await db.refresh(p)
    stok = await hitung_stok_kemasan(db, material.id, size.id, brand_id)
    return BeliKemasanResult(purchase=p, material_nama=material.nama, ukuran=ukuran,
                             stok_baru=stok, brand_nama=brand_nama)


def kemasan_gudang(material_kode: str | None) -> str:
    """Lokasi fisik kemasan: karung PK selalu di GUDANG 1 (membungkus PK), semua
    kemasan lain di GUDANG 2 (mengemas beras jadi)."""
    return "Gudang 1" if (material_kode or "").lower() == "karung_pk" else "Gudang 2"


#: Urutan gudang pada daftar stok karung. Gudang 2 lebih dulu karena di
#: sanalah karung habis: hampir seluruh kemasan dipakai mengemas beras jadi,
#: dan karung PK di Gudang 1 cuma satu jenis.
_URUT_GUDANG = ("Gudang 2", "Gudang 1")


async def stok_kemasan_rinci(db: AsyncSession) -> list[dict]:
    """Stok tiap kombinasi karung yang pernah dibeli — satu baris per kombinasi.

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
        stok = await hitung_stok_kemasan(db, mat_id, size_id, brand_id)
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
