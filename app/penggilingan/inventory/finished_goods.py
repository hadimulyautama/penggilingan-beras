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
    BrokenKeSilo,
    ByproductPrice,
    ByproductStock,
    FinishedGoodsStock,
    OutgoingItem,
    OutgoingRecord,
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
        if not grade:
            raise InventoryError(
                "Pilih mutu beras: Premium, Super, Medium, atau Sayur. "
                "Beras putih harus dipacking sesuai mutu hasil penyosohan."
            )
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
        .where(FinishedGoodsStock.source_type == "polishing",
               FinishedGoodsStock.source_id == proc_id,
               ProductSku.kategori == kategori)
    )
    if std_id is None:
        q = q.where(FinishedGoodsStock.rice_quality_standard_id.is_(None))
    else:
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


async def _broken_dibukukan(db: AsyncSession, proc_id: int) -> float:
    """Broken penyosohan ini yang SUDAH punya rumah — sebangun `_bekatul_
    dibukukan` (lihat catatan panjangnya di sana). Keputusan pemilik 6
    Oktober 2026: broken kini punya jalan CURAH juga (`catat_broken` →
    `byproduct_stock`), supaya ia bisa dipindah ke silo broken untuk disosoh
    ulang — jalan kedua, sama seperti bekatul, yang wajib saling mengurangi
    dengan yang dikarungi."""
    curah = float((await db.execute(
        select(func.coalesce(func.sum(ByproductStock.berat_kg), 0))
        .where(ByproductStock.jenis_produk == "broken",
               ByproductStock.source_type == "polishing",
               ByproductStock.source_id == proc_id)
    )).scalar_one())
    return curah + await _packed_kg(db, proc_id, "broken", None)


async def catat_bekatul(
    db: AsyncSession, *, user, kode_pol: str | None, berat_kg: float | None,
    tanggal=None, jam=None,
) -> float:
    """Catat bekatul CURAH hasil penyosohan → byproduct_stock (per kg).

    ⚠ `kode_pol` WAJIB eksplisit sejak 8 Oktober 2026 — TIDAK ADA fallback
    "proses terbaru" (`_proc_by_kode(None)` dulu diam-diam memilih proses
    yang PALING BARU DIBUAT). Insiden lapangan sungguhan atas `catat_broken`
    (pagar sebangun, lihat docstringnya) membuktikan jalan itu bisa
    mendaratkan catatan di proses yang salah. Guard "belum ada catatan
    hasil → dilewati" di bawah TETAP DIBIARKAN untuk bekatul — beda dari
    broken — sebab itu kesepakatan sadar, bukan celah yang terlewat.
    """
    if not berat_kg:
        raise InventoryError("Sebutkan berat bekatulnya (kg).")
    if not kode_pol:
        raise InventoryError("Sebutkan proses penyosohannya (POL-...).")
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
    # Bekatul dari proses jasa tetap milik pesanan. Menjadi milik pabrik
    # memerlukan aksi eksplisit `pindah_kepemilikan_bekatul_curah` setelah
    # dibukukan. `pemilik_hasil_proses` mempertahankan aturan ini.
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


