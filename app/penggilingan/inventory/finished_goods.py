"""Barang jadi dari penyosohan: packing → finished_goods_stock, bekatul curah,
harga byproduct, HPP beras putih per proses.

Acuan: LOGIKA_PRODUK_JADI_INVENTORY.md + MASTER_RULES_AND_LOGIC.md §14-16.
HPP beras (sama rata semua grade) = (biaya PK silo + biaya penyosohan + biaya
kemasan − nilai byproduct) ÷ total beras. Biaya penyosohan = konversi PK→beras
(sosoh + tenaga + transport per kg PK + operator flat/proses). Marketing = beban
penjualan, DI LUAR HPP. Broken internal GRATIS; broken beli-luar & Beras B menyusul.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
from app.penggilingan.gudang2.polishing import BYPRODUCTS, GRADES
from app.penggilingan.gudang2.service import _g2_warehouse_id
from app.penggilingan.inventory.packaging import (
    InventoryError,
    find_or_create_sku,
    get_material,
    get_size,
    get_standard,
)

_BERAS_KATEGORI = {"beras_putih", "beras_b"}


# ─────────────────────────── Harga byproduct (master) ───────────────────────────
# `set_harga_byproduct` & `harga_byproduct` DIBUANG 28 September 2026: harga
# keluar dari Pos Produksi (keputusan pemilik). Satu-satunya pembacanya
# `hitung_hpp_beras`, yang ikut dibuang. Kolom & baris harganya TIDAK
# dijatuhkan — itu riwayat, dan keuangan akan memintanya.


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
    """Kumulatif terakhir per jenis — SATU corong, `stok.output_sosoh`.

    Polanya dulu ditulis tiga kali di repo ini (di sini, di `polishing`, dan di
    `report`). Tiga pembaca yang masing-masing menyusun aturan "ambil baris
    terbaru per jenis" akan berselisih pada perubahan berikutnya — dan yang
    berselisih diam-diam adalah angka stok.
    """
    from app.services.stok import output_sosoh

    return await output_sosoh(db, proc_id)


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

    # ── PACKING ADALAH PERPINDAHAN, BUKAN PENCIPTAAN ──
    #
    # Sampai 26 September 2026 fungsi ini menulis stok barang jadi dari udara:
    # tak ada angka asal, jadi tak ada yang bisa dilanggarnya. Yang ada cuma
    # peringatan SESUDAH commit — "terkemas 9.500 vs hasil run 9.000" — yang
    # tak menghentikan apa pun dan hilang begitu layarnya berpindah.
    #
    # Sejak beras curah punya rumah (`stok.beras_curah`), angka asalnya ada:
    # yang keluar mesin dikurangi yang sudah dikemas. Packing yang melebihi itu
    # berarti mengemas beras yang tak pernah keluar dari mesin mana pun — dan
    # itu ditolak SEBELUM menulis, bukan disesali sesudahnya.
    #
    # Kalimatnya menyebut berapa yang tersedia: yang ditolak tanpa angka akan
    # mencoba lagi dengan tebakan.
    from app.services.stok import jenis_produk, output_sosoh

    # Aturan pemetaannya tak lagi ditulis di sini: ia diangkat jadi
    # `stok.jenis_produk` 26 September 2026, dan dibaca juga oleh kartu Stok
    # Produk serta hitungan barang keluar. Empat pembaca yang menyusun sendiri
    # "apa nama barang ini" akan menyebut angka berbeda tentang beras yang sama.
    jenis_out = jenis_produk(kategori, grade)
    keluar = (await output_sosoh(db, proc.id)).get(jenis_out)
    if keluar is None:
        raise InventoryError(
            f"Belum ada hasil sosoh {jenis_out} yang tercatat untuk "
            f"{proc.kode_proses}. Catat hasil penyosohannya dulu — packing "
            "memindahkan beras yang sudah keluar mesin, bukan menciptakannya.")
    sudah = await _packed_kg(db, proc.id, kategori, std_id)
    # Bekatul punya jalan KEDUA — "Catat bekatul (curah)" — dan yang sudah
    # dibukukan di sana tak boleh dikarungi lagi. `_packed_kg` sendirian cuma
    # melihat karung, jadi tanpa baris ini 1.000 kg yang sudah dicatat curah
    # masih bisa dikarungi utuh, dan stok bekatul jadi dua kali lipat.
    if kategori == "bekatul":
        sudah = await _bekatul_dibukukan(db, proc.id)
    tersedia = float(keluar) - sudah
    if berat > tersedia + 0.5:
        raise InventoryError(
            f"{proc.kode_proses} tinggal {tersedia:,.0f} kg {jenis_out} yang "
            f"belum dikemas — tak bisa mengemas {berat:,.0f} kg. "
            f"(Keluar mesin {float(keluar):,.0f} kg, sudah dikemas "
            f"{sudah:,.0f} kg.)".replace(",", "."))

    now = input_time(tanggal, jam)
    wid = await _g2_warehouse_id(db)
    # ── Pemiliknya diturunkan dari PROSESNYA, lewat satu tempat ──
    #
    # `pemilik_hasil()` yang memutuskan, bukan cabang di sini: beras, menir,
    # broken, dan reject kembali ke pelanggan; bekatul beralih milik ke pabrik.
    # Keputusan itu ditaruh SEKALI di hulu supaya saringan stok di hilir tak
    # butuh satu pun cabang khusus — termasuk untuk bekatul, yang justru HARUS
    # muncul di perintah penjualan biasa.
    #
    # `jenis_out` yang dipakai, bukan `kategori`: itu nama barang yang sama
    # yang dibaca kartu Stok Produk dan hitungan barang keluar — empat pembaca
    # yang menyusun sendiri "apa nama barang ini" akan menyebut angka berbeda
    # tentang beras yang sama.
    from app.services.jasa import pemilik_hasil_proses

    pemilik = await pemilik_hasil_proses(db, proc.jasa_id, jenis_out)
    fg = FinishedGoodsStock(
        product_sku_id=sku.id, rice_quality_standard_id=std_id,
        source_type="polishing", source_id=proc.id, jumlah_karung=int(jumlah_karung),
        berat_total_kg=berat, warehouse_id=wid, waktu=now, input_by=user.id,
        jasa_id=pemilik,
    )
    db.add(fg)
    await log_activity(
        db, table_name="finished_goods_stock", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kategori}/{grade or '-'} x{jumlah_karung} ({berat:.0f}kg)",
    )
    await db.commit()

    # Sisa curahnya disebutkan — itu yang dicari orang berikutnya, dan ia
    # tak perlu membuka layar lain untuk tahu masih ada berapa.
    sisa = tersedia - berat
    warning = (f"Sisa {jenis_out} belum dikemas di {proc.kode_proses}: "
               f"{sisa:,.0f} kg.".replace(",", ".") if sisa > 0.5 else None)
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


async def _bekatul_dibukukan(db: AsyncSession, proc_id: int) -> float:
    """Bekatul penyosohan ini yang SUDAH punya rumah — lewat jalan mana pun.

    Sejak 28 September 2026 bekatul punya DUA jalan (keputusan pemilik):
    sebagian dijual curah, sebagian dikarungi 40 kg. Keduanya mengambil dari
    tumpukan yang SAMA — bekatul yang keluar mesin pada penyosohan itu — jadi
    keduanya wajib saling mengurangi.

    Tanpa fungsi ini, 1.000 kg bisa dibukukan curah lalu dikarungi lagi:
    keduanya lolos, stoknya jadi 2.000 kg, dan tak satu pun layar berbunyi.
    Bekatul bukan barang mahal — tetapi angka stok yang bisa dilipatgandakan
    dengan dua ketukan wajar membuat SELURUH layar itu berhenti dipercaya.
    """
    curah = float((await db.execute(
        select(func.coalesce(func.sum(ByproductStock.berat_kg), 0))
        .where(ByproductStock.jenis_produk == "bekatul",
               ByproductStock.source_type == "polishing",
               ByproductStock.source_id == proc_id)
    )).scalar_one())
    return curah + await _packed_kg(db, proc_id, "bekatul", None)


async def catat_bekatul(
    db: AsyncSession, *, user, kode_pol: str | None, berat_kg: float | None,
    tanggal=None, jam=None,
) -> float:
    """Catat bekatul CURAH hasil penyosohan → byproduct_stock (per kg)."""
    if not berat_kg:
        raise InventoryError("Sebutkan berat bekatulnya (kg).")
    proc = await _proc_by_kode(db, kode_pol)
    # ── Tak boleh melebihi yang keluar mesin, DIKURANGI yang sudah dikarungi ──
    #
    # Hanya berlaku bila hasil bekatulnya memang DICATAT pada penyosohan itu.
    # Kalau belum ada catatannya, jalan ini dibiarkan seperti dulu: menolak
    # akan mematikan pencatatan curah yang sudah berjalan bertahun-tahun pada
    # pabrik yang tak selalu menimbang bekatulnya di mesin — dan tanpa catatan
    # hasil, packing juga mustahil, jadi tak ada jalan kedua yang bisa
    # menggandakan angkanya.
    from app.services.stok import output_sosoh

    keluar_mesin = (await output_sosoh(db, proc.id)).get("bekatul")
    if keluar_mesin is not None:
        sisa = float(keluar_mesin) - await _bekatul_dibukukan(db, proc.id)
        if float(berat_kg) > sisa + 0.5:
            raise InventoryError(
                f"{proc.kode_proses} tinggal {sisa:,.0f} kg bekatul yang belum "
                f"dibukukan — tak bisa mencatat {float(berat_kg):,.0f} kg. "
                f"(Keluar mesin {float(keluar_mesin):,.0f} kg; sudah dicatat "
                f"curah atau dikarungi {float(keluar_mesin) - sisa:,.0f} kg.)"
                .replace(",", "."))
    now = input_time(tanggal, jam)
    # ⚠ `jasa_id` SENGAJA TIDAK DIISI, dan itu jawaban yang BENAR — bukan
    # kelalaian. Keputusan pemilik 12: bekatul otomatis BERALIH MILIK ke pabrik.
    # Jadi bekatul dari proses jasa adalah stok pabrik biasa: masuk Stok Produk,
    # boleh diperintahkan keluar, boleh dijual. Jangan membuat penghalang untuk
    # ia — *"bukan berarti barangnya tidak boleh keluar."*
    #
    # ASALNYA tetap terbaca tanpa kolom tambahan: `source_id` menunjuk proses
    # sosohnya, dan prosesnya punya `jasa_id`. Itu yang menjawab "berapa bekatul
    # dari proses barang Pak Budi" — hak yang keputusan 12 tegaskan, dan
    # kuerinya sudah ada di `stok.py` lengkap dengan rincian per proses.
    #
    # Lewat `pemilik_hasil()` juga, bukan ditulis `None` langsung: kalau suatu
    # hari sebuah pesanan sepakat bekatulnya KEMBALI, yang berubah cuplikan
    # kesepakatannya — bukan berkas ini.
    from app.services.jasa import pemilik_hasil_proses

    db.add(ByproductStock(
        jenis_produk="bekatul", source_type="polishing", source_id=proc.id,
        berat_kg=berat_kg, tanggal=now.date(), waktu=now, input_by=user.id,
        jasa_id=await pemilik_hasil_proses(db, proc.jasa_id, "bekatul"),
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
                ByproductStock.jenis_produk == "bekatul",
                # ⚠ Saringan pemilik dipasang di SEMUA pembaca stok pabrik,
                # termasuk yang ini — walau untuk bekatul hasilnya selalu sama.
                #
                # Bekatul jasa memang dibukukan `jasa_id` NULL (beralih milik ke
                # pabrik, keputusan pemilik 12), jadi saringan ini tak membuang
                # satu baris pun hari ini. Ia ditulis supaya tetap benar bila
                # suatu hari sebuah pesanan sepakat bekatulnya KEMBALI — dan
                # supaya pembaca berikutnya tak menyimpulkan "bekatul
                # dikecualikan dari aturan pemilik". Yang mengecualikannya
                # `pemilik_hasil()` di hulu, bukan ketiadaan saringan di sini.
                ByproductStock.jasa_id.is_(None),
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
            .where(FinishedGoodsStock.product_sku_id == sku_id,
                   # ⚠⚠ INI SARINGAN YANG PALING BERBAHAYA KALAU TERLEWAT.
                   #
                   # Fungsi ini menjawab "berapa stok barang jadi pabrik", dan
                   # jawabannya dipakai borang BARANG KELUAR untuk menentukan
                   # berapa yang boleh dijual. Tanpa saringan ini, beras
                   # pelanggan terhitung sebagai stok pabrik lalu pabrik
                   # menjualnya — bukan angka yang salah, barang orang lain yang
                   # terjual, dan itu tak bisa diperbaiki dengan pembetulan
                   # pembukuan. Dan ia tak melempar satu pun kesalahan.
                   FinishedGoodsStock.jasa_id.is_(None))
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
class HppBeras:
    hpp_per_kg: float | None
    biaya_pk: float
    biaya_kemasan: float
    biaya_penyosohan: float
    nilai_byproduct: float
    total_beras_kg: float
    lengkap: bool


# `biaya_penyosohan_proses` dan `hitung_hpp_beras` DIBUANG 28 September 2026.
#
# Keduanya mati dengan sendirinya begitu harga pergi: HPP beras butuh HPP PK
# dan harga hasil samping, dan dua-duanya tak ada lagi. Yang dibiarkan hidup
# akan menjawab "menunggu data lengkap" selamanya — dan blok yang selalu
# kosong mengajari orang berhenti membaca dasbornya.


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_stok_barang_jadi(db: AsyncSession) -> str:
    """Stok barang jadi NET (produksi − keluar) per kategori+grade + bekatul."""
    combos = (
        await db.execute(
            select(FinishedGoodsStock.product_sku_id,
                   FinishedGoodsStock.rice_quality_standard_id)
            # Laporan stok PABRIK — beras pelanggan punya notanya sendiri.
            .where(FinishedGoodsStock.jasa_id.is_(None)).distinct()
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


# `laporan_hpp_beras` DIBUANG 28 September 2026 — lihat catatan di atas.
