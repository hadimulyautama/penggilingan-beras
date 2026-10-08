"""Gabah kering dikemas & ditimbang — jalan keluar keempat dari silo Gudang 1.

Pesan kerja 7 Oktober 2026, butir 6 (PESAN-KERJA-12 + 12A + 12B). Alur:

    silo A/B -> KELUARKAN + TIMBANG -> tumpukan -> ┬ dibongkar kembali ke silo
                                                    └ diambil/dijual (keluar)

⭐ GABAH TETAP BAHAN. Usul pertama (pesan 12 bagian 3) memakai
`finished_goods_stock` dengan kategori `gabah_kering` — DICABUT SELURUHNYA
(pesan 12A): gabah tak punya ukuran karung baku, dan tabel itu memaksa
anggapan itu (`ProductSku.package_size_id` wajib isi). Jalan keluarnya
meniru `pk_langsung` (PK dijual langsung dari Gudang 1): satu angka bobot,
tanpa SKU, tanpa jumlah karung wajib — lihat `GabahKeringLot`.

⚠⚠ YANG BELUM DIKERJAKAN DI SINI, DENGAN SENGAJA: gabah kering yang sudah
ditumpuk-ditimbang masuk PENGERING lagi (pesan 12B mengizinkannya). `
masuk_dryer` (`drying.py:435`) murni berbasis daftar KODE BATCH — ia
menganggap seluruh masukannya belum pernah ditimbang, mengecek
`kondisi_gabah`, dan menulis `b.status_batch = "di_dryer"` pada baris
`PurchaseBatch` sungguhan. Lot gabah kering BUKAN `PurchaseBatch`, dan
memaksakannya lewat batch palsu akan mencemari laporan pembelian (CHECK
`ck_purchase_batches_beli_atau_jasa` menuntut `supplier_id` atau `jasa_id`
asli — gabah pabrik yang re-dry tak punya salah satunya tanpa mengarang).
Mengerjakannya dengan benar berarti `DryingLot` butuh sumber bobot KEDUA di
luar `DryingLotBatch`, perubahan yang pantas jadi migrasinya sendiri —
bukan sudut dari fitur ini. Re-weigh (bagian 3 di bawah) tetap bekerja penuh
tanpa ini; yang belum ada cuma jalur "masuk pengering lagi"-nya.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time
from app.models import GabahKeringLot, OutgoingItem, OutgoingRecord, SiloStorage
from app.services.activity_log import log_activity
from app.services.codegen import next_gabah_kering_code
from app.services.jasa import kunci_silo


class GabahKeringError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


async def _dibongkar_kg(db: AsyncSession, lot_id: int) -> float:
    from app.models import GabahKeringBongkar
    return float((await db.execute(
        select(func.coalesce(func.sum(GabahKeringBongkar.berat_kg), 0))
        .where(GabahKeringBongkar.gabah_kering_lot_id == lot_id)
    )).scalar_one())


async def _keluar_kg(db: AsyncSession, lot_id: int) -> float:
    return float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.item_type == "gabah_langsung",
               OutgoingItem.gabah_kering_lot_id == lot_id)
    )).scalar_one())


async def saldo_gabah_kering(db: AsyncSession, lot_id: int) -> float:
    """Saldo lot gabah kering apa adanya — BOLEH NEGATIF.

    `berat_timbang_kg` − dibongkar kembali ke silo − keluar (dijual/diambil
    jasa). Sebangun `transfer.saldo_pk` — lihat catatan panjang di sana
    untuk alasan TIDAK dipotong di nol: pemotongan menyembunyikan selisih
    yang justru harus terlihat oleh yang menelusurinya.
    """
    lot = await db.get(GabahKeringLot, lot_id)
    if lot is None:
        return 0.0
    return (float(lot.berat_timbang_kg)
            - await _dibongkar_kg(db, lot_id)
            - await _keluar_kg(db, lot_id))


async def pending_gabah_kering_kg(db: AsyncSession, lot_id: int) -> float:
    """Saldo untuk TAMPILAN — dipotong di nol. Lihat `saldo_gabah_kering`."""
    return max(await saldo_gabah_kering(db, lot_id), 0.0)


@dataclass
class KeluarkanResult:
    lot: GabahKeringLot
    nama_silo: str
    sisa_silo_kg: float


async def keluarkan_untuk_kemasan(
    db: AsyncSession, *, user, silo_storage_id: int, berat_kg: float,
    jumlah_karung: int | None = None, tanggal=None, jam=None,
) -> KeluarkanResult:
    """Keluarkan gabah dari SATU baris silo, TIMBANG — jalan keluar BARU.

    `berat_kg` WAJIB diisi dari timbangan lantai, bukan `jumlah_karung ×
    ukuran` — gabah tak punya ukuran karung baku (pesan 12 bagian 4), dan
    `jumlah_karung` di sini murni keterangan untuk menyusun di gudang.

    Dua arah "silo berkurang sebagian": baris silo TIDAK ditutup (tetap
    `status="terisi"`, boleh dikemas lagi atau tetap digiling) — yang
    berkurang `dikemas_kg`-nya, dibaca `silo._row_bobot` sebagai suku
    pengurang. Sisa gabah di baris itu tetap bisa digiling seperti biasa.
    """
    from app.penggilingan.gudang1.services.silo import _row_bobot, silo_g1_by_id

    if not berat_kg or berat_kg <= 0:
        raise GabahKeringError("Sebutkan bobot timbangnya (kg), lebih dari 0.")
    row = (await db.execute(
        select(SiloStorage).where(SiloStorage.id == silo_storage_id)
        .with_for_update()
    )).scalars().first()
    if row is None or row.status != "terisi":
        raise GabahKeringError("Baris silo itu tidak ditemukan atau sudah kosong.")
    silo = await silo_g1_by_id(db, row.silo_id)
    nama_silo = silo.nama_silo.removeprefix("Silo ").strip() if silo else "?"

    # ── Pagar: tak boleh melebihi sisa, DAN pagar fisika "kering <= basah
    # masuk pengering" sekaligus — keduanya SATU pembanding yang sama di
    # sini, sebab `_row_bobot` baris ini (sebelum dikurangi oleh
    # pengeluaran kali ini) adalah persis bobot yang tercatat masuk pabrik
    # (basah untuk yang dikeringkan sendiri, sudah-kering-saat-beli untuk
    # yang langsung). Dikecualikan bila bobot pembandingnya belum PASTI —
    # pembanding yang belum pasti akan menolak angka yang benar (pola yang
    # sama dengan pagar rendemen, temuan P6-03a).
    sisa = await _row_bobot(db, row)
    if sisa.pasti and sisa.kg is not None and berat_kg > sisa.kg + 0.5:
        raise GabahKeringError(
            f"Silo {nama_silo} tinggal {sisa.angka():,.0f} kg yang bisa "
            f"dikemas — tak bisa mengeluarkan {berat_kg:,.0f} kg."
            .replace(",", "."))

    # Silonya DIKUNCI — penjaga lain (pemilik, kunci) sudah berdiri sejak
    # baris ini dibuat; di sini cuma menjaga DUA pengeluaran yang datang
    # bersamaan dari baris yang sama tidak sama-sama lolos atas sisa yang
    # sama.
    await kunci_silo(db, row.silo_id)

    now = input_time(tanggal, jam)
    lot = GabahKeringLot(
        kode_lot=await next_gabah_kering_code(db),
        silo_storage_id=row.id, jasa_id=row.jasa_id,
        berat_timbang_kg=berat_kg, jumlah_karung=jumlah_karung,
        tanggal=now.date(), waktu_timbang=now, input_by=user.id,
    )
    db.add(lot)
    # Dinaikkan di Python, BUKAN bug P-K-14: baris silo ini sudah dikunci
    # `FOR UPDATE` tepat di atas, jadi tak ada penekan kedua yang bisa
    # membaca nilai lama sebelum yang pertama commit — beda dari
    # `MillingProcess.berat_gabah_masuk_kg` di `masuk_silo`, yang baris
    # SILO-nya terkunci tetapi PROSES gilingnya tidak.
    row.dikemas_kg = float(row.dikemas_kg or 0) + float(berat_kg)
    await db.flush()

    await log_activity(
        db, table_name="gabah_kering_lots", record_id=lot.id, action="INSERT",
        aksi="gabah_kering_keluar", changed_by=user.id,
        new_value=f"{lot.kode_lot} <- Silo {nama_silo} ({berat_kg:,.0f} kg)"
                  .replace(",", "."),
    )
    await db.commit()
    await db.refresh(lot)
    sisa_sesudah = await _row_bobot(db, row)
    return KeluarkanResult(lot=lot, nama_silo=nama_silo,
                           sisa_silo_kg=sisa_sesudah.angka())


async def timbang_ulang(
    db: AsyncSession, *, user, kode_lot: str, berat_kg: float, tanggal=None, jam=None,
) -> GabahKeringLot:
    """Timbang ULANG satu lot (sesudah dikeringkan lagi, pesan 12B) — bobot
    LAMA DIGANTI, bukan dijumlah.

    ⚠⚠ HANYA bila lot ini MASIH UTUH (belum ada yang dibongkar maupun
    keluar). Sesudah sebagian keluar, "satu angka global" tak lagi cukup
    membedakan "sisa yang ditimbang ulang" dari "total yang pernah ada" —
    pemilik hanya menyebut skenario re-dry SEBELUM ada yang terangkut, dan
    memaksakan rumus lama untuk keadaan yang belum terjawab akan menebak,
    bukan menghitung.
    """
    lot = (await db.execute(
        select(GabahKeringLot).where(GabahKeringLot.kode_lot == kode_lot)
        .with_for_update()
    )).scalars().first()
    if lot is None:
        raise GabahKeringError(f"Gabah kering {kode_lot} tidak ditemukan.")
    if not berat_kg or berat_kg <= 0:
        raise GabahKeringError("Sebutkan bobot timbangnya (kg), lebih dari 0.")
    saldo = await saldo_gabah_kering(db, lot.id)
    if abs(saldo - float(lot.berat_timbang_kg)) > 0.5:
        raise GabahKeringError(
            f"{kode_lot} sudah sebagian dibongkar/diambil — penimbangan "
            "ulang hanya untuk lot yang masih utuh."
        )
    # ── Pagar fisika: mengeringkan hanya membuang air ──
    lama = float(lot.berat_timbang_kg)
    if berat_kg > lama + 0.5:
        raise GabahKeringError(
            f"Penimbangan baru ({berat_kg:,.0f} kg) tak boleh melebihi yang "
            f"sebelumnya ({lama:,.0f} kg) — mengeringkan hanya membuang air, "
            "tak pernah menambah bobot.".replace(",", "."))
    lot.berat_timbang_kg = berat_kg
    lot.waktu_timbang = input_time(tanggal, jam)
    await log_activity(
        db, table_name="gabah_kering_lots", record_id=lot.id, action="UPDATE",
        aksi="gabah_kering_timbang_ulang", changed_by=user.id,
        field_name="berat_timbang_kg", old_value=f"{lama:.0f}",
        new_value=f"{float(berat_kg):.0f}",
    )
    await db.commit()
    await db.refresh(lot)
    return lot