async def catat_broken(
    db: AsyncSession, *, user, kode_pol: str | None, berat_kg: float | None,
    tanggal=None, jam=None,
) -> float:
    """Catat broken CURAH hasil penyosohan → byproduct_stock (per kg).

    Sebangun `catat_bekatul`. Keputusan pemilik 6 Oktober 2026: broken punya
    silonya sendiri, dan jalan ke sana ("Pindah broken ke silo") memindahkan
    dari SINI — baris `byproduct_stock` inilah "sumber"-nya (lihat
    `BrokenKeSilo`). Tanpa langkah ini, broken yang baru keluar mesin tak
    pernah jadi baris yang bisa dipindah; ia cuma tersimpan sebagai log
    `polishing_output_logs` yang tak bisa dirujuk.

    ⚠ `jasa_id` DIISI (beda dari bekatul): broken KEMBALI ke pelanggan
    (keputusan pemilik 12 — hanya sekam & bekatul yang ditahan pabrik), jadi
    broken dari proses jasa tetap barang titipan. `pemilik_hasil()` yang
    memutuskan, bukan cabang di sini — kalau suatu hari sebuah pesanan sepakat
    brokennya DITAHAN juga, yang berubah cuplikan kesepakatannya.

    ⚠⚠ DUA PAGAR DITAMBAH 8 Oktober 2026, dari insiden lapangan sungguhan
    (bukan dugaan): "catat broken 5.000 kg" mendarat di proses yang BARU
    DIBUAT 3 menit sebelumnya dan belum punya satu baris hasil mesin pun —
    bukan proses yang operator maksud.

      1. `kode_pol` kini WAJIB eksplisit — TIDAK ADA fallback "proses
         terbaru" (`_proc_by_kode(None)` dulu diam-diam memilih proses yang
         PALING BARU DIBUAT, bukan yang punya broken). Sebangun
         `masukkan_broken_ke_silo`.
      2. Proses yang BELUM punya satu baris `polishing_output_logs` broken
         pun kini DITOLAK, bukan dilewati. BEDA dari `catat_bekatul`
         (SENGAJA dibiarkan — pabrik historisnya tak selalu menimbang
         bekatul di mesin): broken SELALU salah satu pilihan wajib di
         "Catat hasil penyosohan" (`_ALL_JENIS`), jadi "belum ada
         catatannya" untuk broken bukan praktik normal — ia pertanda proses
         yang salah dipilih, persis insiden ini.
    """
    if not berat_kg:
        raise InventoryError("Sebutkan berat broken-nya (kg).")
    if not kode_pol:
        raise InventoryError("Sebutkan proses penyosohannya (POL-...).")
    proc = await _proc_by_kode(db, kode_pol)
    from app.services.stok import output_sosoh

    keluar_mesin = (await output_sosoh(db, proc.id)).get("broken")
    if keluar_mesin is None:
        raise InventoryError(
            f"{proc.kode_proses} belum punya satu baris pun hasil broken "
            "tercatat ('Catat hasil penyosohan') — periksa lagi prosesnya; "
            "broken selalu wajib dicatat di mesin dulu, bukan diasumsikan.")
    sisa = float(keluar_mesin) - await _broken_dibukukan(db, proc.id)
    if float(berat_kg) > sisa + 0.5:
        raise InventoryError(
            f"{proc.kode_proses} tinggal {sisa:,.0f} kg broken yang belum "
            f"dibukukan — tak bisa mencatat {float(berat_kg):,.0f} kg. "
            f"(Keluar mesin {float(keluar_mesin):,.0f} kg; sudah dicatat "
            f"curah atau dikarungi {float(keluar_mesin) - sisa:,.0f} kg.)"
            .replace(",", "."))
    now = input_time(tanggal, jam)
    from app.services.jasa import pemilik_hasil_proses

    db.add(ByproductStock(
        jenis_produk="broken", source_type="polishing", source_id=proc.id,
        berat_kg=berat_kg, tanggal=now.date(), waktu=now, input_by=user.id,
        jasa_id=await pemilik_hasil_proses(db, proc.jasa_id, "broken"),
    ))
    await log_activity(
        db, table_name="byproduct_stock", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"broken {berat_kg:.0f}kg",
    )
    await db.commit()
    return float(berat_kg)


# ─────────────────────────── Stok ───────────────────────────
async def hitung_stok_bekatul(
    db: AsyncSession, *, jasa_id: int | list[int] | None = None,
) -> float:
    """Stok bekatul curah (kg) = masuk − keluar (barang keluar byproduct_curah).

    `jasa_id` SENGAJA bawaannya `None` (pabrik) — pola yang sama dengan
    `hitung_stok_broken_curah`. ⚠ Saringan pemilik ditulis sejak awal walau
    dulu "hasilnya selalu sama" (bekatul SELALU `jasa_id` NULL, keputusan
    pemilik 12) — justru supaya SIAP begitu suatu hari sebuah pesanan sepakat
    bekatulnya KEMBALI. Hari itu datang 6 Oktober 2026: bekatul dicabut dari
    `HASIL_DITAHAN_BAWAAN`, dan parameter ini yang membuat pembalikannya tak
    perlu menulis ulang fungsi ini — cuma memanggilnya dengan `jasa_id` terisi.
    """
    def milik(k):
        if jasa_id is None:
            return k.jasa_id.is_(None)
        if isinstance(jasa_id, (list, tuple, set, frozenset)):
            return k.jasa_id.in_(jasa_id)
        return k.jasa_id == jasa_id

    masuk = (
        await db.execute(
            select(func.coalesce(func.sum(ByproductStock.berat_kg), 0)).where(
                ByproductStock.jenis_produk == "bekatul", milik(ByproductStock),
            )
        )
    ).scalar_one()
    # `milik(OutgoingItem)` — lihat catatan panjang di `hitung_stok_
    # byproduct_curah` (migrasi 0080, kolom yang sama).
    keluar = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
            .where(OutgoingItem.item_type == "byproduct_curah",
                   OutgoingItem.jenis_byproduct == "bekatul",
                   milik(OutgoingItem))
        )
    ).scalar_one()
    return float(masuk) - float(keluar)


