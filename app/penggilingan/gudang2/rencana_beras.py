"""Bagian baca/alokasi layanan beras ke silo.

Pemeriksaan dan FIFO yang sebelumnya berada di masukkan_beras_ke_silo
dipakai juga oleh pratinjau. Kunci tetap diambil pada jalur simpan; pembaca
tidak menjalankan pembukuan, audit, penggabungan pemilik, atau mutasi silo.
"""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from app.models import PolishingProcess, PolishingOutputLog, FinishedGoodsStock, ProductSku
from app.penggilingan.inventory.finished_goods import (
    _packed_kg, _proc_by_kode, get_standard, sisa_karung_per_sumber,
    hitung_stok_finished_goods)
from hmu_core import PackageSize
from app.services.stok import _dipindah_silo_proc, output_sosoh


def kunci_query(q, kunci):
    return q.with_for_update() if kunci else q


def berat_karung_nyata(row, jumlah):
    """Bagian berat stok tersimpan; ukuran nominal SKU tidak menambah kg.

    NUMERIC disimpan dua desimal. Sisa di baris asal menyerap pembulatan sen
    kilogram pada pemindahan parsial, sehingga karung terakhir tetap menutup
    berat batch tepat, termasuk 20 karung nominal 50 kg yang nyata 998 kg.
    """
    if not row.jumlah_karung or row.berat_total_kg <= 0:
        return Decimal('0')
    return (Decimal(str(row.berat_total_kg))*jumlah/row.jumlah_karung).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)


async def sumber_karung_beras(db, sku_id, std_id, jasa_id=None, *, kunci=False, proses_id=None):
    rows = await sisa_karung_per_sumber(db, sku_id, std_id, jasa_id=jasa_id,
        source_type=None, kunci=kunci, proses_id=proses_id)
    stok = await hitung_stok_finished_goods(db, sku_id, std_id, jasa_id=jasa_id)
    saldo = max(Decimal('0'), min(Decimal(str(stok['kg'])),
        sum((berat_karung_nyata(row, n) for row, n, _ in rows), Decimal('0'))))
    return rows, saldo


def ambil_karung_nyata(rows, perlu):
    """Rencanakan karung utuh FIFO dan kg nyata yang sama untuk writer/preview."""
    left = Decimal(str(perlu))
    plan = []
    for row, tersedia, _ in rows:
        if left <= Decimal('0.000001'):
            break
        if row.berat_total_kg <= 0 or row.jumlah_karung <= 0:
            continue
        n = min(tersedia, int((left+Decimal('0.005'))*row.jumlah_karung/
                              Decimal(str(row.berat_total_kg))))
        while n > 0 and berat_karung_nyata(row, n) > left+Decimal('0.000001'):
            n -= 1
        if n <= 0:
            break
        kg = berat_karung_nyata(row, n)
        plan.append((row, n, float(kg)))
        left -= kg
    return plan, float(left)


async def curah_beras_sumber(db, jenis, jasa_id=None, *, kunci=False):
    """Saldo curah per proses, dengan pengurang dan urutan layanan lama.

    Pembaca saldo menghabiskan iterator; alokasi berhenti ketika kebutuhan
    terpenuhi, seperti layanan sebelumnya. Pencatatan kecil tidak membaca
    seluruh log proses yang tidak ikut diambil.
    """
    kategori_sku = "beras_b" if jenis == "beras_b" else "beras_putih"
    std = await get_standard(db, jenis)
    proses = (await db.execute(kunci_query(
        select(PolishingProcess)
        .where(PolishingProcess.id.in_(select(
            PolishingOutputLog.polishing_process_id).where(
                PolishingOutputLog.jenis == jenis)),
               PolishingProcess.jasa_id.is_(None) if jasa_id is None
               else PolishingProcess.jasa_id == jasa_id)
        .order_by(PolishingProcess.waktu_mulai, PolishingProcess.id), kunci)
    )).scalars().all()
    for proc in proses:
        hasil = (await output_sosoh(db, proc.id)).get(jenis, 0.0)
        dikemas = await _packed_kg(db, proc.id, kategori_sku,
                                   std.id if std else None)
        dipindah = (await _dipindah_silo_proc(db, [proc.id])).get(
            (proc.id, jenis), 0.0)
        tersedia = max(0.0, float(hasil) - dikemas - dipindah)
        yield proc, tersedia


