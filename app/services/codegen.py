"""Generator kode transaksi berurutan per hari, mis. GB-YYYYMMDD-NN.

Prinsip dokumen: semua kode di-generate otomatis oleh sistem.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    KodeUrut,
    BerasKeSilo,
    BrokenKeSilo,
    DryingLot,
    GabahKeringBongkar,
    GabahKeringLot,
    InternalTransfer,
    MillingProcess,
    OutgoingRecord,
    PackagingPurchase,
    PkPurchaseBatch,
    PkRejection,
    PkTumpukanToSilo,
    PolishingProcess,
    PurchaseBatch,
)


async def _next_sequence(db: AsyncSession, prefix: str, count_stmt=None,
                        tgl: date | None = None) -> str:
    """Bentuk kode PREFIX-YYYYMMDD-NN dari penghitung ATOMIK.

    Dulu dari `jumlah baris hari itu + 1`, dan itu salah dua kali:

    **Undo menghapus baris.** Sesudah GB-01 dibatalkan, hitungannya kembali
    nol, jadi truk berikutnya menghitung GB-02 — yang sudah ada — lalu ditolak
    basis data. Dan tetap ditolak SEPANJANG HARI, karena tiap percobaan
    menghitung angka yang sama. Operator membaca "Tiket timbang ini sudah
    ditautkan ke batch lain", pesan yang tak menyebut sebabnya sama sekali.

    **Dua operator bersamaan** menghitung angka yang sama sebelum salah
    satunya menyimpan.

    Penghitungnya diambil dalam transaksi yang SAMA dengan penyisipan
    barisnya, jadi nomor yang sudah terbit tak bisa terbit lagi meski
    barisnya kemudian dibatalkan. Nomor boleh melompat; nomor yang muncul dua
    kali lebih membingungkan daripada nomor yang bolong.

    `count_stmt` masih diterima tetapi TAK DIPAKAI — pemanggilnya banyak dan
    semuanya menyusunnya, jadi membuangnya sekaligus berarti sepuluh
    perubahan yang tak menambah apa pun. Ia hilang sendiri saat tiap
    pemanggil berikutnya disentuh.
    """
    tgl = tgl or now_local().date()
    seq = await _ambil_urut(db, prefix, tgl)
    return f"{prefix}-{tgl:%Y%m%d}-{seq:02d}"


async def _ambil_urut(db: AsyncSession, awalan: str, tgl: date) -> int:
    """Nomor berikutnya untuk awalan & tanggal ini — satu perintah, atomik."""
    dialek = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialek == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert

    perintah = (
        _insert(KodeUrut)
        .values(awalan=awalan, tanggal=tgl, n=1)
        .on_conflict_do_update(
            index_elements=["awalan", "tanggal"],
            set_={"n": KodeUrut.n + 1},
        )
        .returning(KodeUrut.n)
    )
    return (await db.execute(perintah)).scalar_one()


async def next_purchase_batch_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode batch pembelian gabah: GB-YYYYMMDD-NN (reset per hari).

    `tgl` untuk backdate: kode & urutan mengikuti tanggal kejadian.
    """
    tgl = tgl or now_local().date()
    stmt = (
        select(func.count())
        .select_from(PurchaseBatch)
        .where(PurchaseBatch.tanggal_pembelian == tgl)
    )
    return await _next_sequence(db, "GB", stmt, tgl)


async def next_drying_lot_code(db: AsyncSession) -> str:
    """Kode pengeringan: PGR-YYYYMMDD-NN (reset per hari).

    Dulu berawalan LOT-, dari masa ketika satu tabel dipaksa berarti dua hal:
    muatan yang dikeringkan bersama, DAN yang digiling bersama. Sejak silo
    boleh dicampur, keduanya berpisah — dan pemilik memutuskan "lot" dipakai
    HANYA untuk giling. Pengeringan punya namanya sendiri."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(DryingLot)
        .where(DryingLot.created_at >= start)
    )
    return await _next_sequence(db, "PGR", stmt)


async def next_milling_code(db: AsyncSession) -> str:
    """Kode lot giling: LOT-YYYYMMDD-NN (reset per hari).

    LOT- di sini, karena inilah lot yang sesungguhnya: terbentuk saat giling
    dimulai, dari seluruh isi silo. Dulu MIL-."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(MillingProcess)
        .where(MillingProcess.created_at >= start)
    )
    return await _next_sequence(db, "LOT", stmt)


async def next_transfer_code(db: AsyncSession) -> str:
    """Kode transfer internal: TRF-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(InternalTransfer)
        .where(InternalTransfer.created_at >= start)
    )
    return await _next_sequence(db, "TRF", stmt)


async def next_pk_purchase_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode beli PK luar (Gudang 2): PKB-YYYYMMDD-NN (reset per hari).

    `tgl` untuk backdate: kode & urutan mengikuti tanggal kejadian.
    """
    tgl = tgl or now_local().date()
    stmt = (
        select(func.count())
        .select_from(PkPurchaseBatch)
        .where(PkPurchaseBatch.tanggal_pembelian == tgl)
    )
    return await _next_sequence(db, "PKB", stmt, tgl)