async def hitung_stok_broken_curah(
    db: AsyncSession, *, jasa_id: int | list[int] | None = None,
) -> float:
    """Stok broken curah (kg), BELUM dipindah ke silo = masuk − keluar − terpakai.

    TIGA suku, bukan dua — beda dari `hitung_stok_bekatul` (yang tak punya
    jalan "dipakai lagi sebagai bahan"). Keputusan pemilik 6 Oktober 2026,
    bagian 3: *"broken yang dipakai sebagai BAHAN tidak muncul di salah satu
    pun [masuk/keluar]... akibatnya broken yang sudah masuk mesin tetap
    terhitung sebagai stok yang bisa dijual."* `terpakai` di sini = yang
    sudah DIPINDAH ke silo broken (`broken_ke_silo`) — bukan menunggu ia
    sungguh disosoh ulang, sama seperti `hitung_stok_tumpukan` mengurangi PK
    yang sudah dipindah ke silo, bukan menunggu ia disosoh.

    `jasa_id` SENGAJA bukan "pabrik"/"jasa"/"semua" seperti `hitung_stok_
    silo`: bawaannya `None` (pabrik), dan pemanggil yang ingin tahu sisa satu
    pesanan jasa menyebutnya terang-terangan — pola yang sama dengan
    `hitung_stok_finished_goods`. BOLEH DAFTAR, sebangun `stok_produk()`
    (6 Oktober 2026, koreksi "per pelanggan bukan per pesanan"): satu
    pelanggan boleh punya beberapa `Jasa`, dan sisa curahnya WAJIB dijawab
    sebagai satu angka gabungan, bukan dijumlah belakangan oleh pemanggil.

    ⚠ `keluar` kini ikut disaring pemiliknya (`OutgoingItem.jasa_id`,
    migrasi 0080 — dulu lewat `OutgoingRecord.jasa_id`, sebelum itu TIDAK
    disaring sama sekali, cacat yang sempat ada juga di `stok_produk()`
    sebelum perbaikan 6 Oktober, lihat catatan panjang di sana). Jalur jual
    broken curah sudah ADA sejak "Pengambilan barang jasa" (11 Oktober
    2026), jadi suku ini tak lagi dorman — tetap perlu benar sekarang.
    """
    def milik(k):
        if jasa_id is None:
            return k.jasa_id.is_(None)
        if isinstance(jasa_id, (list, tuple, set, frozenset)):
            return k.jasa_id.in_(jasa_id)
        return k.jasa_id == jasa_id

    masuk = float((
        await db.execute(
            select(func.coalesce(func.sum(ByproductStock.berat_kg), 0)).where(
                ByproductStock.jenis_produk == "broken", milik(ByproductStock),
            )
        )
    ).scalar_one())
    # `milik(OutgoingItem)` — lihat catatan panjang di `hitung_stok_
    # byproduct_curah` (migrasi 0080, kolom yang sama).
    keluar = float((
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
            .where(OutgoingItem.item_type == "byproduct_curah",
                   OutgoingItem.jenis_byproduct == "broken",
                   milik(OutgoingItem))
        )
    ).scalar_one())
    terpakai = float((
        await db.execute(
            select(func.coalesce(func.sum(BrokenKeSilo.berat_kg), 0))
            .where(milik(BrokenKeSilo))
        )
    ).scalar_one())
    return masuk - keluar - terpakai