async def rencana_beras(db, *, jenis, sumber_stok, berat_kg, jasa_id=None,
                       kode_pol=None, kunci=True):
    from app.penggilingan.gudang2.service import Gudang2Error
    kategori_sku = "beras_b" if jenis == "beras_b" else "beras_putih"
    std = await get_standard(db, jenis)
    alokasi: dict[int, float] = {}
    baris_karung: list[tuple[FinishedGoodsStock, int, float]] = []
    baris_curah: list[tuple[FinishedGoodsStock, float]] = []
    rencana_pindah: list[tuple[int | None, str, int | None, int | None, float]] = []
    dibongkar_kg = 0.0

    if sumber_stok == "curah":
        # Curah mengikuti pemilik proses. Angka yang dikemas dari proses itu
        # dikurangi dahulu, lalu sisa curah dialokasikan FIFO lintas proses.
        perlu = berat_kg
        async for proc, tersedia in curah_beras_sumber(db, jenis, jasa_id, kunci=kunci):
            ambil = min(perlu, tersedia)
            if ambil > 0.01:
                alokasi[proc.id] = ambil
                rencana_pindah.append((proc.id, "polishing", proc.id, None, ambil))
                perlu -= ambil
            if perlu <= 0.01:
                break
        if perlu > 0.01:
            raise Gudang2Error(
                f"Stok curah {jenis} untuk pemilik ini tinggal "
                f"{berat_kg - perlu:,.2f} kg; tak cukup untuk "
                f"{berat_kg:,.2f} kg.".replace(",", "."))
    elif sumber_stok.startswith("curah:"):
        try:
            row_id = int(sumber_stok.partition(":")[2])
        except ValueError:
            raise Gudang2Error("Pilih stok curah tercatat yang valid.") from None
        row = await db.scalar(kunci_query(select(FinishedGoodsStock)
            .where(FinishedGoodsStock.id == row_id), kunci)
            .execution_options(populate_existing=True))
        sku = await db.get(ProductSku, row.product_sku_id) if row else None
        if (row is None or not row.curah_kemas_ulang or row.jumlah_karung != 0
                or row.jasa_id != jasa_id or sku is None or sku.kategori != kategori_sku
                or row.rice_quality_standard_id != (std.id if std else None)):
            raise Gudang2Error("Stok curah tidak cocok dengan jenis beras dan pemilik yang dipilih.")
        if berat_kg > float(row.berat_total_kg):
            raise Gudang2Error(
                f"Stok curah tercatat tinggal {float(row.berat_total_kg):,.2f} kg; "
                f"tak cukup untuk {berat_kg:,.2f} kg.".replace(",", "."))
        proc_id = row.source_id if row.source_type == "polishing" else None
        if row.source_type == "polishing" and proc_id is None:
            raise Gudang2Error("Asal proses stok curah tidak tercatat; perpindahan dibatalkan.")
        if proc_id is not None:
            alokasi[proc_id] = berat_kg
        baris_curah.append((row, berat_kg))
        rencana_pindah.append((proc_id, row.source_type, row.source_id,
                               row.product_sku_id, berat_kg))
    elif sumber_stok == "legacy":
        proc = await _proc_by_kode(db, kode_pol)
        if proc is None:
            raise Gudang2Error("Proses penyosohan yang dipilih tidak ditemukan.")
        hasil = (await output_sosoh(db, proc.id)).get(jenis, 0.0)
        dikemas = await _packed_kg(
            db, proc.id, kategori_sku, std.id if std else None)
        dipindah = (await _dipindah_silo_proc(db, [proc.id])).get(
            (proc.id, jenis), 0.0)
        curah = (max(0.0, float(hasil) - dikemas - dipindah)
                 if proc.jasa_id == jasa_id else 0.0)
        ambil_curah = min(berat_kg, curah)
        if ambil_curah > 0:
            rencana_pindah.append((proc.id, "polishing", proc.id, None, ambil_curah))
        perlu = berat_kg - ambil_curah
        ukuran_sku = (await db.execute(
            select(ProductSku.id, PackageSize.ukuran_kg)
            .join(FinishedGoodsStock,
                  FinishedGoodsStock.product_sku_id == ProductSku.id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .where(ProductSku.kategori == kategori_sku,
                   FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.source_id == proc.id,
                   FinishedGoodsStock.rice_quality_standard_id ==
                   (std.id if std else None),
                   FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None
                   else FinishedGoodsStock.jasa_id == jasa_id)
            .group_by(ProductSku.id, PackageSize.ukuran_kg)
            .order_by(PackageSize.ukuran_kg)
        )).all()
        for sku_id, ukuran_raw in ukuran_sku:
            if perlu <= 0.5:
                break
            ukuran = float(ukuran_raw)
            if ukuran <= 0:
                continue
            sisa, saldo = await sumber_karung_beras(db, sku_id, std.id if std else None,
                jasa_id, proses_id=proc.id, kunci=kunci)
            plan, _ = ambil_karung_nyata(sisa, min(perlu, float(saldo)))
            kg_karung = sum(kg for _, _, kg in plan)
            for row, jumlah, kg in plan:
                baris_karung.append((row, jumlah, kg))
                rencana_pindah.append((proc.id, "polishing", proc.id,row.product_sku_id,kg))
            perlu = max(0.0, perlu - kg_karung)
            dibongkar_kg += kg_karung
        if perlu > 0.5:
            raise Gudang2Error(
                f"{proc.kode_proses} {jenis} (curah + kemasan) tinggal "
                f"{curah + dibongkar_kg:,.0f} kg — tak bisa memasukkan "
                f"{berat_kg:,.0f} kg ke silo.".replace(",", "."))
        alokasi[proc.id] = berat_kg
    elif sumber_stok.startswith("sku:"):
        try:
            sku_id = int(sumber_stok.partition(":")[2])
        except ValueError:
            raise Gudang2Error("Pilih merek dan ukuran kemasan yang valid.") from None
        sku = await db.get(ProductSku, sku_id)
        if sku is None or sku.kategori != kategori_sku:
            raise Gudang2Error("Merek dan ukuran kemasan yang dipilih tidak dikenal.")
        ukuran = (await db.execute(
            select(PackageSize.ukuran_kg)
            .where(PackageSize.id == sku.package_size_id)
        )).scalar_one_or_none()
        if not ukuran or float(ukuran) <= 0:
            raise Gudang2Error("Ukuran kemasan beras tidak valid.")
        ukuran = float(ukuran)
        sumber, saldo = await sumber_karung_beras(db, sku_id, std.id if std else None,
            jasa_id, kunci=kunci)
        tersedia = sum(jumlah for _, jumlah, _ in sumber)
        if Decimal(str(berat_kg)) > saldo:
            raise Gudang2Error(
                f"Stok kemasan yang dipilih tinggal {tersedia} karung dengan berat nyata "
                f"{float(saldo):,.2f} kg; tak cukup untuk {berat_kg:,.2f} kg.".replace(',', '.'))
        plan, sisa_perlu = ambil_karung_nyata(sumber, berat_kg)
        if abs(sisa_perlu) > 0.000001:
            raise Gudang2Error(
                "Berat harus sesuai isi karung utuh berdasarkan berat nyata stok. "
                f"Ukuran {ukuran:g} kg adalah label nominal, bukan pengganti berat timbang.")
        for row, ambil, kg in plan:
            proc_id = row.source_id if row.source_type == "polishing" else None
            if row.source_type == "polishing" and proc_id is None:
                raise Gudang2Error(
                    "Asal proses untuk stok kemasan ini tidak tercatat; "
                    "stok tidak dipindahkan agar riwayat tetap utuh.")
            baris_karung.append((row, ambil, kg))
            rencana_pindah.append((proc_id, row.source_type, row.source_id,
                                   row.product_sku_id, kg))
            if proc_id is not None:
                alokasi[proc_id] = alokasi.get(proc_id, 0.0) + kg
        dibongkar_kg = sum(kg for _, _, kg in plan)
    else:
        raise Gudang2Error("Pilih curah atau merek dan ukuran kemasan yang tersedia.")

    if (not rencana_pindah
            or abs(sum(item[4] for item in rencana_pindah) - berat_kg) > 0.000001):
        raise Gudang2Error("Alokasi sumber stok tidak cocok dengan berat yang diminta.")

    return dict(alokasi=alokasi, baris_karung=baris_karung,
                baris_curah=baris_curah, rencana_pindah=rencana_pindah,
                dibongkar_kg=dibongkar_kg)