async def next_rejection_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode PK ditolak & dikembalikan (Gudang 2): REJ-YYYYMMDD-NN (reset per hari)."""
    tgl = tgl or now_local().date()
    stmt = (
        select(func.count())
        .select_from(PkRejection)
        .where(PkRejection.tanggal == tgl)
    )
    return await _next_sequence(db, "REJ", stmt, tgl)


async def next_tumpukan_move_code(db: AsyncSession) -> str:
    """Kode pindah tumpukan→silo (Gudang 2): PTS-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(PkTumpukanToSilo)
        .where(PkTumpukanToSilo.created_at >= start)
    )
    return await _next_sequence(db, "PTS", stmt)


async def next_broken_move_code(db: AsyncSession) -> str:
    """Kode pindah broken→silo (Gudang 2): BKS-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(BrokenKeSilo)
        .where(BrokenKeSilo.created_at >= start)
    )
    return await _next_sequence(db, "BKS", stmt)


async def next_beras_move_code(db: AsyncSession) -> str:
    """Kode pindah beras→silo (Gudang 2): BRS-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(BerasKeSilo)
        .where(BerasKeSilo.created_at >= start)
    )
    return await _next_sequence(db, "BRS", stmt)


async def next_gabah_kering_code(db: AsyncSession) -> str:
    """Kode lot gabah kering dikemas+ditimbang (Gudang 1): GKR-YYYYMMDD-NN
    (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(GabahKeringLot)
        .where(GabahKeringLot.created_at >= start)
    )
    return await _next_sequence(db, "GKR", stmt)


async def next_gabah_kering_bongkar_code(db: AsyncSession) -> str:
    """Kode bongkar gabah kering→silo (Gudang 1): GKS-YYYYMMDD-NN (reset per
    hari) — sebangun `next_broken_move_code`/`next_tumpukan_move_code`."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(GabahKeringBongkar)
        .where(GabahKeringBongkar.created_at >= start)
    )
    return await _next_sequence(db, "GKS", stmt)


async def next_polishing_code(db: AsyncSession) -> str:
    """Kode proses penyosohan (Gudang 2): POL-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(PolishingProcess)
        .where(PolishingProcess.created_at >= start)
    )
    return await _next_sequence(db, "POL", stmt)


async def next_packaging_purchase_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode pembelian kemasan: PKP-YYYYMMDD-NN (reset per hari)."""
    tgl = tgl or now_local().date()
    stmt = (
        select(func.count())
        .select_from(PackagingPurchase)
        .where(PackagingPurchase.tanggal == tgl)
    )
    return await _next_sequence(db, "PKP", stmt, tgl)


async def next_outgoing_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode barang keluar: OUT-YYYYMMDD-NN (reset per hari)."""
    tgl = tgl or now_local().date()
    stmt = (
        select(func.count())
        .select_from(OutgoingRecord)
        .where(OutgoingRecord.tanggal == tgl)
    )
    return await _next_sequence(db, "OUT", stmt, tgl)


async def next_jasa_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode pesanan jasa: JAS-YYMM-NNN — reset per BULAN, tiga angka.

    Satu-satunya kode di app ini yang tidak harian, dan bentuknya mengikuti apa
    yang dihitungnya. `GB`/`LOT`/`PGR` menghitung TRUK dan MUATAN: beberapa
    sehari, dan tanggal lengkap di kodenya membuat "gabah tanggal berapa"
    terbaca tanpa membuka apa pun. Pesanan jasa bukan muatan — ia PEKERJAAN,
    satu pesanan bisa menerima enam truk selama dua minggu, dan tanggal
    kedatangan truk pertama bukan fakta yang pantas jadi identitasnya.

    Penghitungnya tetap `kode_urut` yang sama dan tetap ATOMIK — yang berbeda
    hanya kuncinya: tanggal 1 bulan itu, bukan hari ini. Tiga angka karena
    `NN` dua angka akan mentok di pesanan ke-100 dalam sebulan, dan kode yang
    mentok akan ditolak basis data sepanjang sisa bulan itu tanpa menyebut
    sebabnya (jebakan yang sama sudah pernah dijalani penghitung harian —
    lihat catatan pada `_next_sequence`).

    TIDAK lewat `_next_sequence`: fungsi itu merakit `PREFIX-YYYYMMDD-NN`, dan
    menambahkan cabang format di dalamnya berarti satu fungsi yang melayani dua
    bentuk — lalu pemanggil berikutnya mendapat bentuk yang bukan yang ia kira.
    """
    tgl = tgl or now_local().date()
    awal_bulan = tgl.replace(day=1)
    seq = await _ambil_urut(db, "JAS", awal_bulan)
    return f"JAS-{tgl:%y%m}-{seq:03d}"