async def hitung_stok_byproduct_curah(
    db: AsyncSession, jenis: str, *, jasa_id: int | list[int] | None = None,
) -> float:
    """Stok hasil samping CURAH (kg) per JENIS = masuk − keluar, satu fungsi
    untuk KEEMPAT jenis (`bekatul`, `broken`, `menir`, `reject`).

    Pesan kerja 11, butir 1 — satu-satunya cacat di sini yang SEDANG BERJALAN
    di pabrik hari ini. `barang_keluar.tersedia()` dulu memanggil
    `hitung_stok_bekatul()` apa pun `jenis`-nya diminta: "tersedia('menir')"
    menjawab stok BEKATUL berlabel "Menir", dan Admin bisa menerbitkan
    perintah muat menir yang tak ada satu kilo pun, tanpa satu pun galat.

    `jenis == "bekatul"`/`"broken"` DIDELEGASIKAN ke `hitung_stok_bekatul()`/
    `hitung_stok_broken_curah()` — bukan disalin ulang. Keduanya punya
    nuansa sendiri yang tak boleh hilang: bekatul punya DUA rumah (curah +
    dikarungi 40 kg, keputusan 28 Sep), broken punya SUKU KETIGA (`terpakai`
    = sudah dipindah ke silo broken untuk disosoh ulang). `menir`/`reject`
    (dan jenis baru yang lahir nanti) TAK PUNYA nuansa semacam itu — dua
    suku polos sudah cukup, dan itu yang dihitung langsung di sini.
    """
    if jenis == "bekatul":
        return await hitung_stok_bekatul(db, jasa_id=jasa_id)
    if jenis == "broken":
        return await hitung_stok_broken_curah(db, jasa_id=jasa_id)

    def milik(k):
        if jasa_id is None:
            return k.jasa_id.is_(None)
        if isinstance(jasa_id, (list, tuple, set, frozenset)):
            return k.jasa_id.in_(jasa_id)
        return k.jasa_id == jasa_id

    masuk = float((
        await db.execute(
            select(func.coalesce(func.sum(ByproductStock.berat_kg), 0)).where(
                ByproductStock.jenis_produk == jenis, milik(ByproductStock),
            )
        )
    ).scalar_one())
    # `milik(OutgoingItem)` — BUKAN `OutgoingRecord` lagi (migrasi 0080):
    # truk boleh menggabung beberapa pesanan satu pelanggan, dan transaksi
    # semacam itu punya `OutgoingRecord.jasa_id` NULL walau barisnya sendiri
    # tetap tahu pemiliknya masing-masing lewat `OutgoingItem.jasa_id`.
    keluar = float((
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
            .where(OutgoingItem.item_type == "byproduct_curah",
                   OutgoingItem.jenis_byproduct == jenis,
                   milik(OutgoingItem))
        )
    ).scalar_one())
    return masuk - keluar


async def hitung_stok_byproduct_total(
    db: AsyncSession, jenis: str, *, jasa_id: int | None = None,
) -> float:
    """Saldo hasil samping yang bisa keluar, termasuk saldo otomatis kartu.

    Kartu Stok Produk menganggap sisa output menir/reject/broken/bekatul
    sebagai stok tersedia meski belum ada transaksi packing manual. Sebelumnya
    pemilih barang keluar dan pengambilan jasa hanya menjumlah baris
    `FinishedGoodsStock`/`ByproductStock`, sehingga stok terlihat di kartu
    tetapi tak tersedia di picker.

    `stok_produk` adalah sumber saldo yang sama dengan tampilan: ia sudah
    mengurangi barang keluar, barang yang masuk silo, dan memisahkan pemilik.
    Tidak ada siklus pemanggilan karena `stok_produk` tidak memanggil fungsi
    total ini.
    """
    from app.services.stok import stok_produk

    kartu = next((k for k in await stok_produk(db, jasa_id=jasa_id)
                  if k.jenis == jenis), None)
    return max(float(kartu.sisa_kg), 0.0) if kartu else 0.0


