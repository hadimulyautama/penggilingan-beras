"""Logika bisnis pengeringan gabah (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import input_time, now_local
from app.models import (
    Dryer,
    DryingCoolingLog,
    DryingLot,
    DryingLotBatch,
    DryingMoistureLog,
    Notification,
    PurchaseBatch,
    SiloStorage,
    Supplier,
    Warehouse,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_drying_lot_code


class DryingError(Exception):
    """Kesalahan proses pengeringan dengan pesan siap-tampil (args[0])."""


async def get_lot_by_kode(db: AsyncSession, kode: str) -> DryingLot | None:
    stmt = select(DryingLot).where(DryingLot.kode_lot == kode)
    return (await db.execute(stmt)).scalars().first()


async def sole_active_lot_kode(db: AsyncSession) -> str | None:
    """Kode lot bila TEPAT ADA SATU lot yang sedang 'proses'; selain itu None.

    Memungkinkan 'kadar air 26%' tanpa menyebut kode saat cuma 1 lot berjalan.
    """
    rows = (
        await db.execute(select(DryingLot.kode_lot).where(DryingLot.status == "proses"))
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def sole_cooling_lot_kode(db: AsyncSession) -> str | None:
    """Kode lot bila TEPAT ADA SATU lot yang sedang didinginkan (selesai, di dryer)."""
    belum_ke_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
    rows = (
        await db.execute(
            select(DryingLot.kode_lot).where(
                DryingLot.status == "selesai", belum_ke_silo
            )
        )
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def resolve_batch_kodes(
    db: AsyncSession,
    *,
    kode_list: list[str] | None,
    urutan_list: list[int] | None,
    semua: bool = False,
) -> list[str]:
    """Kembalikan daftar kode batch. Bila hanya urutan diberikan, petakan ke

    batch pembelian HARI INI berdasarkan nomor urut (pertama->01, ketiga->03).
    Bila `semua`=True, ambil SEMUA batch hari ini yang belum masuk lot.
    """
    if kode_list:
        return kode_list
    today = now_local().date()
    if semua:
        sudah_dilot = select(DryingLotBatch.purchase_batch_id)
        stmt = (
            select(PurchaseBatch.kode_batch)
            .where(
                PurchaseBatch.tanggal_pembelian == today,
                PurchaseBatch.id.not_in(sudah_dilot),
            )
            .order_by(PurchaseBatch.kode_batch)
        )
        kodes = list((await db.execute(stmt)).scalars().all())
        if not kodes:
            raise DryingError(
                "Tidak ada batch gabah hari ini yang belum masuk pengeringan."
            )
        return kodes
    if not urutan_list:
        return []
    stmt = (
        select(PurchaseBatch.kode_batch)
        .where(PurchaseBatch.tanggal_pembelian == today)
        .order_by(PurchaseBatch.kode_batch)
    )
    today_kodes = list((await db.execute(stmt)).scalars().all())
    hasil: list[str] = []
    kurang: list[int] = []
    for n in urutan_list:
        if 1 <= n <= len(today_kodes):
            hasil.append(today_kodes[n - 1])
        else:
            kurang.append(n)
    if kurang:
        urut = ", ".join(f"ke-{n}" for n in kurang)
        raise DryingError(
            f"Batch {urut} hari ini belum ada (baru {len(today_kodes)} batch "
            "masuk hari ini). Sebutkan kode GB-... langsung bila perlu."
        )
    return hasil


async def _close_late_notifs(db: AsyncSession, lot_id: int) -> None:
    await db.execute(
        update(Notification)
        .where(
            Notification.tipe == "pengeringan_telat",
            Notification.record_id == lot_id,
            Notification.status == "baru",
        )
        .values(status="selesai")
    )


def _hours(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 3600.0


async def dryers_g1(db: AsyncSession) -> list[Dryer]:
    """Semua mesin pengering Gudang 1, yang aktif lebih dulu."""
    return list((await db.execute(
        select(Dryer)
        .join(Warehouse, Dryer.warehouse_id == Warehouse.id)
        .where(Warehouse.nama_gudang.like("Gudang 1%"))
        .order_by(Dryer.status.desc(), Dryer.id)
    )).scalars().all())


async def pilih_dryer(db: AsyncSession, dryer_id: int | None) -> Dryer:
    """Mesin yang dimaksud — atau satu-satunya, bila memang hanya satu.

    Tiap dryer berjalan sendiri-sendiri (Direksi, 3 September 2026), jadi
    setiap tindakan harus menyebut mesinnya. Kecuali saat memang cuma ada
    satu: menyuruh orang memilih dari daftar berisi satu pilihan bukan
    ketelitian, melainkan pekerjaan tambahan tanpa isi.
    """
    mesin = await dryers_g1(db)
    if not mesin:
        raise DryingError("Belum ada mesin pengering terdaftar di Gudang 1.")
    if dryer_id is None:
        if len(mesin) == 1:
            return mesin[0]
        nama = ", ".join(d.nama for d in mesin)
        raise DryingError(f"Sebutkan mesin pengeringnya: {nama}.")
    for d in mesin:
        if d.id == dryer_id:
            return d
    raise DryingError("Mesin pengering itu tidak ada di Gudang 1.")


async def _g1_dryer(db: AsyncSession) -> Dryer | None:
    """Mesin pengering Gudang 1 (unit pertama, aktif diutamakan).

    Dipertahankan untuk pemanggil lama yang memang tak peduli mesin mana —
    laporan ringkas, misalnya. Yang menempatkan gabah TIDAK boleh memakainya.
    """
    stmt = (
        select(Dryer)
        .join(Warehouse, Dryer.warehouse_id == Warehouse.id)
        .where(Warehouse.nama_gudang.like("Gudang 1%"))
        .order_by(Dryer.status.desc(), Dryer.id)  # 'aktif' > lainnya secara alfabet
    )
    return (await db.execute(stmt)).scalars().first()


# Gabah masih di dalam dryer: sedang dikeringkan ATAU sedang didinginkan
# (drying selesai tapi belum dipindah ke silo). Silo = keluar dari dryer.
def _in_dryer_where():
    belum_ke_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
    # Lot dalam dryer: proses (dikeringkan) atau selesai (didinginkan, belum silo).
    return (DryingLot.status.in_(["proses", "selesai"]), belum_ke_silo)


async def dryer_load_kg(db: AsyncSession) -> float:
    """Total kg gabah di dalam dryer = batch menunggu (loose) + lot aktif."""
    lot_kg = (
        await db.execute(
            select(func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0))
            .select_from(DryingLot)
            .join(DryingLotBatch, DryingLotBatch.drying_lot_id == DryingLot.id)
            .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
            .where(*_in_dryer_where())
        )
    ).scalar_one()
    return float(lot_kg) + await loose_dryer_kg(db)


async def _ensure_cooling_started(db, lot, now, user) -> bool:
    """Tandai fase pendinginan MULAI (idempoten). True bila baru dimulai.

    Dipanggil otomatis saat pengeringan selesai — operator tak perlu input
    'mulai pendinginan' terpisah. Tambah 1 log pendinginan otomatis bila belum
    ada log sama sekali."""
    if lot.waktu_mulai_pendinginan is not None:
        return False
    lot.waktu_mulai_pendinginan = now
    cnt = (
        await db.execute(
            select(func.count()).select_from(DryingCoolingLog)
            .where(DryingCoolingLog.drying_lot_id == lot.id)
        )
    ).scalar_one()
    if cnt == 0:
        db.add(DryingCoolingLog(
            drying_lot_id=lot.id, waktu=now,
            catatan="otomatis: mulai pendinginan (pengeringan selesai)",
            input_by=user.id,
        ))
    return True


async def log_cooling(
    db: AsyncSession, *, user, kode_lot: str | None, catatan: str | None, tanggal=None, jam=None
) -> tuple[DryingLot, int, bool]:
    """Catat log pendinginan (gabah tetap di dryer). Kembalikan (lot, jumlah, first).

    OTOMATIS: bila pengeringan belum ditandai selesai, tandai selesai dulu
    (input 'pengeringan selesai' & 'mulai pendinginan' sering bersamaan/terlupa —
    salah satu memicu keduanya)."""
    if not kode_lot:
        raise DryingError("Sebutkan kode lot, contoh: `pendinginan LOT-20260702-01`")
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status == "di_dryer":
        raise DryingError(
            f"Lot {kode_lot} belum mulai dikeringkan. Ketik `mulai pengeringan {kode_lot}` dulu."
        )

    now = input_time(tanggal, jam)
    if lot.status != "selesai":
        lot.status = "selesai"
        if lot.waktu_selesai_pengeringan is None:
            lot.waktu_selesai_pengeringan = now
        await _close_late_notifs(db, lot.id)
        await log_activity(
            db, table_name="drying_lots", record_id=lot.id, action="UPDATE",
            changed_by=user.id, field_name="status",
            new_value="selesai (otomatis dari pendinginan)",
        )
    if lot.waktu_mulai_pendinginan is None:
        lot.waktu_mulai_pendinginan = now

    prev = (
        await db.execute(
            select(func.count())
            .select_from(DryingCoolingLog)
            .where(DryingCoolingLog.drying_lot_id == lot.id)
        )
    ).scalar_one()
    db.add(
        DryingCoolingLog(
            drying_lot_id=lot.id, waktu=now, catatan=catatan, input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="drying_cooling_logs", record_id=lot.id, action="INSERT",
        changed_by=user.id, new_value=catatan or "pendinginan",
    )
    await db.commit()
    return lot, prev + 1, prev == 0


async def finish_cooling(
    db: AsyncSession, *, user, kode_lot: str | None, tanggal=None, jam=None
) -> tuple[DryingLot, float]:
    """Nyatakan pendinginan SELESAI. Ini keputusan OPERATOR — bukan efek samping
    pemindahan ke silo. Gabah boleh TETAP di dryer setelah dingin (mis. kedua
    silo belum kosong); dryer sudah idle sejak titik ini. Waktu inilah basis
    analisa downtime dryer. Kembalikan (lot, durasi_pendinginan_jam)."""
    if not kode_lot:
        raise DryingError("Sebutkan kode lot, contoh: `pendinginan selesai LOT-20260702-01`")
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status == "di_dryer":
        raise DryingError(
            f"Lot {kode_lot} belum mulai dikeringkan. Ketik `mulai pengeringan {kode_lot}` dulu."
        )
    # Pendinginan boleh dinyatakan selesai BERKALI-KALI — keputusan Direksi
    # 2 September 2026. Gabah yang sudah dinyatakan dingin bisa ternyata masih
    # panas, atau perlu didinginkan lagi setelah dicek; menolak pernyataan
    # kedua memaksa operator berbohong pada catatan atau membiarkannya salah.
    #
    # Yang tersimpan di lot adalah pernyataan TERAKHIR, karena itulah saat
    # dryer benar-benar menganggur — dan itu dasar analisa downtime. Riwayat
    # tiap putaran tetap utuh di `drying_cooling_logs`, satu baris per
    # pernyataan, jadi tidak ada yang hilang.
    ulang = lot.waktu_selesai_pendinginan is not None

    now = input_time(tanggal, jam)
    # Pastikan pengeringan selesai & pendinginan sudah mulai (idempoten).
    if lot.status != "selesai":
        lot.status = "selesai"
        if lot.waktu_selesai_pengeringan is None:
            lot.waktu_selesai_pengeringan = now
        await _close_late_notifs(db, lot.id)
    await _ensure_cooling_started(db, lot, lot.waktu_selesai_pengeringan or now, user)
    if lot.waktu_mulai_pendinginan and now < lot.waktu_mulai_pendinginan:
        raise DryingError(
            f"Waktu selesai pendinginan lebih awal dari mulai pendinginan "
            f"({lot.waktu_mulai_pendinginan:%d-%m-%Y %H:%M})."
        )
    lot.waktu_selesai_pendinginan = now
    db.add(DryingCoolingLog(
        drying_lot_id=lot.id, waktu=now, input_by=user.id,
        catatan="pendinginan selesai (diulang)" if ulang else "pendinginan selesai",
    ))
    await log_activity(
        db, table_name="drying_lots", record_id=lot.id, action="UPDATE",
        changed_by=user.id, field_name="waktu_selesai_pendinginan",
        new_value="pendinginan selesai",
    )
    await db.commit()
    await db.refresh(lot)
    return lot, _hours(now, lot.waktu_mulai_pendinginan or now)


# ─────────────────────────── Bentuk lot ───────────────────────────
@dataclass
class LotResult:
    lot: DryingLot | None  # None untuk masuk_dryer (lot belum dibentuk)
    kondisi: str
    total_kg: float
    batch_kodes: list[str] = field(default_factory=list)
    #: Nama mesin yang dipakai — supaya pesan di layar menyebut mesin mana,
    #: bukan "dryer" yang tak lagi tunggal.
    nama_dryer: str | None = None
    #: Peringatan yang HARUS sampai ke layar, tetapi TIDAK menggagalkan aksi.
    #: Ada keadaan yang bukan salah dan bukan benar — hanya tidak ideal, dan
    #: orang yang menjalankannya perlu tahu bahwa ia sedang menyimpang.
    peringatan: str | None = None


async def _loose_dryer_batches(
    db: AsyncSession, dryer_id: int | None = None
) -> list[PurchaseBatch]:
    """Batch yang MENUNGGU di dryer (status 'di_dryer', belum jadi lot).

    Disaring per mesin bila disebutkan. Tanpa saringan itu, "mulai
    pengeringan" akan menyapu gabah dari SEMUA mesin ke dalam satu lot —
    gabah yang tidak pernah bertemu di mesin yang sama.
    """
    in_lot = select(DryingLotBatch.purchase_batch_id)
    q = (select(PurchaseBatch)
         .where(PurchaseBatch.status_batch == "di_dryer",
                PurchaseBatch.id.not_in(in_lot)))
    if dryer_id is not None:
        q = q.where(PurchaseBatch.dryer_id == dryer_id)
    return list((await db.execute(q.order_by(PurchaseBatch.id))).scalars().all())


async def loose_dryer_kg(db: AsyncSession, dryer_id: int | None = None) -> float:
    return sum(float(b.berat_total_kg or 0)
               for b in await _loose_dryer_batches(db, dryer_id))


async def masuk_dryer(
    db: AsyncSession, *, user, kode_batch_list: list[str] | None,
    dryer_id: int | None = None,
) -> LotResult:
    """Masukkan batch ke dryer — MENUNGGU (belum jadi lot). Lot baru dibentuk
    saat 'mulai pengeringan' dari SEMUA batch di dryer.

    Validasi: tak campur basah/kering, kapasitas dryer, dryer tak sedang dipakai
    lot yang mengering/didinginkan. Tanpa batas jumlah batch (ikut kapasitas)."""
    kodes = list(dict.fromkeys(kode_batch_list or []))
    if not kodes:
        raise DryingError(
            "Sebutkan kode batch, contoh: `keringkan GB-20260702-01 dan GB-...`"
        )
    batches: list[PurchaseBatch] = []
    missing: list[str] = []
    for kode in kodes:
        b = (
            await db.execute(select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode))
        ).scalars().first()
        (batches if b else missing).append(b if b else kode)  # type: ignore[arg-type]
    if missing:
        raise DryingError("Batch tidak ditemukan: " + ", ".join(missing))

    dryer = await pilih_dryer(db, dryer_id)
    occupied = await active_drying_lot(db, dryer.id)
    if occupied is not None:
        raise DryingError(
            f"{dryer.nama} masih dipakai lot {occupied.kode_lot} — "
            "kosongkan ke silo dulu."
        )
    for b in batches:
        if b.status_batch == "di_dryer":
            raise DryingError(f"{b.kode_batch} sudah di dryer.")
        if b.status_batch in ("di_silo", "dikeringkan", "digiling"):
            raise DryingError(f"{b.kode_batch} sudah diproses ({b.status_batch}).")

    loose = await _loose_dryer_batches(db, dryer.id)
    kondisi_all = {b.kondisi_gabah for b in batches} | {b.kondisi_gabah for b in loose}
    if len(kondisi_all) > 1:
        raise DryingError(
            f"❌ Tidak boleh mencampur gabah basah & kering di {dryer.nama}."
        )

    new_total = sum(float(b.berat_total_kg or 0) for b in batches)
    if dryer is not None:
        if dryer.status != "aktif":
            raise DryingError(f"{dryer.nama} sedang {dryer.status}.")
        load = await loose_dryer_kg(db, dryer.id)
        cap_efektif = float(dryer.kapasitas_kg) + settings.dryer_toleransi_kg
        if load + new_total > cap_efektif:
            sisa = max(cap_efektif - load, 0)
            raise DryingError(
                f"❌ Kapasitas dryer tak cukup (sisa {sisa / 1000:g} ton, "
                f"batch ini {new_total / 1000:g} ton)."
            )

    for b in batches:
        b.status_batch = "di_dryer"
        b.dryer_id = dryer.id
    await log_activity(
        db, table_name="purchase_batches", record_id=batches[0].id, action="UPDATE",
        changed_by=user.id, field_name="status_batch",
        new_value="masuk dryer: " + ", ".join(b.kode_batch for b in batches),
    )
    await db.commit()
    return LotResult(
        lot=None, kondisi=kondisi_all.pop() if kondisi_all else batches[0].kondisi_gabah,
        total_kg=await loose_dryer_kg(db, dryer.id),
        nama_dryer=dryer.nama,
        batch_kodes=[b.kode_batch for b in batches],
    )


async def active_drying_lot(
    db: AsyncSession, dryer_id: int | None = None
) -> DryingLot | None:
    """Lot yang MENGISI sebuah dryer (belum ke silo).

    Sedang dikeringkan ('proses') atau didinginkan ('selesai' belum ke silo).
    Selagi ada, mesin ITU dianggap dipakai — gabah baru tak boleh masuk ke
    sana. Lot = 1 proses pengeringan.

    `dryer_id=None` berarti "mesin mana pun", dan itu dipakai laporan ringkas
    — bukan oleh yang menempatkan gabah. Sejak tiap dryer berjalan
    sendiri-sendiri, menanyakan "apakah dryer terpakai" tanpa menyebut
    mesinnya akan menutup seluruh pabrik gara-gara satu mesin sibuk.
    """
    belum_ke_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
    q = (select(DryingLot)
         .where(DryingLot.status.in_(["proses", "selesai"]), belum_ke_silo))
    if dryer_id is not None:
        q = q.where(DryingLot.dryer_id == dryer_id)
    return (await db.execute(q.order_by(DryingLot.id.desc()))).scalars().first()


async def _lot_batches(db: AsyncSession, lot_id: int) -> list[PurchaseBatch]:
    return list(
        (
            await db.execute(
                select(PurchaseBatch)
                .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == lot_id)
            )
        ).scalars().all()
    )


async def add_batches_to_lot(
    db: AsyncSession, *, user, kode_lot: str, kode_batch_list: list[str] | None
) -> LotResult:
    """Gabungkan batch tambahan ke lot pengeringan yang masih 'proses' di dryer."""
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status not in ("di_dryer", "proses"):
        raise DryingError(f"Lot {kode_lot} sudah selesai — tidak bisa menambah batch.")

    kodes = list(dict.fromkeys(kode_batch_list or []))
    if not kodes:
        raise DryingError("Sebutkan batch yang mau digabungkan ke lot.")

    existing = await _lot_batches(db, lot.id)
    existing_kondisi = existing[0].kondisi_gabah if existing else None

    batches: list[PurchaseBatch] = []
    missing: list[str] = []
    for kode in kodes:
        b = (
            await db.execute(select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode))
        ).scalars().first()
        (batches if b else missing).append(b if b else kode)  # type: ignore[arg-type]
    if missing:
        raise DryingError("Batch tidak ditemukan: " + ", ".join(missing))

    ids = [b.id for b in batches]
    used = (
        await db.execute(
            select(DryingLotBatch.purchase_batch_id).where(
                DryingLotBatch.purchase_batch_id.in_(ids)
            )
        )
    ).scalars().all()
    if used:
        dup = [b.kode_batch for b in batches if b.id in set(used)]
        raise DryingError("Sudah masuk lot: " + ", ".join(dup))

    if len(existing) + len(batches) > 3:
        raise DryingError(
            f"Maksimal 3 batch per lot. {kode_lot} sudah {len(existing)} batch."
        )

    kondisi_baru = {b.kondisi_gabah for b in batches}
    if len(kondisi_baru) > 1 or (existing_kondisi and kondisi_baru != {existing_kondisi}):
        raise DryingError(
            "❌ Tidak boleh mencampur gabah basah dan kering dalam satu lot."
        )
    kondisi = existing_kondisi or kondisi_baru.pop()

    new_total = sum(float(b.berat_total_kg or 0) for b in batches)
    dryer = await _g1_dryer(db)
    if dryer is not None:
        load = await dryer_load_kg(db)  # sudah termasuk lot ini
        cap = float(dryer.kapasitas_kg)
        cap_efektif = cap + settings.dryer_toleransi_kg
        if load + new_total > cap_efektif:
            sisa = max(cap_efektif - load, 0)
            raise DryingError(
                f"❌ Kapasitas mesin pengering {cap / 1000:g} ton "
                f"(maks dgn toleransi {cap_efektif / 1000:g} ton) tidak cukup "
                f"(sisa {sisa / 1000:g} ton, tambahan {new_total / 1000:g} ton)."
            )

    for b in batches:
        db.add(DryingLotBatch(drying_lot_id=lot.id, purchase_batch_id=b.id))
        b.status_batch = "dikeringkan"
        # Mesinnya kini tersimpan di lot; dua tempat yang menyebut hal sama
        # cepat atau lambat berbeda.
        b.dryer_id = None
    await log_activity(
        db, table_name="drying_lots", record_id=lot.id, action="UPDATE",
        changed_by=user.id,
        new_value=f"{kode_lot} +{len(batches)} batch ({new_total:.0f}kg)",
    )
    await db.commit()

    all_batches = existing + batches
    total_kg = sum(float(b.berat_total_kg or 0) for b in all_batches)
    return LotResult(
        lot=lot, kondisi=kondisi, total_kg=total_kg,
        batch_kodes=[b.kode_batch for b in all_batches],
    )


# ─────────────────────────── Log kadar air ───────────────────────────
@dataclass
class MoistureResult:
    lot: DryingLot
    jam_sejak_mulai: float
    jam_sejak_log_sebelumnya: float | None
    #: Rata-rata sampel alat tes, dan sebarannya (terendah–tertinggi).
    rata_tes: float | None = None
    sebar: float | None = None
    indikator: float | None = None
    #: Selisih bacaan mesin terhadap rata-rata alat tes. Dryer yang sensornya
    #: melenceng akan menunjukkan selisih yang konsisten dari hari ke hari —
    #: dan itu hanya terlihat kalau keduanya dicatat berdampingan.
    selisih_mesin: float | None = None


async def log_moisture(
    db: AsyncSession,
    *,
    user,
    kode_lot: str | None,
    indikator: float | None = None,
    tes_manual: float | None = None,
    sampel: list[float | None] | None = None,
    tanggal=None, jam=None,
) -> MoistureResult:
    """Catat kadar air satu lot.

    `sampel` adalah empat titik dengan alat tes kadar air; yang dipakai
    sebagai angka tes adalah RATA-RATANYA. Satu titik saja bisa kebetulan
    mengenai bagian yang paling basah atau paling kering, dan keputusan
    menghentikan pengeringan tidak boleh bergantung pada satu tusukan.

    `indikator` adalah angka yang terbaca pada mesin dryer sendiri. Ia TIDAK
    dirata-ratakan bersama alat tes: keduanya mengukur hal yang sama dengan
    alat berbeda, dan mencampurnya menghapus justru perbandingan yang berguna
    — mesin yang sensornya melenceng terlihat dari selisih yang tetap.
    """

    if not kode_lot:
        raise DryingError("Sebutkan kode lot-nya, contoh: `kadar air LOT-20260702-01 18%`")
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status == "selesai":
        raise DryingError(f"Lot {kode_lot} sudah selesai — tidak bisa menambah log.")
    isi = [x for x in (sampel or []) if x is not None]
    if isi and tes_manual is None:
        tes_manual = sum(isi) / len(isi)
    if indikator is None and tes_manual is None:
        raise DryingError(
            "Sebutkan angka kadar airnya — minimal satu sampel alat tes, "
            "atau angka yang terbaca di mesin."
        )

    # Log sebelumnya (untuk hitung jeda).
    prev = (
        await db.execute(
            select(DryingMoistureLog.waktu_update)
            .where(DryingMoistureLog.drying_lot_id == lot.id)
            .order_by(DryingMoistureLog.waktu_update.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    now = input_time(tanggal, jam)
    db.add(
        DryingMoistureLog(
            drying_lot_id=lot.id,
            waktu_update=now,
            kadar_air_indikator=indikator,
            kadar_air_tes_manual=tes_manual,
            kadar_air_tes_1=(sampel or [None] * 4)[0] if sampel else None,
            kadar_air_tes_2=(sampel or [None] * 4)[1] if sampel and len(sampel) > 1 else None,
            kadar_air_tes_3=(sampel or [None] * 4)[2] if sampel and len(sampel) > 2 else None,
            kadar_air_tes_4=(sampel or [None] * 4)[3] if sampel and len(sampel) > 3 else None,
            input_by=user.id,
        )
    )
    await log_activity(
        db,
        table_name="drying_moisture_logs",
        record_id=lot.id,
        action="INSERT",
        changed_by=user.id,
        new_value=(f"indikator={indikator} tes_manual={tes_manual} "
                   f"sampel={[float(x) for x in isi] if isi else '-'}"),
    )
    await _close_late_notifs(db, lot.id)
    await db.commit()
    return MoistureResult(
        lot=lot,
        jam_sejak_mulai=_hours(now, lot.waktu_mulai_pengeringan),
        jam_sejak_log_sebelumnya=_hours(now, prev) if prev else None,
        rata_tes=tes_manual,
        sebar=(max(isi) - min(isi)) if len(isi) > 1 else None,
        indikator=indikator,
        selisih_mesin=((indikator - tes_manual)
                       if indikator is not None and tes_manual is not None else None),
    )


# ─────────────────────────── Selesai ───────────────────────────
async def start_drying(
    db: AsyncSession, *, user, dryer_id: int | None = None, tanggal=None, jam=None
) -> LotResult:
    """MULAI pengeringan: bentuk 1 LOT dari SEMUA batch yang menunggu di dryer,
    lalu status 'proses'. Lot lahir di sini (bukan saat masuk dryer).

    Masuk dryer ≠ mulai pengeringan — ini input terpisah (operator G1 utama)."""
    dryer = await pilih_dryer(db, dryer_id)
    loose = await _loose_dryer_batches(db, dryer.id)
    if not loose:
        raise DryingError(
            f"Tidak ada gabah di {dryer.nama}. Masukkan dulu, "
            "mis. `keringkan GB-...`."
        )
    kondisi_set = {b.kondisi_gabah for b in loose}
    if len(kondisi_set) > 1:
        raise DryingError("❌ Ada campuran basah & kering di dryer — pisahkan dulu.")
    kondisi = kondisi_set.pop()
    now = input_time(tanggal, jam)
    lot = DryingLot(
        kode_lot=await next_drying_lot_code(db),
        dryer_id=dryer.id,
        waktu_mulai_pengeringan=now, status="proses", created_by=user.id,
    )
    db.add(lot)
    await db.flush()
    total = 0.0
    for b in loose:
        db.add(DryingLotBatch(drying_lot_id=lot.id, purchase_batch_id=b.id))
        b.status_batch = "dikeringkan"
        # Mesinnya kini tersimpan di lot; dua tempat yang menyebut hal sama
        # cepat atau lambat berbeda.
        b.dryer_id = None
        total += float(b.berat_total_kg or 0)
    await log_activity(
        db, table_name="drying_lots", record_id=lot.id, action="INSERT",
        changed_by=user.id,
        new_value=f"mulai pengeringan {lot.kode_lot} ({len(loose)} batch, {total:.0f}kg)",
    )
    await db.commit()
    await db.refresh(lot)

    # Satu batch saja BOLEH dikeringkan — tetapi tidak ideal, dan orang yang
    # menjalankannya perlu tahu. Dryer 30 ton yang dinyalakan untuk satu muatan
    # kecil membakar bahan bakar yang sama dengan yang penuh, dan biayanya
    # dibagi ke gabah yang lebih sedikit. Peringatan, bukan penolakan: kadang
    # memang tak ada muatan kedua yang menunggu, dan menahan gabah demi
    # menunggu teman justru membuatnya menginap.
    peringatan = None
    if len(loose) < 2:
        peringatan = (
            f"⚠️ Hanya 1 batch ({total:.0f} kg) — pengeringan sebaiknya "
            "menggabungkan minimal 2 batch. Tetap dijalankan."
        )
    return LotResult(lot=lot, kondisi=kondisi, total_kg=total,
                     batch_kodes=[b.kode_batch for b in loose],
                     nama_dryer=dryer.nama, peringatan=peringatan)


async def finish_drying(
    db: AsyncSession, *, user, kode_lot: str | None, tanggal=None, jam=None
) -> tuple[DryingLot, float]:
    if not kode_lot:
        raise DryingError("Sebutkan kode lot yang selesai, contoh: `LOT-20260702-01 selesai`")
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status == "di_dryer":
        raise DryingError(
            f"Lot {kode_lot} belum mulai dikeringkan. Ketik `mulai pengeringan {kode_lot}` dulu."
        )

    now = input_time(tanggal, jam)
    if lot.status != "selesai":
        if lot.waktu_mulai_pengeringan and now < lot.waktu_mulai_pengeringan:
            raise DryingError(
                f"Tanggal selesai lebih awal dari mulai pengeringan "
                f"({lot.waktu_mulai_pengeringan:%d-%m-%Y %H:%M})."
            )
        lot.status = "selesai"
        lot.waktu_selesai_pengeringan = now
        await _close_late_notifs(db, lot.id)
        await log_activity(
            db, table_name="drying_lots", record_id=lot.id, action="UPDATE",
            changed_by=user.id, field_name="status", new_value="selesai",
        )
    # OTOMATIS masuk fase pendinginan (idempoten — aman bila sudah dimulai).
    await _ensure_cooling_started(db, lot, now, user)
    await db.commit()
    await db.refresh(lot)
    mulai = lot.waktu_mulai_pengeringan or now
    return lot, _hours(lot.waktu_selesai_pengeringan or now, mulai)


# ─────────────────────────── Laporan ───────────────────────────
async def _latest_log(db: AsyncSession, lot_id: int) -> DryingMoistureLog | None:
    return (
        await db.execute(
            select(DryingMoistureLog)
            .where(DryingMoistureLog.drying_lot_id == lot_id)
            .order_by(DryingMoistureLog.waktu_update.desc())
            .limit(1)
        )
    ).scalars().first()


async def _batch_count(db: AsyncSession, lot_id: int) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(DryingLotBatch)
            .where(DryingLotBatch.drying_lot_id == lot_id)
        )
    ).scalar_one()


def _fmt_ka(log: DryingMoistureLog | None) -> str:
    if log is None:
        return "belum ada log kadar air"
    parts = []
    if log.kadar_air_indikator is not None:
        parts.append(f"indikator {log.kadar_air_indikator:g}%")
    if log.kadar_air_tes_manual is not None:
        parts.append(f"manual {log.kadar_air_tes_manual:g}%")
    return " / ".join(parts) if parts else "-"


async def _lot_suppliers(db: AsyncSession, lot_id: int) -> list[str]:
    """Nama supplier asal bahan sebuah lot pengeringan (lewat batch gabungan)."""
    rows = (
        await db.execute(
            select(Supplier.nama_supplier)
            .join(PurchaseBatch, PurchaseBatch.supplier_id == Supplier.id)
            .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
            .where(DryingLotBatch.drying_lot_id == lot_id)
            .distinct()
        )
    ).scalars().all()
    return list(rows)


async def laporan_pengeringan(db: AsyncSession, kode_lot: str | None = None) -> str:
    now = now_local()
    if kode_lot:
        lot = await get_lot_by_kode(db, kode_lot)
        if lot is None:
            return f"Lot {kode_lot} tidak ditemukan."
        n = await _batch_count(db, lot.id)
        log = await _latest_log(db, lot.id)
        sups = await _lot_suppliers(db, lot.id)
        nama = ", ".join(sups) if sups else "-"
        lines = [
            f"🌾 Lot pengeringan {lot.kode_lot} — bahan dari {nama}",
            f"• Status: {lot.status}",
            f"• Jumlah batch: {n}",
            f"• Kadar air terbaru: {_fmt_ka(log)}",
        ]
        if lot.status == "proses":
            ref = log.waktu_update if log else lot.waktu_mulai_pengeringan
            lines.append(f"• Terakhir diupdate: {_hours(now, ref):.1f} jam lalu")
        else:
            lines.append(
                f"• Durasi: {_hours(lot.waktu_selesai_pengeringan, lot.waktu_mulai_pengeringan):.1f} jam"
            )
        return "\n".join(lines)

    # Semua lot yang masih di dalam dryer: dikeringkan atau didinginkan.
    lots = (
        await db.execute(
            select(DryingLot).where(*_in_dryer_where()).order_by(DryingLot.id)
        )
    ).scalars().all()
    dryer = await _g1_dryer(db)
    loose = await _loose_dryer_batches(db)
    loose_line = ""
    if loose:
        lkg = sum(float(b.berat_total_kg or 0) for b in loose)
        loose_line = (
            f"\n⏸️ Menunggu di dryer (belum mulai): {len(loose)} batch, "
            f"{lkg/1000:g} ton — {', '.join(b.kode_batch for b in loose)}.\n"
            "_Ketik `mulai pengeringan` untuk membentuk lot & memulai._"
        )
    if not lots:
        if loose:
            return "🌾 Isi mesin pengering:" + loose_line
        base = "🌾 Tidak ada gabah di mesin pengering."
        if dryer:
            base += f"\nMesin kosong (kapasitas {float(dryer.kapasitas_kg)/1000:g} ton)."
        return base
    header = f"🌾 Isi mesin pengering ({len(lots)} lot)"
    if dryer:
        load = await dryer_load_kg(db)
        cap = float(dryer.kapasitas_kg)
        header += f" — {load/1000:g}/{cap/1000:g} ton (sisa {max(cap-load,0)/1000:g} ton)"
    lines = [header + ":"]
    for lot in lots:
        if lot.status == "proses":
            log = await _latest_log(db, lot.id)
            ref = log.waktu_update if log else lot.waktu_mulai_pengeringan
            gap = _hours(now, ref)
            warn = " ⚠️telat" if gap >= 5 else ""
            lines.append(
                f"• {lot.kode_lot} [mengeringkan]: {_fmt_ka(log)} — {gap:.1f} jam lalu{warn}"
            )
        else:  # 'selesai' & masih di dryer = fase pendinginan
            since = lot.waktu_selesai_pengeringan or lot.waktu_mulai_pengeringan
            jam = _hours(now, since) if since else 0
            lines.append(f"• {lot.kode_lot} [pendinginan]: sudah {jam:.1f} jam")
    return "\n".join(lines) + loose_line


# ─────────────────────── Cek keterlambatan (scheduler) ───────────────────────
async def check_late_drying(
    db: AsyncSession, late_hours: float
) -> list[tuple[DryingLot, float]]:
    """Temukan lot 'proses' yang log kadar airnya telat > late_hours.

    Membuat notifikasi (sekali per keterlambatan) dan mengembalikan daftar
    (lot, jam_telat) yang BARU ditandai untuk dikirim ke Telegram.
    """
    now = now_local()
    lots = (
        await db.execute(select(DryingLot).where(DryingLot.status == "proses"))
    ).scalars().all()
    alerts: list[tuple[DryingLot, float]] = []
    for lot in lots:
        log = await _latest_log(db, lot.id)
        ref = log.waktu_update if log else lot.waktu_mulai_pengeringan
        gap = _hours(now, ref)
        if gap < late_hours:
            continue
        # Sudah ada notifikasi terbuka? jangan duplikasi.
        open_notif = (
            await db.execute(
                select(Notification.id).where(
                    Notification.tipe == "pengeringan_telat",
                    Notification.record_id == lot.id,
                    Notification.status == "baru",
                )
            )
        ).first()
        if open_notif:
            continue
        db.add(
            Notification(
                tipe="pengeringan_telat",
                record_id=lot.id,
                table_name="drying_lots",
                target_role="operator",
                pesan=f"🔴 {lot.kode_lot}: kadar air belum diupdate {gap:.1f} jam (batas {late_hours:g} jam).",
                prioritas="merah",
                status="baru",
            )
        )
        alerts.append((lot, gap))
    if alerts:
        await db.commit()
    return alerts
