"""Logika bisnis proses milling / pecah kulit (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.angka import AngkaError, angka_wajar
from app.database import input_time, now_local
from app.models import (
    DryingLot,
    DryingLotBatch,
    InternalTransfer,
    MillingProcess,
    MillingProcessSource,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchVerification,
    Silo,
    SiloStorage,
    Supplier,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_drying_lot_code, next_milling_code
from app.penggilingan.gudang1.services.silo import _silo_active_rows, get_g1_silo


class MillingError(Exception):
    """Kesalahan proses milling dengan pesan siap-tampil (args[0])."""


async def get_process_by_kode(db: AsyncSession, kode: str) -> MillingProcess | None:
    return (
        await db.execute(select(MillingProcess).where(MillingProcess.kode_proses == kode))
    ).scalars().first()


async def sole_active_milling_kode(db: AsyncSession) -> str | None:
    """Kode proses bila TEPAT ADA SATU milling yang sedang 'proses'; else None.

    Memungkinkan 'giling selesai' / 'progress 5 ton' tanpa menyebut kode.
    """
    rows = (
        await db.execute(
            select(MillingProcess.kode_proses).where(MillingProcess.status == "proses")
        )
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def _storage_kg(db: AsyncSession, st: SiloStorage) -> float:
    if st.drying_lot_id:
        stmt = (
            select(func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0))
            .select_from(DryingLotBatch)
            .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
            .where(DryingLotBatch.drying_lot_id == st.drying_lot_id)
        )
        return float((await db.execute(stmt)).scalar_one())
    if st.purchase_batch_id:
        b = await db.get(PurchaseBatch, st.purchase_batch_id)
        return float(b.berat_total_kg or 0) if b else 0.0
    return 0.0


async def _active_storage(db: AsyncSession, silo_id: int) -> SiloStorage | None:
    return (
        await db.execute(
            select(SiloStorage).where(
                SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
            )
        )
    ).scalars().first()


# ─────────────────────────── Mulai ───────────────────────────
@dataclass
class StartResult:
    proc: MillingProcess
    nama_silo: str
    berat_masuk: float


async def start_milling(
    db: AsyncSession, *, user, nama_silo: str | None, tanggal=None, jam=None
) -> StartResult:
    if not nama_silo:
        raise MillingError("Sebutkan silo mana, contoh: `giling silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise MillingError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    rows = await _silo_active_rows(db, silo.id)
    if not rows:
        raise MillingError(f"Silo {nama_silo} kosong — tidak ada yang bisa digiling.")
    active = (
        await db.execute(
            select(MillingProcess).where(
                MillingProcess.silo_id == silo.id, MillingProcess.status == "proses"
            )
        )
    ).scalars().first()
    if active:
        raise MillingError(f"Silo {nama_silo} sedang digiling ({active.kode_proses}).")

    now = input_time(tanggal, jam)

    # SELURUH isi silo masuk ke satu proses giling — bukan satu baris saja.
    #
    # Dulu di sini dipilih SATU baris: kalau ada lot hasil pengeringan, itu
    # yang diambil; kalau tidak, batch-batch lepas dikonsolidasi jadi lot baru.
    # Selama satu silo hanya boleh berisi satu hal, keduanya cukup. Begitu silo
    # boleh dicampur, cabang pertama diam-diam mengabaikan batch lepas yang ada
    # di silo yang sama: gabahnya ikut tergiling, tetapi tidak ikut tercatat.
    #
    # `drying_lots` sekarang berarti satu PROSES PENGERINGAN, dan apa yang
    # digiling bersama didaftar di `milling_process_sources`.
    berat_per_baris: list[tuple[SiloStorage, float]] = []
    for r in rows:
        berat_per_baris.append((r, await _storage_kg(db, r)))
    berat = sum(k for _, k in berat_per_baris)

    # Penunjuk tunggal di `MillingProcess` tetap diisi supaya laporan, undo,
    # dan rekonsiliasi yang membacanya tidak mati sekaligus. Yang dipilih:
    # baris lot bila ada — itulah sumber terbesar dan paling berarti.
    st = next((r for r in rows if r.drying_lot_id), rows[0])
    proc = MillingProcess(
        kode_proses=await next_milling_code(db),
        silo_id=silo.id,
        silo_storage_id=st.id,
        drying_lot_id=st.drying_lot_id,
        purchase_batch_id=st.purchase_batch_id,
        berat_gabah_masuk_kg=berat,
        waktu_mulai=now,
        status="proses",
        created_by=user.id,
    )
    db.add(proc)
    await db.flush()
    for r, kg in berat_per_baris:
        db.add(MillingProcessSource(
            milling_process_id=proc.id, silo_storage_id=r.id,
            drying_lot_id=r.drying_lot_id, purchase_batch_id=r.purchase_batch_id,
            berat_kg=kg,
        ))
    await db.flush()
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"{proc.kode_proses} <- Silo {nama_silo} ({berat:.0f}kg)",
    )
    await db.commit()
    await db.refresh(proc)
    return StartResult(proc=proc, nama_silo=nama_silo, berat_masuk=berat)


# ─────────────────────────── Progress ───────────────────────────
@dataclass
class ProgressResult:
    proc: MillingProcess
    berat_kumulatif: float
    rendemen_persen: float | None
    jenis: str | None = None  # KS (dibeli basah) / KL (dibeli kering) / MIX (dua-duanya)
    peringatan: str | None = None


def hitung_rendemen(hasil: float | None, masuk: float | None) -> float | None:
    """Berapa persen gabah yang keluar jadi PK. None bila bahannya tak diketahui.

    Rumusnya sepele; yang tidak sepele adalah PENYEBUTNYA selalu sama.
    `berat_gabah_masuk_kg` adalah cuplikan berat bahan saat giling dimulai, dan
    ia disinkronkan ulang ketika timbangan membetulkan tiketnya. Kalau ada
    layar yang memakai penyebut lain — berat batch, isi silo — dua layar akan
    menyebut rendemen berbeda untuk lot yang sama, dan yang melihatnya akan
    mencari sebabnya di mesin, bukan di catatan.
    """
    masuk = float(masuk or 0)
    if not masuk or hasil is None:
        return None
    return float(hasil) / masuk * 100


async def stok_pk_g1(db: AsyncSession) -> float:
    """PK yang MENUMPUK di Gudang 1 — belum dikirim, belum dijual.

    Tidak disimpan sebagai keadaan tersendiri, dan itu disengaja. "Ditumpuk"
    dan "langsung dibawa ke penyosohan" bukan dua jalan yang perlu dinyatakan
    operator: yang membedakan keduanya hanya ADA TIDAKNYA transfer, dan itu
    sudah tercatat. Menyuruh orang menyatakannya lagi berarti dua sumber untuk
    satu fakta — dan yang salah selalu yang diketik manual, karena orang lupa
    memperbaruinya setelah barangnya benar-benar pindah.
    """
    total = 0.0
    for proc in (await db.execute(select(MillingProcess))).scalars().all():
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia > 0:
            total += bd.tersedia
    return total


async def log_progress(
    db: AsyncSession, *, user, kode_proses: str | None, berat_kumulatif: float | None,
    tanggal=None, jam=None,
) -> ProgressResult:
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `progress giling LOT-20260702-01 5 ton`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")
    if berat_kumulatif is None:
        raise MillingError("Sebutkan berat PK kumulatifnya, mis. `LOT-... sudah 5 ton`.")
    # Dijaga DI SINI juga, bukan cuma di model permintaan: lapisan AI dan
    # sebagian rute memanggil layanan ini langsung, dan NaN yang lolos di satu
    # tempat akan menular ke seluruh kolom yang menjumlahkannya.
    try:
        berat_kumulatif = angka_wajar(berat_kumulatif, "Berat PK kumulatif")
    except AngkaError as e:
        raise MillingError(str(e)) from None

    db.add(
        MillingProgressLog(
            milling_process_id=proc.id,
            waktu_update=input_time(tanggal, jam),
            berat_kumulatif_kg=berat_kumulatif,
            input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="milling_progress_logs", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"kumulatif {berat_kumulatif:.0f}kg",
    )
    await db.commit()
    rendemen = hitung_rendemen(berat_kumulatif, proc.berat_gabah_masuk_kg)
    jenis = await pk_jenis(db, proc)

    # Lantainya penuh — DIBERITAHU, bukan ditolak.
    #
    # PK ini sudah keluar dari mesin sebelum siapa pun mengetiknya. Menolak
    # mencatatnya tidak membuatnya lenyap; ia hanya membuat catatan berbohong,
    # dan justru menyembunyikan keadaan yang paling perlu dilihat. Beda dengan
    # tumpukan Gudang 2 yang MENOLAK: di sana yang dijaga adalah keputusan
    # penempatan, dan keputusan masih bisa dialihkan ke silo.
    peringatan = None
    stok = await stok_pk_g1(db)
    cap = settings.g1_pk_tumpukan_maks_kg
    if stok > cap:
        peringatan = (
            f"⚠️ Tumpukan PK Gudang 1 {stok / 1000:g} ton — melewati batas lantai "
            f"{cap / 1000:g} ton. Kirim ke gudang penyosohan."
        )
    elif stok > cap * 0.9:
        peringatan = (
            f"⚠️ Tumpukan PK Gudang 1 {stok / 1000:g} ton dari {cap / 1000:g} ton "
            f"— sisa {(cap - stok) / 1000:g} ton."
        )
    return ProgressResult(
        proc=proc, berat_kumulatif=berat_kumulatif, rendemen_persen=rendemen,
        jenis=jenis, peringatan=peringatan,
    )


# ─────────────────────────── Selesai (auto-kosongkan silo) ───────────────────────────
@dataclass
class FinishResult:
    proc: MillingProcess
    nama_silo: str | None
    produced: float
    siap_kirim: float
    jenis: str | None = None  # KS / KL / MIX


async def finish_milling(
    db: AsyncSession, *, user, kode_proses: str | None, berat_akhir: float | None = None,
    tanggal=None, jam=None,
) -> FinishResult:
    """Tutup giling. Hasil akhir PK WAJIB — tanpa itu prosesnya tidak ditutup.

    Keputusan pemilik. Sebelumnya aksi ini hanya menutup prosesnya, jadi giling
    bisa berakhir tanpa satu pun angka hasil: PK-nya ada di lantai, tetapi tak
    ada yang tahu berapa. Lot itu lalu jatuh dari layar Stok, dan kelalaiannya
    tak punya satu tempat pun untuk kelihatan.

    Yang ditolak adalah PENUTUPANNYA, bukan pencatatannya. Prosesnya tak
    disentuh sama sekali sebelum angkanya ada, jadi kartunya tetap berada di
    Sedang berjalan — keadaan yang benar: mesinnya memang belum tuntas
    dilaporkan. Kartu yang hilang tanpa penjelasan lebih buruk daripada kartu
    yang bertahan sampai dilengkapi.

    Angkanya masuk sebagai progres KUMULATIF terakhir — catatan operator.
    Verifikasi admin (`berat_output_final_kg`) tetap langkah tersendiri, dan
    tetap menang atas angka ini bila kelak berbeda.
    """
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `LOT-20260702-01 selesai`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")

    # Diperiksa SEBELUM apa pun diubah. Kalau ditolak, prosesnya harus tetap
    # utuh berstatus "proses" — itulah yang membuat kartunya kembali sendiri.
    sudah = await _latest_progress(db, proc.id)
    if berat_akhir is None:
        if sudah is None:
            raise MillingError(
                "Sebutkan hasil akhir PK-nya dulu (kg). Giling tidak bisa "
                "ditutup tanpa angka hasil — PK-nya ada, dan yang tak tercatat "
                "tak akan muncul di Stok."
            )
        berat_akhir = sudah          # sudah pernah dicatat: pakai yang terakhir
    berat_akhir = float(berat_akhir)
    if berat_akhir <= 0:
        raise MillingError("Hasil akhir PK harus lebih dari nol.")
    masuk = float(proc.berat_gabah_masuk_kg or 0)
    if masuk and berat_akhir > masuk:
        raise MillingError(
            f"Hasil PK {berat_akhir:,.0f} kg lebih besar daripada gabah yang "
            f"masuk ({masuk:,.0f} kg). Periksa angkanya."
            .replace(",", ".")
        )

    now = input_time(tanggal, jam)
    if now < proc.waktu_mulai:
        raise MillingError(
            f"Tanggal selesai lebih awal dari mulai giling "
            f"({proc.waktu_mulai:%d-%m-%Y %H:%M})."
        )

    # Dicatat sebagai progres kumulatif, bukan kolom baru: `_produced_pk` sudah
    # membacanya, dan kolom kedua untuk fakta yang sama akan berselisih.
    if sudah is None or berat_akhir != sudah:
        db.add(MillingProgressLog(
            milling_process_id=proc.id, waktu_update=now,
            berat_kumulatif_kg=berat_akhir, input_by=user.id,
        ))
        await log_activity(
            db, table_name="milling_progress_logs", record_id=proc.id, action="INSERT",
            changed_by=user.id, new_value=f"hasil akhir {berat_akhir:.0f}kg",
        )
        await db.flush()

    proc.status = "selesai"
    proc.waktu_selesai = now

    # Silo dianggap kosong saat milling selesai (bukan saat gabah keluar fisik).
    #
    # Dikosongkan dari SELURUH sumbernya, bukan dari `proc.silo_storage_id`.
    # Penunjuk tunggal itu diisi `start_milling` dengan SALAH SATU baris silo
    # saja — "baris lot bila ada" — padahal satu giling boleh memakan beberapa
    # baris sekaligus sejak silo boleh dicampur. Baris yang tak ikut
    # dikosongkan tetap berstatus "terisi", dan silo yang isinya sudah habis
    # tergiling muncul kembali sebagai "Transit di silo kering": gabah yang
    # sama ditawarkan untuk digiling dua kali.
    nama_silo = None
    ids = [s for s in (await db.execute(
        select(MillingProcessSource.silo_storage_id).where(
            MillingProcessSource.milling_process_id == proc.id)
    )).scalars().all() if s]
    if not ids and proc.silo_storage_id:
        ids = [proc.silo_storage_id]      # proses lama, sebelum ada tabel sumber
    for sid in ids:
        st = await db.get(SiloStorage, sid)
        if st and st.status == "terisi":
            st.status = "kosong"
            st.tanggal_keluar = now
    if ids:
        silo = await db.get(Silo, proc.silo_id)
        if silo:
            silo.status = "kosong"
            nama_silo = silo.nama_silo.replace("Silo ", "")
    # Batch sumber berstatus digiling.
    if proc.drying_lot_id:
        bids = (
            await db.execute(
                select(DryingLotBatch.purchase_batch_id).where(
                    DryingLotBatch.drying_lot_id == proc.drying_lot_id
                )
            )
        ).scalars().all()
        for bid in bids:
            b = await db.get(PurchaseBatch, bid)
            if b:
                b.status_batch = "digiling"
    elif proc.purchase_batch_id:
        b = await db.get(PurchaseBatch, proc.purchase_batch_id)
        if b:
            b.status_batch = "digiling"

    bd = await _pk_breakdown(db, proc.id)
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="status", new_value="selesai",
    )
    jenis = await pk_jenis(db, proc)
    await db.commit()
    return FinishResult(
        proc=proc, nama_silo=nama_silo, produced=bd.produced, siap_kirim=bd.tersedia,
        jenis=jenis,
    )


# ─────────────────────────── Laporan ───────────────────────────
async def _latest_progress(db: AsyncSession, proc_id: int) -> float | None:
    v = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc_id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return float(v) if v is not None else None


async def _produced_pk(db: AsyncSession, proc_id: int) -> float:
    """PK dihasilkan. Angka TERVERIFIKASI menang atas progres operator.

    Progres kumulatif diketik operator sambil mesin jalan — ia perkiraan yang
    berguna selama proses, tetapi bukan angka final. Yang final ditetapkan
    admin di `milling_process_verifications.berat_output_final_kg`, dan itulah
    yang sudah dipakai HPP.

    Sebelumnya fungsi ini hanya membaca progres. Akibatnya: giling yang ditutup
    TANPA operator pernah mencatat hasilnya, lalu outputnya diverifikasi admin
    sebesar 6.300 kg, tetap berstok NOL — hilang dari layar Stok dan tak bisa
    dikirim ke Gudang 2. Angka yang sudah diverifikasi tetapi tak dipakai
    adalah pekerjaan verifikasi yang dibuang.
    """
    v = (await db.execute(
        select(MillingProcessVerification.berat_output_final_kg).where(
            MillingProcessVerification.milling_process_id == proc_id)
    )).scalars().first()
    if v is not None:
        return float(v)
    v = await _latest_progress(db, proc_id)
    return float(v) if v is not None else 0.0


async def _transferred_pk(db: AsyncSession, proc_id: int) -> float:
    """Total PK yang SUDAH dikirim (transfer) dari sebuah proses."""
    r = (
        await db.execute(
            select(func.coalesce(func.sum(InternalTransfer.berat_kg), 0)).where(
                InternalTransfer.milling_process_id == proc_id,
                InternalTransfer.status == "terkirim",
            )
        )
    ).scalar_one()
    return float(r)


@dataclass
class PkBreakdown:
    produced: float     # total PK dihasilkan (hasil yang di-update operator)
    transferred: float  # sudah dikirim ke Gudang 2
    tersedia: float     # siap kirim (stok) = produced - transferred


async def _sold_pk_langsung(db: AsyncSession, proc_id: int) -> float:
    """PK yang sudah dijual langsung dari Gudang 1 (barang keluar pk_langsung)."""
    from app.models import OutgoingItem
    r = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(
                OutgoingItem.item_type == "pk_langsung",
                OutgoingItem.milling_process_id == proc_id,
            )
        )
    ).scalar_one()
    return float(r)


async def _pk_breakdown(db: AsyncSession, proc_id: int) -> PkBreakdown:
    """Stok PK siap kirim = hasil − dikirim (transfer) − dijual langsung."""
    produced = await _produced_pk(db, proc_id)
    transferred = await _transferred_pk(db, proc_id)
    sold = await _sold_pk_langsung(db, proc_id)
    return PkBreakdown(produced, transferred, max(produced - transferred - sold, 0.0))


async def _milling_supplier_names(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Supplier asal bahan sebuah proses giling — dari SELURUH isinya.

    Dulu dibaca dari `proc.drying_lot_id`/`purchase_batch_id`, penunjuk tunggal
    peninggalan masa ketika satu silo hanya boleh berisi satu hal. Sejak silo
    boleh dicampur, penunjuk itu menyebut salah satu sumber dan mendiamkan
    sisanya: silo berisi pengeringan DAN gabah kering langsung akan melaporkan
    supplier yang pertama saja. Yang kedua hilang dari laporan tanpa jejak —
    padahal gabahnya ikut tergiling dan ikut dibayar.

    `sumber_batch` sudah menjawab pertanyaan yang sama untuk HPP; laporan
    memakai sumber yang sama supaya keduanya tak mungkin berselisih.
    """
    nama: list[str] = []
    for b, _harga, _lewat in await sumber_batch(db, proc):
        sup = await db.get(Supplier, b.supplier_id)
        if sup and sup.nama_supplier not in nama:
            nama.append(sup.nama_supplier)
    return nama