async def hitung_stok_finished_goods(
    db: AsyncSession, sku_id: int, standard_id: int | None,
    *, jasa_id: int | None = None,
) -> dict:
    """Stok barang jadi (karung, kg) per SKU+grade = masuk produksi − keluar.

    `jasa_id` memilih MILIK SIAPA yang dihitung, dan bawaannya PABRIK (None) —
    bukan "semua". Bawaan yang aman arahnya satu: fungsi ini memberi makan
    borang barang keluar, dan borang itu menjual. Bawaan "semua" berarti setiap
    pemanggil yang lupa menyebutnya akan menawarkan beras pelanggan untuk
    dijual, tanpa satu pun galat.

    Dengan `jasa_id` terisi ia menjawab pertanyaan yang berbeda: berapa barang
    pesanan itu yang belum diambil pemiliknya. Satu fungsi, satu rumus, dua
    pertanyaan — bukan dua fungsi yang suatu hari berbeda cara menghitungnya.
    """
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
                   # Tanpa saringan pemilik, beras pelanggan terhitung sebagai
                   # stok pabrik lalu pabrik menjualnya — bukan angka yang
                   # salah, barang orang lain yang terjual, dan itu tak bisa
                   # diperbaiki dengan pembetulan pembukuan. Dan ia tak
                   # melempar satu pun kesalahan.
                   FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None
                   else FinishedGoodsStock.jasa_id == jasa_id)
        ))
    ).one()
    # ⚠ YANG KELUAR DISARING PEMILIK JUGA, dan kalau tidak angkanya mustahil.
    #
    # Masuk disaring (pabrik atau pesanan itu), keluar tidak: maka pengambilan
    # pelanggan akan dikurangkan dari stok PABRIK — stok pabrik menyusut karena
    # barang orang lain diambil, dan pesanan jasanya tampak tak pernah berkurang.
    # Dua kesalahan dari satu saringan yang terlupa.
    #
    # Dibaca dari `outgoing_items.jasa_id` LANGSUNG (migrasi 0080) — BUKAN
    # `outgoing_records.jasa_id`. Dulu satu truk selalu satu pesanan, jadi
    # keduanya selalu sama; sejak truk boleh menggabung beberapa pesanan
    # satu pelanggan (keputusan pemilik 11 Oktober 2026), `outgoing_records.
    # jasa_id` jadi NULL tepat pada transaksi semacam itu, dan membaca lewat
    # sana akan membuat barang yang SUDAH diambil lewat truk gabungan
    # terhitung lagi sebagai stok yang masih ada.
    oq = select(
        func.coalesce(func.sum(OutgoingItem.jumlah_karung), 0),
        func.coalesce(func.sum(OutgoingItem.berat_kg), 0),
    ).where(
        OutgoingItem.item_type == "finished_goods",
        OutgoingItem.product_sku_id == sku_id,
        OutgoingItem.jasa_id.is_(None) if jasa_id is None
        else OutgoingItem.jasa_id == jasa_id,
    )
    if standard_id is None:
        oq = oq.where(OutgoingItem.rice_quality_standard_id.is_(None))
    else:
        oq = oq.where(OutgoingItem.rice_quality_standard_id == standard_id)
    ok, okg = (await db.execute(oq)).one()
    return {"karung": int(mk) - int(ok), "kg": float(mkg) - float(okg)}


async def sisa_karung_per_sumber(
    db: AsyncSession, sku_id: int, standard_id: int | None, *,
    jasa_id: int | None = None, proses_id: int | None = None,
    kunci: bool = False,
) -> list[tuple[FinishedGoodsStock, int, float]]:
    """Sisa karung per baris sumber setelah barang keluar dialokasikan FIFO.

    Stok barang jadi menyimpan baris masuk, sedangkan pengiriman dicatat di
    tabel lain. Agar pemilihan ukuran kemasan tidak menawarkan karung yang
    sudah dikirim, jumlah keluar untuk SKU/pemilik itu dialokasikan ke baris
    masuk tertua, sama urutannya dengan FIFO yang dipakai saat mengosongkan
    stok. `proses_id` hanya menyaring hasil setelah alokasi global tersebut.
    """
    def milik(kolom):
        return kolom.is_(None) if jasa_id is None else kolom == jasa_id

    q = select(FinishedGoodsStock).where(
        FinishedGoodsStock.product_sku_id == sku_id,
        FinishedGoodsStock.source_type == "polishing",
        milik(FinishedGoodsStock.jasa_id),
    )
    if standard_id is None:
        q = q.where(FinishedGoodsStock.rice_quality_standard_id.is_(None))
    else:
        q = q.where(FinishedGoodsStock.rice_quality_standard_id == standard_id)
    rows = (await db.execute(q.order_by(FinishedGoodsStock.waktu,
                                       FinishedGoodsStock.id)
                             .with_for_update() if kunci else
                             q.order_by(FinishedGoodsStock.waktu,
                                        FinishedGoodsStock.id))).scalars().all()
    keluar_q = select(func.coalesce(func.sum(OutgoingItem.jumlah_karung), 0)).where(
        OutgoingItem.item_type == "finished_goods",
        OutgoingItem.product_sku_id == sku_id,
        milik(OutgoingItem.jasa_id),
    )
    if standard_id is None:
        keluar_q = keluar_q.where(OutgoingItem.rice_quality_standard_id.is_(None))
    else:
        keluar_q = keluar_q.where(OutgoingItem.rice_quality_standard_id == standard_id)
    keluar = max(0, int((await db.execute(keluar_q)).scalar_one()))
    hasil: list[tuple[FinishedGoodsStock, int, float]] = []
    for row in rows:
        terpakai = min(max(int(row.jumlah_karung), 0), keluar)
        keluar -= terpakai
        tersedia = max(int(row.jumlah_karung) - terpakai, 0)
        if proses_id is not None and row.source_id != proses_id:
            continue
        if tersedia:
            per_karung = (float(row.berat_total_kg) / row.jumlah_karung
                          if row.jumlah_karung else 0.0)
            hasil.append((row, tersedia, per_karung * tersedia))
    return hasil


