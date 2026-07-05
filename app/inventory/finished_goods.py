"""Barang jadi dari penyosohan: packing → finished_goods_stock, bekatul curah,
harga byproduct, HPP beras putih per proses.

Acuan: LOGIKA_PRODUK_JADI_INVENTORY.md + MASTER_RULES_AND_LOGIC.md §14-16.
HPP beras (sama rata semua grade) = (biaya PK silo + biaya kemasan − nilai
byproduct) ÷ total beras. Broken internal GRATIS; broken beli-luar & Beras B
menyusul (sub-fase terpisah).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time, now_local
from app.models import (
    ByproductPrice,
    ByproductStock,
    FinishedGoodsStock,
    OutgoingItem,
    PolishingOutputLog,
    PolishingProcess,
    PolishingSiloUsage,
    ProductSku,
    RiceQualityStandard,
)
from app.services.activity_log import log_activity
from app.gudang2.polishing import BYPRODUCTS, GRADES
from app.gudang2.service import _g2_warehouse_id, hitung_hpp_wavg_silo
from app.inventory.packaging import (
    InventoryError,
    find_or_create_sku,
    get_material,
    get_size,
    get_standard,
    hpp_kemasan_wavg,
)

_BERAS_KATEGORI = {"beras_putih", "beras_b"}


# ─────────────────────────── Harga byproduct (master) ───────────────────────────
async def set_harga_byproduct(
    db: AsyncSession, *, user, jenis: str | None, harga: float | None,
) -> str:
    if not jenis or jenis.lower() not in ("bekatul", "broken", "menir", "reject"):
        raise InventoryError("Jenis byproduct: bekatul / broken / menir / reject.")
    if harga is None:
        raise InventoryError("Sebutkan harganya per kg.")
    jenis = jenis.lower()
    db.add(ByproductPrice(
        jenis=jenis, harga_per_kg=harga, waktu=now_local(), updated_by=user.id,
    ))
    await log_activity(
        db, table_name="byproduct_prices", record_id=0, action="INSERT",
        changed_by=user.id, new_value=f"{jenis}={harga}",
    )
    await db.commit()
    return jenis


async def harga_byproduct(db: AsyncSession, jenis: str) -> float | None:
    v = (
        await db.execute(
            select(ByproductPrice.harga_per_kg)
            .where(ByproductPrice.jenis == jenis)
            .order_by(ByproductPrice.id.desc())
            .limit(1)
        )
    ).scalars().first()
    return float(v) if v is not None else None


# ─────────────────────────── Polishing helpers ───────────────────────────
async def _proc_by_kode(db: AsyncSession, kode: str | None) -> PolishingProcess:
    if not kode:
        rows = (
            await db.execute(select(PolishingProcess).order_by(PolishingProcess.id.desc()).limit(1))
        ).scalars().all()
        if rows:
            return rows[0]
        raise InventoryError("Sebutkan kode proses penyosohan (POL-...).")
    p = (
        await db.execute(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
    ).scalars().first()
    if p is None:
        raise InventoryError(f"Proses {kode} tidak ditemukan.")
    return p


async def _output_map(db: AsyncSession, proc_id: int) -> dict[str, float]:
    rows = (
        await db.execute(
            select(PolishingOutputLog.jenis, PolishingOutputLog.berat_kg,
                   PolishingOutputLog.waktu_update)
            .where(PolishingOutputLog.polishing_process_id == proc_id)
            .order_by(PolishingOutputLog.jenis, PolishingOutputLog.waktu_update.desc())
        )
    ).all()
    out: dict[str, float] = {}
    for jenis, berat, _ in rows:
        if jenis not in out:
            out[jenis] = float(berat)
    return out


# ─────────────────────────── Packing → barang jadi ───────────────────────────
@dataclass
class PackingResult:
    kategori: str
    grade: str | None
    jumlah_karung: int
    berat_total_kg: float
    warning: str | None = None


async def catat_packing(
    db: AsyncSession, *, user, kode_pol: str | None, kategori: str | None,
    grade: str | None = None, brand_nama: str | None = None,
    material_kode: str | None = None, ukuran: int | None = None,
    jumlah_karung: int | None = None, tanggal=None, jam=None,
) -> PackingResult:
    """Catat packing hasil penyosohan → stok barang jadi (kurangi stok karung)."""
    if not kategori:
        raise InventoryError("Sebutkan jenis produk (beras/broken/menir/reject).")
    kategori = kategori.lower()
    if not material_kode or not ukuran or not jumlah_karung:
        raise InventoryError(
            "Sebutkan jenis karung, ukuran, dan jumlah karung. Contoh: "
            "`packing premium merk Imbiss laminasi 25kg 80 karung`"
        )
    proc = await _proc_by_kode(db, kode_pol)
    std_id = None
    if kategori == "beras_putih":
        if grade:
            std = await get_standard(db, grade)
            if std is None:
                raise InventoryError(f"Standar mutu '{grade}' tidak ada.")
            std_id = std.id
    sku = await find_or_create_sku(
        db, kategori=kategori, material_kode=material_kode, ukuran=int(ukuran),
        brand_nama=brand_nama,
    )
    berat = float(jumlah_karung) * int(ukuran)
    now = input_time(tanggal, jam)
    wid = await _g2_warehouse_id(db)
    fg = FinishedGoodsStock(
        product_sku_id=sku.id, rice_quality_standard_id=std_id,
        source_type="polishing", source_id=proc.id, jumlah_karung=int(jumlah_karung),
        berat_total_kg=berat, warehouse_id=wid, waktu=now, input_by=user.id,
    )
    db.add(fg)
    await log_activity(
        db, table_name="finished_goods_stock", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kategori}/{grade or '-'} x{jumlah_karung} ({berat:.0f}kg)",
    )
    await db.commit()

    # Validasi longgar: bandingkan total dikemas vs output run untuk jenis ini.
    warning = None
    outputs = await _output_map(db, proc.id)
    jenis_out = grade if kategori == "beras_putih" else kategori
    out_kg = outputs.get(jenis_out)
    if out_kg is not None:
        packed = await _packed_kg(db, proc.id, kategori, std_id)
        if abs(packed - out_kg) > max(out_kg * 0.02, 50):
            warning = (
                f"⚠️ Terkemas {packed:.0f} kg vs hasil run {out_kg:.0f} kg "
                f"(selisih {packed - out_kg:+.0f} kg)."
            )
    return PackingResult(
        kategori=kategori, grade=grade, jumlah_karung=int(jumlah_karung),
        berat_total_kg=berat, warning=warning,
    )


async def _packed_kg(db: AsyncSession, proc_id: int, kategori: str, std_id: int | None) -> float:
    q = (
        select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
        .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
        .where(FinishedGoodsStock.source_id == proc_id, ProductSku.kategori == kategori)
    )
    if std_id is not None:
        q = q.where(FinishedGoodsStock.rice_quality_standard_id == std_id)
    return float((await db.execute(q)).scalar_one())


async def catat_bekatul(
    db: AsyncSession, *, user, kode_pol: str | None, berat_kg: float | None,
    tanggal=None, jam=None,
) -> float:
    """Catat bekatul CURAH hasil penyosohan → byproduct_stock (per kg)."""
    if not berat_kg:
        raise InventoryError("Sebutkan berat bekatulnya (kg).")
    proc = await _proc_by_kode(db, kode_pol)
    now = input_time(tanggal, jam)
    db.add(ByproductStock(
        jenis_produk="bekatul", source_type="polishing", source_id=proc.id,
        berat_kg=berat_kg, tanggal=now.date(), waktu=now, input_by=user.id,
    ))
    await log_activity(
        db, table_name="byproduct_stock", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"bekatul {berat_kg:.0f}kg",
    )
    await db.commit()
    return float(berat_kg)


# ─────────────────────────── Stok ───────────────────────────
async def hitung_stok_bekatul(db: AsyncSession) -> float:
    """Stok bekatul curah (kg) = masuk − keluar (barang keluar byproduct_curah)."""
    masuk = (
        await db.execute(
            select(func.coalesce(func.sum(ByproductStock.berat_kg), 0)).where(
                ByproductStock.jenis_produk == "bekatul"
            )
        )
    ).scalar_one()
    keluar = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(
                OutgoingItem.item_type == "byproduct_curah",
                OutgoingItem.jenis_byproduct == "bekatul",
            )
        )
    ).scalar_one()
    return float(masuk) - float(keluar)


async def hitung_stok_finished_goods(
    db: AsyncSession, sku_id: int, standard_id: int | None
) -> dict:
    """Stok barang jadi (karung, kg) per SKU+grade = masuk produksi − keluar."""
    def _std(q):
        if standard_id is None:
            return q.where(FinishedGoodsStock.rice_quality_standard_id.is_(None))
        return q.where(FinishedGoodsStock.rice_quality_standard_id == standard_id)

    mk, mkg = (
        await db.execute(_std(
            select(func.coalesce(func.sum(FinishedGoodsStock.jumlah_karung), 0),
                   func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
            .where(FinishedGoodsStock.product_sku_id == sku_id)
        ))
    ).one()
    oq = select(
        func.coalesce(func.sum(OutgoingItem.jumlah_karung), 0),
        func.coalesce(func.sum(OutgoingItem.berat_kg), 0),
    ).where(
        OutgoingItem.item_type == "finished_goods",
        OutgoingItem.product_sku_id == sku_id,
    )
    if standard_id is None:
        oq = oq.where(OutgoingItem.rice_quality_standard_id.is_(None))
    else:
        oq = oq.where(OutgoingItem.rice_quality_standard_id == standard_id)
    ok, okg = (await db.execute(oq)).one()
    return {"karung": int(mk) - int(ok), "kg": float(mkg) - float(okg)}


# ─────────────────────────── HPP beras per proses ───────────────────────────
@dataclass
class HppBeras:
    hpp_per_kg: float | None
    biaya_pk: float
    biaya_kemasan: float
    nilai_byproduct: float
    total_beras_kg: float
    lengkap: bool


async def hitung_hpp_beras(db: AsyncSession, kode_pol: str | None) -> HppBeras:
    """HPP per kg beras putih (sama rata semua grade) untuk 1 proses penyosohan."""
    proc = await _proc_by_kode(db, kode_pol)
    usages = (
        await db.execute(
            select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id == proc.id)
        )
    ).scalars().all()
    biaya_pk = 0.0
    lengkap = True
    for u in usages:
        terpakai = float(u.berat_terpakai_kg or 0)
        if terpakai <= 0:
            continue
        wavg = await hitung_hpp_wavg_silo(db, u.silo_id)
        if wavg is None:
            lengkap = False  # HPP PK silo belum tersedia (upstream belum verif)
            continue
        biaya_pk += wavg * terpakai

    # Biaya kemasan beras (weighted-avg harga/lembar × jumlah karung).
    beras_rows = (
        await db.execute(
            select(FinishedGoodsStock.jumlah_karung, ProductSku.packaging_material_id,
                   ProductSku.package_size_id, ProductSku.brand_id)
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(
                FinishedGoodsStock.source_id == proc.id,
                ProductSku.kategori.in_(list(_BERAS_KATEGORI)),
            )
        )
    ).all()
    biaya_kemasan = 0.0
    for jml, mat_id, size_id, brand_id in beras_rows:
        hk = await hpp_kemasan_wavg(db, mat_id, size_id, brand_id)
        if hk is not None:
            biaya_kemasan += hk * int(jml)

    # Nilai byproduct = output kg × harga acuan.
    outputs = await _output_map(db, proc.id)
    nilai_byproduct = 0.0
    for jenis in BYPRODUCTS:
        kg = outputs.get(jenis, 0.0)
        if kg > 0:
            h = await harga_byproduct(db, jenis)
            if h is not None:
                nilai_byproduct += kg * h

    total_beras = sum(v for k, v in outputs.items() if k in GRADES)
    hpp = None
    if total_beras > 0 and lengkap:
        hpp = (biaya_pk + biaya_kemasan - nilai_byproduct) / total_beras
    return HppBeras(
        hpp_per_kg=hpp, biaya_pk=biaya_pk, biaya_kemasan=biaya_kemasan,
        nilai_byproduct=nilai_byproduct, total_beras_kg=total_beras, lengkap=lengkap,
    )


# ─────────────────────────── Laporan ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_stok_barang_jadi(db: AsyncSession) -> str:
    """Stok barang jadi NET (produksi − keluar) per kategori+grade + bekatul."""
    combos = (
        await db.execute(
            select(FinishedGoodsStock.product_sku_id,
                   FinishedGoodsStock.rice_quality_standard_id).distinct()
        )
    ).all()
    agg: dict[tuple, list] = {}
    for sku_id, std_id in combos:
        sku = await db.get(ProductSku, sku_id)
        std = await db.get(RiceQualityStandard, std_id) if std_id else None
        net = await hitung_stok_finished_goods(db, sku_id, std_id)
        key = (sku.kategori if sku else "-", std.nama if std else None)
        a = agg.setdefault(key, [0, 0.0])
        a[0] += net["karung"]
        a[1] += net["kg"]
    lines = ["📦 Stok barang jadi:"]
    if not agg:
        lines.append("• (kosong)")
    for (kategori, grade), (karung, kg) in sorted(agg.items(), key=lambda x: str(x[0])):
        label = f"{kategori}" + (f" {grade}" if grade else "")
        lines.append(f"• {label}: {karung} karung ({_kg(kg)})")
    bekatul = await hitung_stok_bekatul(db)
    if bekatul != 0:
        lines.append(f"• bekatul (curah): {_kg(bekatul)}")
    return "\n".join(lines)


async def laporan_hpp_beras(db: AsyncSession, kode_pol: str | None) -> str:
    h = await hitung_hpp_beras(db, kode_pol)
    lines = ["🧮 HPP beras putih (per proses):"]
    lines.append(f"• Biaya PK (silo): {_rp(h.biaya_pk)}")
    lines.append(f"• Biaya kemasan: {_rp(h.biaya_kemasan)}")
    lines.append(f"• (−) Nilai byproduct: {_rp(h.nilai_byproduct)}")
    lines.append(f"• Total beras: {_kg(h.total_beras_kg)}")
    if h.hpp_per_kg is not None:
        lines.append(f"➡️ *HPP {_rp(h.hpp_per_kg)}/kg* (sama rata semua grade)")
    else:
        lines.append("➡️ HPP belum lengkap (HPP PK dari Gudang 1 belum diverifikasi).")
    return "\n".join(lines)