async def asal_isi(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Baris "asal-usul" satu lot giling: tiap sumber, tiap batch, tiap tiket.

    Inilah yang menjawab "beras ini dari gabah siapa" tanpa membuka basis
    data. Dikelompokkan per sumber karena itulah bentuk fisiknya: gabah yang
    dikeringkan bersama tak bisa lagi dipisahkan di dalam silo.
    """
    baris = list((await db.execute(
        select(MillingProcessSource)
        .where(MillingProcessSource.milling_process_id == proc.id)
        .order_by(MillingProcessSource.id)
    )).scalars().all())
    if not baris:
        return []

    # Kode tiket timbang milik aplikasi Timbangan — dibaca lewat SQL mentah di
    # basis data bersama. Kalau tabelnya tak ada (pemasangan tanpa timbangan),
    # asal-usulnya tetap tampil, hanya tanpa nomor tiket.
    async def kode_tiket(ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        try:
            rows = (await db.execute(
                text("SELECT id, kode FROM timbangan_transaksi WHERE id = ANY(:ids)"),
                {"ids": ids},
            )).all()
            return {r[0]: r[1] for r in rows}
        except Exception:
            return {}

    out: list[str] = []
    for s_ in baris:
        if s_.drying_lot_id:
            lot = await db.get(DryingLot, s_.drying_lot_id)
            judul = f"  ‣ {lot.kode_lot if lot else 'pengeringan'} · {_kg(float(s_.berat_kg))}"
            batches = list((await db.execute(
                select(PurchaseBatch)
                .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == s_.drying_lot_id)
                .order_by(PurchaseBatch.id)
            )).scalars().all())
        else:
            judul = f"  ‣ tanpa pengeringan · {_kg(float(s_.berat_kg))}"
            b = await db.get(PurchaseBatch, s_.purchase_batch_id)
            batches = [b] if b else []
        out.append(judul)
        tiket = await kode_tiket([b.timbangan_transaksi_id for b in batches
                                 if b.timbangan_transaksi_id])
        for b in batches:
            sup = await db.get(Supplier, b.supplier_id)
            tk = tiket.get(b.timbangan_transaksi_id or -1)
            out.append(
                f"     – {b.kode_batch} · {b.kondisi_gabah} "
                f"{_kg(float(b.berat_total_kg or 0))} · {sup.nama_supplier if sup else '-'}"
                + (f" · tiket {tk}" if tk else "")
            )
    return out


#: Kondisi gabah saat DIBELI → kelas PK yang keluar darinya.
KELAS_PK = {"basah": "KS", "kering": "KL"}

#: Lot yang bahannya dua-duanya. Bukan "campuran" — satu kata yang meringkas
#: dua asal-usul terbaca seperti nama varietas, dan yang membacanya akan
#: mencari gabah bernama itu.
KELAS_PK_CAMPUR = "MIX"


def kelas_pk(kondisi: list[str]) -> str | None:
    """KS / KL / MIX dari daftar kondisi beli bahannya. None bila tak diketahui."""
    kode = [KELAS_PK[k] for k in kondisi if k in KELAS_PK]
    if not kode:
        return None
    return kode[0] if len(set(kode)) == 1 else KELAS_PK_CAMPUR


async def _source_kondisi(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Kondisi beli gabah sumber proses — dari SELURUH isinya.

    Dulu dibaca dari `proc.drying_lot_id`/`purchase_batch_id`, penunjuk tunggal
    peninggalan masa ketika satu silo hanya boleh berisi satu hal, dengan
    catatan "satu lot tidak boleh campur basah & kering, jadi cukup satu batch
    sumber". Catatan itu tidak lagi benar: silo Gudang 1 boleh berisi gabah
    yang KAMI keringkan (dibeli basah) bersama gabah yang datang sudah kering.
    Keduanya sama-sama kering saat digiling — yang membedakan adalah kelas PK
    yang keluar, dan itu justru yang dijual.

    Akibat bentuk lama: lot bercampur mengaku KS saja, diam-diam, dan PK KL di
    dalamnya hilang dari laporan, dari transfer, dan dari catatan QC.

    `sumber_batch` sudah menjawab pertanyaan "apa isi proses ini" untuk HPP;
    di sini dipakai sumber yang sama supaya keduanya tak mungkin berselisih.
    """
    kondisi: list[str] = []
    for b, _harga, _lewat in await sumber_batch(db, proc):
        k = (b.kondisi_gabah or "").strip().lower()
        if k and k not in kondisi:
            kondisi.append(k)
    return [k for k in ("basah", "kering") if k in kondisi]


async def pk_jenis(db: AsyncSession, proc: MillingProcess) -> str | None:
    """Kelas PK hasil Gudang 1: KS (dari gabah basah), KL (kering), MIX (dua-duanya)."""
    return kelas_pk(await _source_kondisi(db, proc))


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_milling(db: AsyncSession, kode_proses: str | None = None) -> str:
    now = now_local()
    if kode_proses:
        proc = await get_process_by_kode(db, kode_proses)
        if proc is None:
            return f"Proses {kode_proses} tidak ditemukan."
        masuk = float(proc.berat_gabah_masuk_kg or 0)
        prog = await _latest_progress(db, proc.id)
        bd = await _pk_breakdown(db, proc.id)
        suppliers = await _milling_supplier_names(db, proc)
        nama = ", ".join(suppliers) if suppliers else "-"
        jenis = await pk_jenis(db, proc)
        jenis_lbl = f" ({jenis})" if jenis else ""
        lines = [
            f"⚙️ Giling {proc.kode_proses} — bahan dari {nama}",
            f"• Status: {proc.status}",
            f"• Jenis PK: {jenis or '-'}",
            f"• Gabah masuk: {_kg(masuk)}",
            f"• PK dihasilkan: {_kg(bd.produced)}{jenis_lbl}",
            f"• Siap kirim (stok): {_kg(bd.tersedia)}",
        ]
        asal = await asal_isi(db, proc)
        if asal:
            lines.append("• Asal gabah:")
            lines += asal
        if bd.transferred > 0:
            lines.append(f"• Sudah dikirim: {_kg(bd.transferred)}")
        r = hitung_rendemen(prog, proc.berat_gabah_masuk_kg)
        if r is not None:
            lines.append(f"• Rendemen sementara: {r:.1f}%")
        return "\n".join(lines)

    procs = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "proses").order_by(MillingProcess.id)
        )
    ).scalars().all()
    if not procs:
        return "⚙️ Tidak ada proses giling yang sedang berjalan."
    lines = [f"⚙️ Giling berjalan ({len(procs)} proses):"]
    for proc in procs:
        prog = await _latest_progress(db, proc.id)
        jam = (now - proc.waktu_mulai).total_seconds() / 3600
        jenis = await pk_jenis(db, proc)
        jlbl = f" {jenis}" if jenis else ""
        lines.append(
            f"• {proc.kode_proses}: PK{jlbl} {_kg(prog) if prog is not None else '0 kg'} — {jam:.1f} jam"
        )
    return "\n".join(lines)