# ─────────────── Pindah kepemilikan — titipan jadi milik pabrik ───────────────
#
# Keputusan pemilik 6 Oktober 2026, halaman "Produk Jasa": *"nanti bisa
# berpindah kepemilikan menjadi milik kita ... karna bisa jadi produk ataupun
# hasil samping jadi milik kita ataupun kita beli."* Pelanggan kadang sepakat
# menyerahkan sisa barangnya (beras, menir, broken, reject) ke pabrik alih-alih
# mengambilnya — sama seperti bekatul SUDAH beralih milik otomatis (keputusan
# 12), bedanya di sini keputusannya per-pesanan dan ATAS PERMINTAAN, jadi
# butuh tombolnya sendiri, bukan otomatis saat dibukukan.
#
# ⚠ HANYA yang SUDAH TERCATAT (baris `finished_goods_stock`/`byproduct_stock`)
# yang bisa dipindah — sama seperti broken wajib dicatat curah dulu sebelum
# dipindah ke silo. Hasil mesin yang belum dikemas maupun belum dicatat curah
# (kolom "curah" di kartu `stok_produk`) tak punya baris untuk dipindah;
# catat dulu lewat "Catat packing" atau "Catat broken (curah)".
#
# ⚠⚠ BOLEH SEBAGIAN — admin mengetik jumlahnya sendiri, bukan "pindahkan
# semua". FIFO, baris tertua duluan, dipecah bila jumlahnya jatuh di tengah
# satu baris: baris asal dikurangi, baris baru ditulis untuk bagian yang
# berpindah. AMAN walau sebagian sisa pesanan ini sudah diambil pelanggan
# atau sudah dipindah ke silo broken — keduanya disaring lewat `jasa_id`
# pada TABEL LAIN (`outgoing_records`/`broken_ke_silo`), bukan lewat baris
# yang dipindah di sini, jadi aritmetikanya tetap benar: yang dijaga
# hanyalah "jangan memindahkan lebih daripada `tersedia`" — dari situ,
# berapa pun jumlah yang berpindah, sisa pesanan ini turun persis sebesar
# itu, tak peduli baris MANA yang kebetulan dipilih FIFO.


