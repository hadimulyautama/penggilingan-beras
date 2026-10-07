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
from app.penggilingan.gudang1.services.bobot import dari_batch, dari_batches
from app.penggilingan.gudang1.services.timbang_link import berat_kotor_tiket
from app.services.codegen import next_drying_lot_code
from app.services.jasa import (
    JasaError,
    kunci_dryer,
    nama_pemilik,
    pastikan_satu_jasa_bernama,
)


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
        raise DryingError("Sebutkan kode lot, contoh: `pendinginan PGR-20260702-01`")
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
        raise DryingError("Sebutkan kode lot, contoh: `pendinginan selesai PGR-20260702-01`")
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
    """Yang DIKETAHUI saja — batch yang belum punya angka tak terhitung."""
    return dari_batches(await _loose_dryer_batches(db, dryer_id)).angka()


async def _berat_untuk_pagar(db: AsyncSession, batches) -> tuple[float, str]:
    """Berat untuk PAGAR KAPASITAS: batas atas, bukan bawah (QA P6-04).

    Truk yang belum ditimbang kedua tak punya netto, tetapi punya berat KOTOR
    (timbang pertama) — dan kotor ≥ netto: yang muat dengan berat kotornya
    pasti muat dengan nettonya. Dulu ia dihitung 0 dan pengering yang sudah
    85 % menerima 15 ton lagi: 135 %. Perkiraan dipakai apa adanya. Yang tak
    punya angka DAN tak punya tiket ditolak — pagar yang tak bisa menilai
    bukan pagar.

    → (total kg untuk pagar, catatan untuk pesan penolakan).
    """
    total = 0.0
    catatan: list[str] = []
    for b in batches:
        bb = dari_batch(b)
        if bb.diketahui:
            total += bb.angka()
            continue
        kotor = await berat_kotor_tiket(db, b.timbangan_transaksi_id)
        if kotor is None:
            raise DryingError(
                f"{b.kode_batch} belum punya bobot sama sekali, jadi tak bisa "
                "dinilai muat atau tidak. Tunggu timbang keduanya.")
        total += kotor
        catatan.append(f"{b.kode_batch} belum ditimbang kedua — dihitung "
                       f"berat kotornya {kotor:,.0f} kg".replace(",", "."))
    return total, ("; " + "; ".join(catatan) if catatan else "")