async def stok_pk_gudang1(db: AsyncSession) -> str:
    """Stok PK siap kirim di Gudang 1 = hasil produksi tiap proses − yang sudah dikirim."""
    procs = (
        await db.execute(
            select(MillingProcess).order_by(MillingProcess.kode_proses)
        )
    ).scalars().all()
    items: list[tuple[str, str | None, PkBreakdown]] = []
    for proc in procs:
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia > 0:
            items.append((proc.kode_proses, await pk_jenis(db, proc), bd))
    if not items:
        return "📦 Stok PK Gudang 1 kosong."
    total = sum(bd.tersedia for _, _, bd in items)
    sub: dict[str, float] = {}
    for _, jenis, bd in items:
        sub[jenis or "?"] = sub.get(jenis or "?", 0.0) + bd.tersedia
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(sub.items()))
    lines = [f"📦 Stok PK siap kirim Gudang 1: {_kg(total)}  ({ringkas})"]
    for kode, jenis, bd in items:
        detail = f"• {jenis or '-'} dari {kode}: {_kg(bd.tersedia)}"
        if bd.transferred > 0:
            detail += f" (dari {_kg(bd.produced)}, terkirim {_kg(bd.transferred)})"
        lines.append(detail)
    return "\n".join(lines)


# ─────────────────────── QC & Verifikasi (staff/admin) ───────────────────────
@dataclass
class QcResult:
    proc: MillingProcess
    kadar_air: float | None
    broken: float | None
    susut: float | None
    kondisi: str | None
    qc_count: int