async def pindah_kepemilikan_barang_jadi(
    db: AsyncSession, *, user, sku_id: int, standard_id: int | None,
    jasa_id: int, karung: int,
) -> float:
    """Pindah N karung barang jadi dari pesanan jasa ke milik PABRIK.

    Mengembalikan total kg yang berpindah (karung × ukuran sesungguhnya per
    baris, bisa pecahan bila baris terakhir terpecah).
    """
    from app.models import FinishedGoodsStock

    if not jasa_id:
        raise InventoryError("Barang pabrik tak punya pemilik untuk dipindah.")
    if not karung or karung <= 0:
        raise InventoryError("Sebutkan jumlah karung yang dipindah, lebih dari 0.")
    tersedia = await hitung_stok_finished_goods(db, sku_id, standard_id, jasa_id=jasa_id)
    if karung > tersedia["karung"]:
        raise InventoryError(
            f"Sisa milik pesanan ini tinggal {tersedia['karung']} karung — "
            f"tak bisa memindahkan {karung} karung.")

    def _std(q):
        if standard_id is None:
            return q.where(FinishedGoodsStock.rice_quality_standard_id.is_(None))
        return q.where(FinishedGoodsStock.rice_quality_standard_id == standard_id)

    # Baris sumbernya DIKUNCI sebelum dipecah — dua admin yang memindahkan
    # pesanan yang sama pada detik yang sama akan memecah baris yang sama.
    rows = (await db.execute(_std(
        select(FinishedGoodsStock)
        .where(FinishedGoodsStock.product_sku_id == sku_id,
               FinishedGoodsStock.jasa_id == jasa_id)
        .order_by(FinishedGoodsStock.waktu.asc(), FinishedGoodsStock.id.asc())
        .with_for_update()
    ))).scalars().all()

    sisa = karung
    berat_dipindah = 0.0
    now = now_local()
    baris_disentuh: list[int] = []
    for row in rows:
        if sisa <= 0:
            break
        baris_disentuh.append(row.id)
        if row.jumlah_karung <= sisa:
            row.jasa_id = None
            sisa -= row.jumlah_karung
            berat_dipindah += float(row.berat_total_kg)
        else:
            per_karung = float(row.berat_total_kg) / row.jumlah_karung
            kg_dipindah = per_karung * sisa
            row.jumlah_karung -= sisa
            row.berat_total_kg = float(row.berat_total_kg) - kg_dipindah
            db.add(FinishedGoodsStock(
                product_sku_id=row.product_sku_id,
                rice_quality_standard_id=row.rice_quality_standard_id,
                source_type=row.source_type, source_id=row.source_id,
                jumlah_karung=sisa, berat_total_kg=kg_dipindah,
                warehouse_id=row.warehouse_id, waktu=now, input_by=user.id,
                jasa_id=None,
            ))
            berat_dipindah += kg_dipindah
            sisa = 0
    await log_activity(
        db, table_name="finished_goods_stock", record_id=baris_disentuh[0],
        action="UPDATE", changed_by=user.id, field_name="jasa_id",
        new_value=f"{karung} karung ({berat_dipindah:.0f}kg) → pabrik",
        aksi="pindah_kepemilikan_produk",
    )
    await db.commit()
    return berat_dipindah


async def pindah_kepemilikan_broken_curah(
    db: AsyncSession, *, user, jasa_id: int | list[int], berat_kg: float,
) -> float:
    """Pindah N kg broken CURAH dari pesanan jasa ke milik PABRIK — sebangun
    `pindah_kepemilikan_barang_jadi`, bedanya baris `byproduct_stock` (kg,
    tak berkarung).

    `jasa_id` boleh daftar — satu pelanggan boleh punya beberapa pesanan
    (lihat `stok_produk()`), dan sisa curahnya dijawab sebagai satu angka
    gabungan. Baris yang DIPINDAH tetap dipilih FIFO lintas seluruh
    `jasa_id` dalam daftar itu, bukan satu pesanan saja — kalau tidak,
    pesanan kedua seorang pelanggan bisa menyisakan broken yang tak
    terjangkau tombol ini walau totalnya di kartu masih menunjukkan sisa.
    """
    from app.models import ByproductStock

    if not jasa_id:
        raise InventoryError("Barang pabrik tak punya pemilik untuk dipindah.")
    if not berat_kg or berat_kg <= 0:
        raise InventoryError("Sebutkan berat yang dipindah, lebih dari 0 kg.")
    tersedia = await hitung_stok_broken_curah(db, jasa_id=jasa_id)
    if berat_kg > tersedia + 0.5:
        raise InventoryError(
            f"Sisa broken curah pesanan ini tinggal {tersedia:,.0f} kg — "
            f"tak bisa memindahkan {berat_kg:,.0f} kg.".replace(",", "."))

    milik_jasa = (
        ByproductStock.jasa_id.in_(jasa_id)
        if isinstance(jasa_id, (list, tuple, set, frozenset))
        else ByproductStock.jasa_id == jasa_id
    )
    rows = (await db.execute(
        select(ByproductStock)
        .where(ByproductStock.jenis_produk == "broken", milik_jasa)
        .order_by(ByproductStock.waktu.asc(), ByproductStock.id.asc())
        .with_for_update()
    )).scalars().all()

    sisa = float(berat_kg)
    now = now_local()
    baris_disentuh: list[int] = []
    for row in rows:
        if sisa <= 0.001:
            break
        baris_disentuh.append(row.id)
        baris_kg = float(row.berat_kg)
        if baris_kg <= sisa + 0.001:
            row.jasa_id = None
            sisa -= baris_kg
        else:
            row.berat_kg = baris_kg - sisa
            db.add(ByproductStock(
                jenis_produk="broken", source_type=row.source_type,
                source_id=row.source_id, berat_kg=sisa,
                tanggal=now.date(), waktu=now, input_by=user.id,
                jasa_id=None,
            ))
            sisa = 0
    await log_activity(
        db, table_name="byproduct_stock", record_id=baris_disentuh[0],
        action="UPDATE", changed_by=user.id, field_name="jasa_id",
        new_value=f"{berat_kg:.0f}kg broken → pabrik",
        aksi="pindah_kepemilikan_produk",
    )
    await db.commit()
    return float(berat_kg)