async def isi_dryer(
    db: AsyncSession, dryer_id: int
) -> tuple[str, float] | None:
    """Kondisi & berat gabah yang SEDANG ada di dalam satu mesin — None bila kosong.

    Gabah di dryer punya dua bentuk: batch lepas yang menunggu mesin
    dinyalakan, dan lot yang sedang dikeringkan atau didinginkan. Keduanya
    sama-sama "ada gabah di dalam", dan larangan mencampur basah dengan kering
    berlaku untuk keduanya — termasuk setelah pengeringan dan pendinginan
    dinyatakan selesai, selama gabahnya belum keluar ke silo.

    Dipakai untuk MENUTUP pilihan sebelum orang menekannya. Penolakan setelah
    ditekan tetap ada di `masuk_dryer`, tetapi saat itu batch-nya sudah
    terlanjur tercatat dan harus ditempatkan ulang dengan tangan.
    """
    lot = await active_drying_lot(db, dryer_id)
    if lot is not None:
        batches = await _lot_batches(db, lot.id)
        if batches:
            return (batches[0].kondisi_gabah, dari_batches(batches).angka())
    loose = await _loose_dryer_batches(db, dryer_id)
    if loose:
        return (loose[0].kondisi_gabah, dari_batches(loose).angka())
    return None


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

    # ── MESINNYA DIKUNCI sebelum isinya dibaca ──
    #
    # Pemeriksaan pemilik di bawah ini tak berarti apa-apa tanpa kunci: dua
    # operator yang memasukkan gabah dua pemilik ke mesin yang sama pada detik
    # yang sama sama-sama membaca "isinya milik pabrik", dan keduanya lolos.
    # Lihat catatan panjang di `jasa.kunci_dryer`.
    await kunci_dryer(db, dryer.id)
    loose = await _loose_dryer_batches(db, dryer.id)
    kondisi_all = {b.kondisi_gabah for b in batches} | {b.kondisi_gabah for b in loose}
    if len(kondisi_all) > 1:
        raise DryingError(
            f"❌ Tidak boleh mencampur gabah basah & kering di {dryer.nama}."
        )
    # ── Dan tidak boleh mencampur PEMILIK ──
    #
    # Sejajar dengan penjaga basah/kering di atasnya, dan untuk alasan yang
    # LEBIH keras: gabah basah yang tercampur kering cuma merusak lotnya;
    # gabah dua pemilik yang tercampur merusak hak orang atas barangnya, dan
    # tak ada tombol yang memisahkannya kembali sesudah mesin menyala.
    #
    # Dijaga DI SINI, bukan hanya saat lotnya terbentuk: lot baru lahir di
    # "mulai pengeringan", sedangkan gabahnya sudah bercampur sejak masuk
    # mesin. Menolak di sana berarti menolak pada saat penolakannya sudah tak
    # berguna.
    try:
        await pastikan_satu_jasa_bernama(
            db, [b.jasa_id for b in batches] + [b.jasa_id for b in loose])
    except JasaError as e:
        raise DryingError(f"❌ {e.args[0]}") from None

    new_total, tak_pasti = await _berat_untuk_pagar(db, batches)
    if dryer is not None:
        if dryer.status != "aktif":
            raise DryingError(f"{dryer.nama} sedang {dryer.status}.")
        load = await loose_dryer_kg(db, dryer.id)
        cap_efektif = float(dryer.kapasitas_kg) + settings.dryer_toleransi_kg
        if load + new_total > cap_efektif:
            sisa = max(cap_efektif - load, 0)
            raise DryingError(
                f"❌ Kapasitas dryer tak cukup (sisa {sisa / 1000:g} ton, "
                f"batch ini {new_total / 1000:g} ton{tak_pasti})."
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
    # Lotnya DIKUNCI, bukan cuma dibaca: dua operator yang menambahkan batch
    # dua pemilik ke lot yang sama pada detik yang sama sama-sama membaca
    # pemilik lot yang lama. Pola yang sama dipakai `masuk_silo` untuk lot
    # (P-K-05) dan `create_internal_transfer` untuk proses giling (P-K-06).
    lot = (await db.execute(
        select(DryingLot).where(DryingLot.kode_lot == kode_lot).with_for_update()
    )).scalars().first()
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

    # Pemilik lot lawan pemilik batch tambahan. Lotnya SUDAH dikunci di atas
    # (`with_for_update` saat diambil), jadi pemeriksaan ini tak bisa disalip.
    try:
        pemilik = await pastikan_satu_jasa_bernama(
            db, [lot.jasa_id] + [b.jasa_id for b in batches])
    except JasaError as e:
        raise DryingError(f"❌ {e.args[0]}") from None
    lot.jasa_id = pemilik

    new_total, tak_pasti = await _berat_untuk_pagar(db, batches)
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
                f"(sisa {sisa / 1000:g} ton, tambahan {new_total / 1000:g} ton{tak_pasti})."
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
    total_kg = dari_batches(all_batches).angka()
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
    #: Terisi hanya bila target BERUBAH pada pencatatan ini.
    target_lama: float | None = None
    target_kini: float | None = None


async def log_moisture(
    db: AsyncSession,
    *,
    user,
    kode_lot: str | None,
    indikator: float | None = None,
    tes_manual: float | None = None,
    sampel: list[float | None] | None = None,
    target_baru: float | None = None,
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
        raise DryingError("Sebutkan kode lot-nya, contoh: `kadar air PGR-20260702-01 18%`")
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status == "selesai":
        raise DryingError(f"Lot {kode_lot} sudah selesai — tidak bisa menambah log.")
    # Target boleh berubah SEIRING pengeringan — gabah yang ternyata lebih
    # basah dari dugaan, atau pembeli yang berubah maunya. Perubahannya
    # dicatat di jurnal aktivitas: garis selesai yang bergeser tanpa jejak
    # membuat "kenapa berhenti di 15%?" tak bisa dijawab bulan depan.
    target_lama = float(lot.target_kadar_air) if lot.target_kadar_air is not None else None
    if target_baru is not None and target_baru != target_lama:
        lot.target_kadar_air = target_baru
        await log_activity(
            db, table_name="drying_lots", record_id=lot.id, action="UPDATE",
            changed_by=user.id, field_name="target_kadar_air",
            old_value=str(target_lama), new_value=str(target_baru),
            # Ditandai, kalau tidak pembatalannya jatuh ke `_undo_lot_merge`
            # dan justru MENGELUARKAN batch dari lot yang sedang dikeringkan.
            aksi="ubah_target",
        )

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
        target_lama=(target_lama if (target_baru is not None
                                     and target_baru != target_lama) else None),
        target_kini=(float(lot.target_kadar_air)
                     if lot.target_kadar_air is not None else None),
    )


# ─────────────────────────── Selesai ───────────────────────────
#: Mode dryer menurut tonase. Angka mesin, bukan pilihan gaya — mesin ini
#: memang punya lima setelan itu.
MODE_DRYER = ("15T", "20T", "25T", "30T", "35T")


def mode_disarankan(kg: float) -> str:
    """Mode yang tonasenya PALING DEKAT dengan muatan.

    23 ton → 25T, bukan 20T: yang dicari jarak terdekat, bukan yang di
    bawahnya. Aturannya dari pemilik, dan dihitung di sini supaya operator
    tak perlu menghitung sendiri sambil berdiri di depan mesin.
    """
    ton = (kg or 0) / 1000
    return min(MODE_DRYER, key=lambda m: abs(int(m[:-1]) - ton))


async def start_drying(
    db: AsyncSession, *, user, dryer_id: int | None = None,
    target_kadar_air: float | None = None, mode_dryer: str | None = None,
    tanggal=None, jam=None,
) -> LotResult:
    """MULAI pengeringan: bentuk 1 LOT dari SEMUA batch yang menunggu di dryer,
    lalu status 'proses'. Lot lahir di sini (bukan saat masuk dryer).

    Masuk dryer ≠ mulai pengeringan — ini input terpisah (operator G1 utama)."""
    dryer = await pilih_dryer(db, dryer_id)
    # Dikunci sebelum isinya dibaca, sama seperti `masuk_dryer`: gabah bisa
    # masuk mesin pada detik lot ini dibentuk, dan lot yang lahir dari isi yang
    # sudah bergeser akan mewarisi pemilik yang bukan pemilik seluruh isinya.
    await kunci_dryer(db, dryer.id)
    loose = await _loose_dryer_batches(db, dryer.id)
    if not loose:
        raise DryingError(
            f"Tidak ada gabah di {dryer.nama}. Masukkan dulu, "
            "mis. `keringkan GB-...`."
        )
    # Target WAJIB — keputusan pemilik. Pengeringan tanpa target adalah
    # pengeringan yang tak punya garis selesai: kemajuannya tak bisa dihitung,
    # dan "sudah cukup kering" jadi perasaan, bukan angka.
    if target_kadar_air is None:
        raise DryingError(
            "Sebutkan target kadar airnya dulu — sampai berapa muatan ini "
            "dikeringkan."
        )
    kondisi_set = {b.kondisi_gabah for b in loose}
    if len(kondisi_set) > 1:
        raise DryingError("❌ Ada campuran basah & kering di dryer — pisahkan dulu.")
    kondisi = kondisi_set.pop()
    # Pemilik lot DITURUNKAN dari seluruh isi mesin, bukan dari batch pertama.
    # `masuk_dryer` sudah menolak campuran pemilik, jadi di sini seharusnya
    # tunggal — tetapi "seharusnya" bukan penjaga: gabah bisa masuk mesin lewat
    # `tempatkan`, dan satu jalur yang lupa memanggil penjaganya akan melahirkan
    # lot bercampur yang tak pernah ditolak di mana pun.
    try:
        pemilik_lot = await pastikan_satu_jasa_bernama(db, [b.jasa_id for b in loose])
    except JasaError as e:
        raise DryingError(f"❌ {e.args[0]}") from None
    now = input_time(tanggal, jam)
    lot = DryingLot(
        kode_lot=await next_drying_lot_code(db),
        dryer_id=dryer.id,
        jasa_id=pemilik_lot,
        target_kadar_air=target_kadar_air,
        mode_dryer=(mode_dryer or "").strip().upper() or None,
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
        total += dari_batch(b).angka()
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
    # DAFTAR, bukan satu kalimat: mode yang tak cocok dan muatan satu batch
    # adalah dua hal berbeda, dan yang belakangan tak boleh menghapus yang
    # duluan. Sebelumnya keduanya menulis ke variabel yang sama, jadi
    # peringatan mode lenyap tiap kali muatannya kebetulan satu batch.
    catatan: list[str] = []

    # Mode yang dipilih dibandingkan dengan yang seharusnya — DIPERINGATKAN,
    # bukan ditolak. Yang disimpan adalah pernyataan operator tentang setelan
    # mesin yang sungguhan; menolaknya berarti memaksa ia menuliskan mode yang
    # BUKAN yang terpasang, dan catatan yang berbohong lebih buruk daripada
    # catatan yang menyimpan ketidakcocokan beserta alasannya.
    if lot.mode_dryer:
        seharusnya = mode_disarankan(total)
        if lot.mode_dryer != seharusnya:
            catatan.append(
                f"⚠️ Muatan {total / 1000:.1f} ton — mode terdekat {seharusnya}, "
                f"bukan {lot.mode_dryer}. Periksa setelan di mesin."
            )
    if len(loose) < 2:
        catatan.append(
            f"⚠️ Hanya 1 batch ({total:.0f} kg) — pengeringan sebaiknya "
            "menggabungkan minimal 2 batch. Tetap dijalankan."
        )
    peringatan = "\n".join(catatan) or None
    return LotResult(lot=lot, kondisi=kondisi, total_kg=total,
                     batch_kodes=[b.kode_batch for b in loose],
                     nama_dryer=dryer.nama, peringatan=peringatan)


async def finish_drying(
    db: AsyncSession, *, user, kode_lot: str | None,
    kadar_air_akhir: float | None = None, tanggal=None, jam=None
) -> tuple[DryingLot, float]:
    """Nyatakan pengeringan selesai — berikut kadar air yang TERTERA DI MESIN.

    Angka itu wajib, dan alasannya bukan kerapian data. Kadar air akhir adalah
    satu-satunya jawaban atas pertanyaan "kenapa pengeringan ini dihentikan di
    sini?", dan ia satu-satunya yang menghubungkan lama pengeringan dengan
    hasilnya. Tanpa dicatat pada saat mesin dimatikan, ia tak akan pernah
    tercatat: gabahnya pindah ke silo, bercampur, lalu digiling, dan angka itu
    hilang bersama momennya.

    Sebelumnya menyelesaikan pengeringan tak menuntut apa pun selain memilih
    lotnya. Yang mencatat kadar air adalah aksi TERPISAH ("Perbarui kadar
    air") yang dipakai selama proses berjalan — jadi lot yang dikeringkan
    tanpa sekali pun diperbarui akan selesai tanpa satu angka pun, dan tak ada
    layar yang memberi tahu bahwa ia kosong.

    Dicatat lewat `log_moisture` yang sudah ada, BUKAN dengan menulis kolom
    baru: satu jalan masuk berarti satu jalan pembatalan, satu bentuk jurnal,
    dan tak ada angka kedua yang bisa berselisih dengan yang pertama. Ia
    ditulis SEBELUM status berpindah — `log_moisture` menolak lot yang sudah
    "selesai", dan penolakan itu benar: sesudah selesai, log baru bukan lagi
    pengukuran melainkan koreksi.
    """
    if not kode_lot:
        raise DryingError("Sebutkan kode lot yang selesai, contoh: `PGR-20260702-01 selesai`")
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
        # ── Seluruh penolakan SEBELUM satu pun perubahan ──
        #
        # Aturan yang sama dipakai `finish_milling`, dan ia ada karena
        # pelanggarannya pernah mahal: proses yang setengah tertutup — status
        # sudah berpindah, angkanya ditolak — meninggalkan lot yang tak muncul
        # di layar mana pun. Tak di antrean karena sudah selesai, tak di
        # laporan karena datanya belum lengkap.
        if kadar_air_akhir is None:
            raise DryingError(
                "Sebutkan kadar air yang tertera di mesin saat dimatikan. "
                "Angka itu yang menjawab kenapa pengeringan dihentikan di "
                "sini, dan ia tak bisa dicari lagi setelah gabahnya pindah."
            )
        if not 0 < float(kadar_air_akhir) <= 100:
            raise DryingError(
                f"Kadar air {kadar_air_akhir:g}% di luar akal — isikan persen, "
                f"bukan berat."
            )
        # Dicatat lebih dulu, selagi lotnya masih berjalan. `log_moisture`
        # melakukan commit-nya sendiri; itu tak mengapa, karena baris ini
        # sebuah PENGUKURAN yang memang terjadi — ia tetap benar walau
        # penutupan di bawahnya gagal.
        await log_moisture(db, user=user, kode_lot=kode_lot,
                           indikator=float(kadar_air_akhir),
                           tanggal=tanggal, jam=jam)
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


async def ubah_target(
    db: AsyncSession, *, user, kode_lot: str | None, target: float | None
) -> tuple[DryingLot, float | None]:
    """Geser garis selesai pengeringan — sendirian, tanpa mencatat kadar air.

    Sebelumnya target hanya bisa berubah sebagai medan SAMPINGAN di borang
    "Perbarui kadar air", dan ia menumpang pada `log_moisture` yang menolak
    kiriman tanpa satu pun bacaan. Jadi mengubah target menuntut ikut mengukur
    kadar air — padahal keputusan menggeser garis selesai justru sering datang
    tanpa pengukuran baru: pembeli berubah maunya, atau gabahnya ternyata
    untuk pasar yang lain.

    Dipisah juga karena bobotnya berbeda. Mencatat kadar air melaporkan apa
    yang TERBACA; mengubah target menetapkan kapan mesin dimatikan, dan itu
    ikut menentukan gabah ini dijual sebagai apa. Dua hal sebesar itu tak
    pantas berbagi satu tombol Simpan.

    Perubahannya dicatat di jurnal aktivitas berikut nilai lamanya: garis
    selesai yang bergeser tanpa jejak membuat "kenapa berhenti di 15%?" tak
    bisa dijawab bulan depan.
    """
    if not kode_lot:
        raise DryingError("Sebutkan kode lot yang targetnya diubah.")
    if target is None:
        raise DryingError("Sebutkan target kadar airnya.")
    if not 0 < float(target) <= 100:
        raise DryingError(
            f"Target {target:g}% di luar akal — isikan persen, bukan berat."
        )
    lot = await get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise DryingError(f"Lot {kode_lot} tidak ditemukan.")
    if lot.status == "selesai":
        raise DryingError(
            f"Lot {kode_lot} sudah selesai — targetnya tak bisa diubah lagi."
        )

    lama = float(lot.target_kadar_air) if lot.target_kadar_air is not None else None
    if lama is not None and abs(lama - float(target)) < 1e-9:
        raise DryingError(f"Targetnya memang sudah {target:g}%.")

    lot.target_kadar_air = float(target)
    await log_activity(
        db, table_name="drying_lots", record_id=lot.id, action="UPDATE",
        changed_by=user.id, field_name="target_kadar_air",
        old_value=str(lama), new_value=str(float(target)),
        # Lihat catatan di `log_moisture`: tanpa tag ini, membatalkan
        # perubahan target mengeluarkan gabah dari lotnya.
        aksi="ubah_target",
    )
    await db.commit()
    await db.refresh(lot)
    return lot, lama


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
    """Asal bahan sebuah lot pengeringan — pemasoknya, atau pemiliknya.

    ⚠ DULU INNER JOIN KE `suppliers`, DAN ITU MENGHILANGKAN BARIS. Begitu
    `purchase_batches.supplier_id` boleh NULL (migrasi 0064), lot yang berisi
    gabah jasa menampilkan daftar KOSONG — bukan angka yang salah, BARISNYA
    HILANG, dan yang membaca laporan menyimpulkan lotnya kosong. Itu kelas
    kerusakan yang paling sulit dilihat: tak ada galat, tak ada angka ganjil,
    cuma ketiadaan.

    `outerjoin` + sebutan pemiliknya: lot jasa menyebut "JAS-2610-007 Pak Budi"
    di tempat nama pemasok biasanya berdiri — pertanyaan yang dijawab baris ini
    memang "gabah siapa", dan untuk barang titipan jawabannya pemiliknya.
    """
    rows = (
        await db.execute(
            select(Supplier.nama_supplier, PurchaseBatch.jasa_id)
            .select_from(DryingLotBatch)
            .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
            .outerjoin(Supplier, PurchaseBatch.supplier_id == Supplier.id)
            .where(DryingLotBatch.drying_lot_id == lot_id)
            .distinct()
        )
    ).all()
    keluar: list[str] = []
    for nama, jasa_id in rows:
        sebutan = nama or await nama_pemilik(db, jasa_id) or "?"
        if sebutan not in keluar:
            keluar.append(sebutan)
    return keluar


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
        lkg = dari_batches(loose).angka()
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


async def kadar_air_awal(db: AsyncSession, lot_id: int) -> float | None:
    """Bacaan PERTAMA lot ini — titik tolak kemajuan.

    Tanpanya tak ada yang bisa disebut "sudah sejauh mana": 18% itu jauh atau
    dekat sepenuhnya tergantung mulai dari berapa.
    """
    row = (await db.execute(
        select(DryingMoistureLog.kadar_air_tes_manual,
               DryingMoistureLog.kadar_air_indikator)
        .where(DryingMoistureLog.drying_lot_id == lot_id)
        .order_by(DryingMoistureLog.waktu_update.asc()).limit(1)
    )).first()
    if row is None:
        return None
    nilai = row[0] if row[0] is not None else row[1]
    return float(nilai) if nilai is not None else None


def kemajuan(awal: float | None, kini: float | None, target: float) -> float | None:
    """Sejauh mana lot bergerak dari bacaan pertamanya menuju target — 0..1.

    Satu rumus dipakai bersama oleh dashboard dan layar Beranda. Dua salinan
    rumus yang sama adalah dua angka yang cepat atau lambat berbeda, dan yang
    berbeda diam-diam justru tak akan pernah ada yang menyadarinya.

    None berarti belum bisa dihitung — belum ada bacaan, atau gabahnya sudah
    lebih kering dari target sejak awal sehingga tak ada jarak untuk ditempuh.
    """
    if kini is not None and kini <= target:
        return 1.0
    if awal is None or kini is None or awal <= target:
        return None
    return max(0.0, min(1.0, (awal - kini) / (awal - target)))


#: Ambang yang membuat sebuah angka layak disebut. Ditaruh di sini, satu
#: tempat, karena keduanya dipakai dua kali: saat mencatat (kabar hasil) dan
#: saat menggambar kartu. Ambang yang disalin akan berselisih, dan yang
#: berselisih membuat kartu berkata "merata" sementara catatannya berkata
#: tidak.
AMBANG_SEBAR = 1.5          # % antara titik terendah & tertinggi
AMBANG_SELISIH_MESIN = 2.0  # % antara bacaan mesin & alat tes


def peringatan_kadar_air(log) -> list[str]:
    """Apa yang perlu diketahui dari SATU bacaan kadar air — kalimat siap baca.

    Dulu keduanya hanya muncul di kabar sekejap sesudah menyimpan, lalu
    hilang bersama kabarnya. Padahal justru inilah yang menerangkan mengapa
    pengeringan tak kunjung turun: gabah yang belum merata, atau sensor mesin
    yang melenceng. Dihitung ULANG dari bacaan tersimpan, bukan disalin dari
    kalimat kabarnya, supaya kartu dan catatan tak pernah berbeda.
    """
    if log is None:
        return []
    titik = [float(x) for x in (log.kadar_air_tes_1, log.kadar_air_tes_2,
                                log.kadar_air_tes_3, log.kadar_air_tes_4)
             if x is not None]
    keluar: list[str] = []
    if len(titik) > 1:
        sebar = max(titik) - min(titik)
        if sebar >= AMBANG_SEBAR:
            keluar.append(f"Sebaran {sebar:.1f}% antara titik terendah & "
                          "tertinggi — gabah belum kering merata.")
    tes = log.kadar_air_tes_manual
    mesin = log.kadar_air_indikator
    if tes is not None and mesin is not None:
        selisih = float(mesin) - float(tes)
        if abs(selisih) >= AMBANG_SELISIH_MESIN:
            keluar.append(f"Mesin membaca {selisih:+.1f}% dari alat tes — "
                          "periksa sensor dryer bila terus begini.")
    return keluar


# ═══════════════════ Riwayat Pengeringan (7 Oktober 2026) ═══════════════════
#
# Sub-menu "Riwayat Proses". Cetakan sama `polishing.riwayat_sosoh()` dan
# `milling.riwayat_giling()` — kartu TIAP lot yang SUDAH SELESAI, terbaru
# dulu, lima-enam kueri borongan apa pun banyaknya kartu.
#
# ⚠⚠ TANPA SATU KOLOM PUN BERNAMA "SUSUT" — dan itu bukan kelalaian, sebab
# tak ada satu tempat pun di seluruh basis data yang menyimpan berat gabah
# KERING saat keluar dryer. `DryingLot` dan `SiloStorage` sama-sama tanpa
# kolom berat; `masuk_silo()` (`silo.py`) menghitung `kg`-nya lewat
# `_lot_kg`→`_lot_bobot`, dan itu membaca ULANG berat BASAH dari
# `PurchaseBatch` (`dari_batches`) — bukan menimbang gabah kering yang baru
# keluar. Satu-satunya berat KERING yang pernah tercatat adalah
# `MillingProcessSource.berat_kg`, dan itu cuma ada kalau lotnya sudah
# PERNAH DIGILING (sebagian, atau belum sama sekali). Jadi "susut
# pengeringan" di sini secara jujur TIDAK BISA DIHITUNG — bukan "0%", bukan
# "belum tersedia": tidak pernah ada cara mengukurnya hari ini. Yang
# ditampilkan hanya yang BENAR-BENAR tercatat: bahan basah masuk, kadar air
# terakhir, dan status silo.
#
# "SELESAI" di sini = `waktu_selesai_pendinginan IS NOT NULL` — bukan cuma
# `status=="selesai"`, yang hanya menutup fase KERINGNYA. Lot bisa
# "selesai" tapi masih di fase dingin; riwayat cuma memuat yang sudah tuntas
# kedua fasenya, pola yang sama dengan `riwayat_sosoh` ("hanya yang
# selesai, proses berjalan punya pintunya sendiri").
@dataclass(frozen=True)
class KartuPengeringan:
    """Satu lot pengeringan yang SUDAH SELESAI (kering + dingin)."""

    id: int
    kode_lot: str
    #: "JAS-2610-001 Pak Budi" bila gabahnya titipan; None = milik pabrik.
    pemilik: str | None
    dryer_nama: str
    mode_dryer: str | None
    target_kadar_air: float | None
    mulai: datetime | None
    selesai_kering: datetime | None
    selesai_dingin: datetime | None
    lama_kering: str
    lama_total: str
    #: Berat basah masuk — bobot EFEKTIF (nota vs timbangan), bukan nota
    #: mentah. `bahan_final=False` berarti sebagian batch belum ditimbang.
    bahan_kg: float
    bahan_final: bool
    #: (pemasok/pemilik, kode+berat, keterangan) — bentuk sama `LotPk.bahan`.
    bahan: list[tuple[str, str, str]]
    #: "indikator 13,0% / manual 12,5%", atau "belum ada log kadar air".
    ka_terakhir: str
    #: Nama silo tujuan, atau None = belum dipindah ke silo sama sekali.
    silo_tujuan: str | None
    waktu_masuk_silo: datetime | None


async def riwayat_pengeringan(db: AsyncSession, *, batas: int = 30,
                              sebelum: int | None = None
                              ) -> tuple[list[KartuPengeringan], bool]:
    """Kartu lot pengeringan SELESAI (kering+dingin), terbaru dulu.

    `sebelum` = id lot TERAKHIR yang sudah digambar (kursor) — pola sama
    `riwayat_sosoh`/`riwayat_giling`. Enam kueri borongan apa pun banyaknya
    kartu (dryer, bahan+pemasok, pemilik bahan tanpa pemasok, kadar air
    terakhir lewat jendela SQL, status silo, pemilik lot) plus satu
    pengambilan lot itu sendiri — dijaga sebagai perbandingan 1 vs 6 kartu
    (`tests/pg/test_riwayat_pengeringan.py`), pola yang sama `riwayat_sosoh`.
    """
    from types import SimpleNamespace

    from app.models import Silo
    from app.services.jasa import nama_pemilik_banyak
    from app.services.berjalan import lama_kata
    from app.services.stok import _baris_bahan

    q = (select(DryingLot)
         .where(DryingLot.waktu_selesai_pendinginan.isnot(None))
         .order_by(DryingLot.id.desc())
         .limit(batas + 1))
    if sebelum:
        q = q.where(DryingLot.id < sebelum)
    lots = (await db.execute(q)).scalars().all()
    lagi = len(lots) > batas
    lots = lots[:batas]
    if not lots:
        return [], False
    ids = [l.id for l in lots]

    dryer_nama = {i: n for i, n in (await db.execute(
        select(Dryer.id, Dryer.nama)
        .where(Dryer.id.in_({l.dryer_id for l in lots if l.dryer_id} or {0}))
    )).all()}

    # Bahan: SELURUH batch dari SELURUH lot, satu kueri — dikelompokkan di
    # Python, pola sama `stok._bahan_banyak`.
    baris_batch = (await db.execute(
        select(DryingLotBatch.drying_lot_id, PurchaseBatch, Supplier.nama_supplier)
        .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
        .outerjoin(Supplier, PurchaseBatch.supplier_id == Supplier.id)
        .where(DryingLotBatch.drying_lot_id.in_(ids))
        .order_by(DryingLotBatch.id)
    )).all()
    batch_per_lot: dict[int, list] = {}
    for lot_id, b, nama_sup in baris_batch:
        batch_per_lot.setdefault(lot_id, []).append((b, nama_sup))
    # Batch tanpa pemasok (titipan jasa) menyebut PEMILIKnya — borongan,
    # bukan `nama_pemilik` satu per baris (lihat catatan `_lot_suppliers`
    # tentang kenapa baris ini wajib tetap ada, bukan sekadar "?").
    jasa_ids_batch = {b.jasa_id for rows in batch_per_lot.values()
                      for b, nama in rows if nama is None and b.jasa_id}
    nama_pemilik_batch = await nama_pemilik_banyak(db, jasa_ids_batch)

    # Kadar air TERAKHIR per lot — satu kueri, jendela SQL (pola sama
    # `milling.progress_banyak`), bukan `_latest_log` yang satu-lot.
    urut = func.row_number().over(
        partition_by=DryingMoistureLog.drying_lot_id,
        order_by=DryingMoistureLog.waktu_update.desc(),
    ).label("urut")
    sub = select(
        DryingMoistureLog.drying_lot_id.label("lid"),
        DryingMoistureLog.kadar_air_indikator.label("ind"),
        DryingMoistureLog.kadar_air_tes_manual.label("man"),
        urut,
    ).where(DryingMoistureLog.drying_lot_id.in_(ids)).subquery()
    ka_per_lot = {lid: (ind, man) for lid, ind, man in (await db.execute(
        select(sub.c.lid, sub.c.ind, sub.c.man).where(sub.c.urut == 1)
    )).all()}

    # Status silo — baris PALING AWAL per lot (lazimnya cuma satu baris
    # seumur hidup lot: "1 silo = 1 lot sekaligus" selama masih terisi, dan
    # lot yang sama tak masuk silo dua kali).
    silo_per_lot: dict[int, tuple[int, datetime]] = {}
    for lid, sid, tgl in (await db.execute(
        select(SiloStorage.drying_lot_id, SiloStorage.silo_id,
              SiloStorage.tanggal_masuk)
        .where(SiloStorage.drying_lot_id.in_(ids))
        .order_by(SiloStorage.tanggal_masuk.asc())
    )).all():
        silo_per_lot.setdefault(lid, (sid, tgl))
    nama_silo = {i: n for i, n in (await db.execute(
        select(Silo.id, Silo.nama_silo)
        .where(Silo.id.in_({sid for sid, _ in silo_per_lot.values()} or {0}))
    )).all()}

    pemilik = await nama_pemilik_banyak(db, {l.jasa_id for l in lots})

    kartu = []
    for lot in lots:
        baris = batch_per_lot.get(lot.id, [])
        bobot = dari_batches(b for b, _ in baris)
        bahan = [_baris_bahan(
            b, nama or (nama_pemilik_batch.get(b.jasa_id) if b.jasa_id else None))
            for b, nama in baris]
        # `in` di kamus, bukan `.get(..., (None, None))`: lot yang tak punya
        # satu pun log kadar air harus berkata "belum ada log kadar air"
        # (lewat `log=None`), bukan "-" — dan dua keadaan itu sama-sama
        # terbaca `(None, None)` bila disamakan lewat bawaan `.get()`.
        log_ka = (SimpleNamespace(kadar_air_indikator=ka_per_lot[lot.id][0],
                                  kadar_air_tes_manual=ka_per_lot[lot.id][1])
                 if lot.id in ka_per_lot else None)
        sid, tgl_masuk = silo_per_lot.get(lot.id, (None, None))
        kartu.append(KartuPengeringan(
            id=lot.id, kode_lot=lot.kode_lot,
            pemilik=pemilik.get(lot.jasa_id) if lot.jasa_id else None,
            dryer_nama=dryer_nama.get(lot.dryer_id) or "?",
            mode_dryer=lot.mode_dryer,
            target_kadar_air=(float(lot.target_kadar_air)
                             if lot.target_kadar_air is not None else None),
            mulai=lot.waktu_mulai_pengeringan,
            selesai_kering=lot.waktu_selesai_pengeringan,
            selesai_dingin=lot.waktu_selesai_pendinginan,
            lama_kering=(lama_kata((lot.waktu_selesai_pengeringan
                                    - lot.waktu_mulai_pengeringan).total_seconds())
                        if lot.waktu_mulai_pengeringan and lot.waktu_selesai_pengeringan
                        else ""),
            lama_total=(lama_kata((lot.waktu_selesai_pendinginan
                                   - lot.waktu_mulai_pengeringan).total_seconds())
                       if lot.waktu_mulai_pengeringan else ""),
            bahan_kg=bobot.angka(), bahan_final=bobot.pasti, bahan=bahan,
            ka_terakhir=_fmt_ka(log_ka),
            silo_tujuan=(nama_silo.get(sid) if sid else None),
            waktu_masuk_silo=tgl_masuk,
        ))
    return kartu, lagi