async def log_qc_milling(
    db: AsyncSession,
    *,
    user,
    kode_proses: str | None,
    kadar_air: float | None,
    broken: float | None,
    susut: float | None,
    kondisi: str | None,
) -> QcResult:
    if not kode_proses:
        raise MillingError(
            "Sebutkan kode proses, contoh: `QC LOT-20260702-01 kadar air 13 broken 5 kondisi KS`"
        )
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if all(v is None for v in (kadar_air, broken, susut)):
        raise MillingError("Sebutkan hasil QC-nya (kadar air / broken / susut).")
    # Jenis PK TIDAK diisi manual — ditentukan otomatis dari kondisi gabah
    # SELURUH sumbernya: basah → KS, kering → KL, dua-duanya → MIX. Input
    # manual diabaikan.
    kondisi = await pk_jenis(db, proc) or kondisi

    db.add(
        MillingQcLog(
            milling_process_id=proc.id,
            kadar_air=kadar_air,
            broken_persen=broken,
            susut_persen=susut,
            kondisi=kondisi,
            waktu=now_local(),
            input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="milling_qc_logs", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=f"ka={kadar_air} broken={broken} susut={susut} kondisi={kondisi}",
    )
    await db.commit()
    count = (
        await db.execute(
            select(func.count()).select_from(MillingQcLog).where(
                MillingQcLog.milling_process_id == proc.id
            )
        )
    ).scalar_one()
    return QcResult(
        proc=proc, kadar_air=kadar_air, broken=broken, susut=susut,
        kondisi=kondisi, qc_count=count,
    )


@dataclass
class VerifyOutputResult:
    proc: MillingProcess
    berat_output: float
    rendemen_persen: float | None
    re_verified: bool


async def verify_milling_output(
    db: AsyncSession, *, user, kode_proses: str | None, berat_output: float | None
) -> VerifyOutputResult:
    if not kode_proses:
        raise MillingError(
            "Sebutkan kode proses, contoh: `verifikasi output LOT-20260702-01 14 ton`"
        )
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if berat_output is None:
        raise MillingError("Sebutkan berat output PK final-nya, mis. `... 14 ton`.")

    verif = (
        await db.execute(
            select(MillingProcessVerification).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    re_verified = verif is not None
    if verif is None:
        verif = MillingProcessVerification(milling_process_id=proc.id)
        db.add(verif)
    verif.berat_output_final_kg = berat_output
    verif.verified_by = user.id
    verif.waktu_verifikasi = now_local()
    verif.status_verifikasi = "terverifikasi"

    await log_activity(
        db,
        table_name="milling_process_verifications",
        record_id=proc.id,
        action="UPDATE" if re_verified else "INSERT",
        changed_by=user.id,
        field_name="berat_output_final_kg",
        new_value=f"{berat_output:.0f}",
    )
    await db.commit()
    rendemen = hitung_rendemen(berat_output, proc.berat_gabah_masuk_kg)
    return VerifyOutputResult(
        proc=proc, berat_output=berat_output, rendemen_persen=rendemen, re_verified=re_verified
    )


async def sumber_batch(
    db: AsyncSession, proc: MillingProcess
) -> list[tuple[PurchaseBatch, float | None, bool]]:
    """Batch gabah yang benar-benar masuk sebuah proses giling.

    Kembalian: (batch, harga_per_kg | None, lewat_dryer).

    SATU tempat untuk pertanyaan "apa isi proses ini", dipakai HPP maupun
    analitik. Dulu keduanya menjawabnya sendiri-sendiri dari penunjuk tunggal
    di `MillingProcess`, dan jawaban itu hanya benar selama satu silo tak
    boleh dicampur. Begitu boleh, keduanya akan menghitung sebagian isi saja —
    dan pada HPP, "sebagian" berarti angka uang yang salah tanpa ada yang tahu.

    `lewat_dryer` ditentukan per batch, bukan per proses: satu silo bisa berisi
    gabah yang dikeringkan DAN gabah kering yang langsung masuk. Menagihkan
    satu tarif pengeringan untuk keduanya salah ke dua arah sekaligus.
    """
    baris = list((await db.execute(
        select(MillingProcessSource).where(
            MillingProcessSource.milling_process_id == proc.id
        )
    )).scalars().all())

    # Proses lama yang tak punya baris silo (sebelum penautan timbang) tidak
    # ikut terisi migrasi. Penunjuk tunggalnya masih satu-satunya yang ada.
    pasangan: list[tuple[int | None, int | None]] = (
        [(b.drying_lot_id, b.purchase_batch_id) for b in baris] if baris
        else [(proc.drying_lot_id, proc.purchase_batch_id)]
    )

    harga = dict((await db.execute(
        select(PurchaseBatchVerification.purchase_batch_id,
               PurchaseBatchVerification.harga_per_kg)
    )).all())

    hasil: list[tuple[PurchaseBatch, float | None, bool]] = []
    terlihat: set[int] = set()
    for lot_id, batch_id in pasangan:
        if lot_id:
            lot = await db.get(DryingLot, lot_id)
            lewat = lot is not None and lot.dryer_id is not None
            batches = (await db.execute(
                select(PurchaseBatch)
                .join(DryingLotBatch,
                      DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == lot_id)
            )).scalars().all()
        elif batch_id:
            lewat = False
            b = await db.get(PurchaseBatch, batch_id)
            batches = [b] if b else []
        else:
            continue
        for b in batches:
            if b.id in terlihat:      # satu batch tak boleh terhitung dua kali
                continue
            terlihat.add(b.id)
            h = harga.get(b.id)
            hasil.append((b, float(h) if h is not None else None, lewat))
    return hasil


async def resinkron_bahan_berjalan(db: AsyncSession) -> list[str]:
    """Samakan bahan giling YANG SEDANG BERJALAN dengan bobot batchnya sekarang.

    `berat_gabah_masuk_kg` dan `milling_process_sources.berat_kg` diambil
    sebagai cuplikan saat giling dimulai. Cuplikan itu benar pada detik itu —
    tetapi begitu timbangan membetulkan berat sebuah tiket, ia jadi salinan
    yang tak pernah dibaca ulang, dan salinan yang tak pernah dibaca ulang
    adalah cara paling umum dua aplikasi mulai berbeda tanpa ada yang
    menyadarinya.

    Akibatnya bukan satu angka meleset: `berat_gabah_masuk_kg` adalah penyebut
    rendemen. Bahan yang tercatat lebih kecil daripada yang sungguh masuk
    membuat rendemen terbaca melambung — dan yang melihatnya akan mencari
    sebabnya di mesin, bukan di catatan.

    Hanya proses yang masih `proses`. Yang sudah ditutup TIDAK disentuh:
    angkanya sudah masuk laporan dan sudah dipakai orang lain memutuskan,
    persis alasan yang sama dengan batas 48 jam pada pembatalan. Selisih yang
    baru ketahuan sesudah itu diperbaiki dengan catatan koreksi, bukan dengan
    menulis ulang yang lama.

    → daftar kode proses yang berubah (kosong = semuanya sudah cocok).
    """
    berubah: list[str] = []
    procs = (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
    )).scalars().all()
    for proc in procs:
        sumber = (await db.execute(
            select(MillingProcessSource).where(
                MillingProcessSource.milling_process_id == proc.id)
        )).scalars().all()
        if not sumber:
            continue
        total = 0.0
        ada_geser = False
        for src in sumber:
            st = await db.get(SiloStorage, src.silo_storage_id)
            if st is None:
                total += float(src.berat_kg or 0)
                continue
            kg = await _storage_kg(db, st)
            if float(src.berat_kg or 0) != kg:
                src.berat_kg = kg
                ada_geser = True
            total += kg
        if ada_geser or float(proc.berat_gabah_masuk_kg or 0) != total:
            lama = float(proc.berat_gabah_masuk_kg or 0)
            proc.berat_gabah_masuk_kg = total
            await log_activity(
                db, table_name="milling_process", record_id=proc.id,
                action="UPDATE", changed_by=proc.created_by,
                field_name="berat_gabah_masuk_kg",
                old_value=f"{lama:.0f}", new_value=f"{total:.0f}",
                alasan="bobot tiket direvisi di aplikasi timbangan",
            )
            berubah.append(proc.kode_proses)
    if berubah:
        await db.commit()
    return berubah