async def pindah_kepemilikan_bekatul_curah(
    db: AsyncSession, *, user, jasa_id: int | list[int], berat_kg: float,
) -> float:
    """Pindah N kg bekatul CURAH dari pesanan jasa ke milik PABRIK.

    Kembaran `pindah_kepemilikan_broken_curah` — baris demi baris sama,
    cuma `jenis_produk` yang beda — DITULIS TERPISAH, bukan digeneralkan jadi
    satu fungsi berparameter `jenis`. Broken sudah lama berjalan dan diuji
    penuh; menggabungkannya dengan bekatul (baru 6 Oktober 2026, pembalikan
    `HASIL_DITAHAN_BAWAAN`) berarti satu baris kode yang salah bisa merusak
    keduanya sekaligus. Dua fungsi kecil yang terpisah > satu fungsi besar
    yang menanggung risiko satu sama lain.
    """
    from app.models import ByproductStock

    if not jasa_id:
        raise InventoryError("Barang pabrik tak punya pemilik untuk dipindah.")
    if not berat_kg or berat_kg <= 0:
        raise InventoryError("Sebutkan berat yang dipindah, lebih dari 0 kg.")
    tersedia = await hitung_stok_bekatul(db, jasa_id=jasa_id)
    if berat_kg > tersedia + 0.5:
        raise InventoryError(
            f"Sisa bekatul curah pesanan ini tinggal {tersedia:,.0f} kg — "
            f"tak bisa memindahkan {berat_kg:,.0f} kg.".replace(",", "."))

    milik_jasa = (
        ByproductStock.jasa_id.in_(jasa_id)
        if isinstance(jasa_id, (list, tuple, set, frozenset))
        else ByproductStock.jasa_id == jasa_id
    )
    rows = (await db.execute(
        select(ByproductStock)
        .where(ByproductStock.jenis_produk == "bekatul", milik_jasa)
        .order_by(ByproductStock.waktu.asc(), ByproductStock.id.asc())
        .with_for_update()
    )).scalars().all()

    sisa = float(berat_kg)
    now = now_local()
    baris_disentuh: list[int] = []
    for row in rows:
        if sisa <= 0.001:
            break
        baris_disentuh.append(row.id)
        baris_kg = float(row.berat_kg)
        if baris_kg <= sisa + 0.001:
            row.jasa_id = None
            sisa -= baris_kg
        else:
            row.berat_kg = baris_kg - sisa
            db.add(ByproductStock(
                jenis_produk="bekatul", source_type=row.source_type,
                source_id=row.source_id, berat_kg=sisa,
                tanggal=now.date(), waktu=now, input_by=user.id,
                jasa_id=None,
            ))
            sisa = 0
    await log_activity(
        db, table_name="byproduct_stock", record_id=baris_disentuh[0],
        action="UPDATE", changed_by=user.id, field_name="jasa_id",
        new_value=f"{berat_kg:.0f}kg bekatul → pabrik",
        aksi="pindah_kepemilikan_produk",
    )
    await db.commit()
    return float(berat_kg)


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
