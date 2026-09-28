"""Logika bisnis pembelian gabah (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import input_time, now_local, tanggal_lokal
from app.models import PurchaseBatch, Supplier, User
from app.penggilingan.gudang1.services.timbang_link import bobot_awal_dari_tiket
from app.penggilingan.gudang1.services.timbang_link import (
    TiketSudahDipakai,
    ambil_tiket,
    kunci_tiket_untuk_ditaut,
)
from app.penggilingan.peta_jenis import intake_dari_jenis, is_gabah
from app.models.peristiwa import GABAH_MASUK
from app.services import peristiwa as buku
from app.services.activity_log import log_activity
from app.services.codegen import next_purchase_batch_code
from app.services.notification import create_notification




def _pesan_integritas(e: IntegrityError, tabel: str, kode: str) -> str:
    """Terjemahkan pelanggaran basis data jadi kalimat yang JUJUR.

    Dulu setiap `IntegrityError` di sini dilabeli "Tiket timbang ini sudah
    ditautkan ke batch lain" — apa pun sebabnya. Itu menutupi dua hal
    sekaligus. Pertama, tabrakan kode harian (P-K-01) muncul sebagai kalimat
    tentang tiket, sehingga operator mencari masalah di tempat yang salah
    seharian. Kedua, pelanggaran lain jadi tak terlihat sama sekali.

    Dibedakan menurut NAMA CONSTRAINT-nya, bukan menurut tebakan: hanya
    pelanggaran unik tautan tiket yang boleh berbunyi soal tiket.
    """
    nama = ""
    asli = getattr(e, "orig", None)
    for atribut in ("constraint_name", "diag"):
        nilai = getattr(asli, atribut, None)
        nama = nama or getattr(nilai, "constraint_name", None) or (
            nilai if isinstance(nilai, str) else "")
    nama = (nama or str(asli))[:200]

    if f"uq_{tabel}_timbangan" in nama or "timbangan_transaksi_id" in nama:
        return "Tiket timbang ini sudah ditautkan ke batch lain."
    if kode and kode in nama or "kode" in nama:
        return (f"Nomor {kode} ternyata sudah dipakai. Coba simpan sekali lagi — "
                "nomornya akan diterbitkan ulang.")
    return (f"Tersimpan gagal karena aturan basis data: {nama}. "
            "Sebutkan pesan ini ke admin bila berulang.")

async def find_or_create_supplier(db: AsyncSession, nama: str) -> tuple[Supplier, bool]:
    """Cari supplier aktif (case-insensitive). Kembalikan (supplier, dibuat_baru)."""
    nama = nama.strip()
    stmt = select(Supplier).where(
        func.lower(Supplier.nama_supplier) == nama.lower(),
        Supplier.deleted_at.is_(None),
    )
    supplier = (await db.execute(stmt)).scalars().first()
    if supplier:
        return supplier, False
    supplier = Supplier(nama_supplier=nama, status="aktif")
    try:
        # SAVEPOINT: tabrakan di sini tak boleh menggugurkan transaksi
        # pemanggil — kunci tiket yang sudah terpasang harus tetap terpasang.
        async with db.begin_nested():
            db.add(supplier)
            await db.flush()
    except IntegrityError:
        # ── Ada yang mendahului di antara "cari" dan "buat" ──
        #
        # Tiga penulis menyentuh tabel ini — jalur ini, sinkron kontak Kledo,
        # dan penyemai data uji — dan tak satu pun tahu tentang yang lain.
        # Indeks unik parsial (migrasi 0045) kini menolak yang kedua; di sini
        # penolakan itu diterjemahkan jadi "pakai yang sudah ada", bukan jadi
        # galat. Yang meminta memang cuma ingin pemasoknya, bukan barisnya.
        # Temuan QA X-20.
        supplier = (await db.execute(stmt)).scalars().first()
        if supplier is None:
            raise
        return supplier, False
    return supplier, True


async def count_batches_on(db: AsyncSession, tgl: date) -> int:
    stmt = (
        select(func.count())
        .select_from(PurchaseBatch)
        .where(PurchaseBatch.tanggal_pembelian == tgl)
    )
    return (await db.execute(stmt)).scalar_one()


@dataclass
class CreatedBatch:
    batch: PurchaseBatch
    supplier: Supplier
    supplier_created: bool


async def create_purchase_batch(
    db: AsyncSession,
    *,
    user: User,
    nama_supplier: str,
    berat_kg: float,
    kondisi_gabah: str,
    no_polisi_truk: str | None,
    kadar_air_awal_persen: float | None,
    tanggal: date | None = None,
    jam: time | None = None,
) -> CreatedBatch:
    """Buat batch pembelian gabah + audit + notifikasi verifikasi harga.

    `tanggal`/`jam` opsional untuk backdate (isi mundur); default sekarang.

    TIDAK ADA batas jumlah batch per hari. Dulu ada — tiga — dan pemilik
    menegaskan batas itu tak pernah ada dalam pekerjaannya: berapa truk yang
    datang hari itu ditentukan panen, bukan oleh aplikasi. Yang lebih buruk,
    batasnya menolak dengan melemparkan ANGKA-nya saja, jadi operator truk
    keempat berhenti bekerja di depan lembar galat bertuliskan "3".
    """
    now = input_time(tanggal, jam)  # BackdateError bila di masa depan

    supplier, created = await find_or_create_supplier(db, nama_supplier)

    hari = tanggal_lokal(now)
    kode = await next_purchase_batch_code(db, hari)
    batch = PurchaseBatch(
        kode_batch=kode,
        supplier_id=supplier.id,
        berat_total_kg=berat_kg,
        no_polisi_truk=no_polisi_truk,
        kondisi_gabah=kondisi_gabah,
        kadar_air_awal_persen=kadar_air_awal_persen,
        tanggal_pembelian=hari,
        waktu_pembelian=now,
        input_by=user.id,
        status_batch="baru",
        flag_unverified=True,
    )
    db.add(batch)
    await db.flush()

    await log_activity(
        db,
        table_name="purchase_batches",
        record_id=batch.id,
        action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {berat_kg:.0f}kg | {kondisi_gabah}",
    )
    # Kabar "menunggu verifikasi harga" DIBUANG 28 September 2026: harga keluar
    # dari Pos Produksi (keputusan pemilik), jadi tak ada lagi yang bisa
    # mengerjakannya di sini. Kabar yang menagih pekerjaan yang tak punya
    # pintu akan dibaca, ditekan, lalu diabaikan selamanya.

    await db.commit()
    await db.refresh(batch)
    return CreatedBatch(batch=batch, supplier=supplier, supplier_created=created)


async def create_purchase_batch_dari_timbang(
    db: AsyncSession,
    *,
    user: User,
    timbangan_transaksi_id: int,
    kadar_air_awal_persen: float | None = None,
    kondisi_gabah: str | None = None,
    tanggal: date | None = None,
    jam: time | None = None,
    kunci_kiriman: str | None = None,
) -> CreatedBatch:
    """Buat batch gabah DARI tiket TIMBANG (aplikasi terpisah, DB terintegrasi).

    Operator hanya memilih tiket; SUPPLIER, BOBOT, NOPOL diturunkan dari timbang (tak
    diinput ulang → cegah dobel). Bobot & `sumber_berat` ikut tiket: NOTA bila ada,
    selain itu REAL timbang. `timbangan_transaksi_id` UNIQUE → satu tiket satu batch.

    **Jalur PERISTIWA (Tahap 3, aksi pertama yang dipindahkan).** Satu
    transaksi: kunci tiket (FOR UPDATE) → pemeriksaan → nomor dari penghitung
    atomik → peristiwa `gabah_masuk` (kunci kiriman idempoten) → proyeksi
    `proyeksi_gabah_masuk` (constraint: satu tiket satu pencatatan hidup) →
    cermin `purchase_batches` untuk layar lama → jejak & notifikasi → commit.
    Gagal di mana pun = tak ada yang tersimpan, termasuk nomornya.

    `kunci_kiriman` dari klien (bila ada) membuat kiriman ulang mengembalikan
    batch yang sama; tanpa itu kuncinya diturunkan dari tiket dan urutan
    pencatatannya.
    """
    # Kunci dulu, baru baca. Urutannya penting: pemeriksaan "tiket ini sudah
    # dipakai?" yang dilakukan sebelum kunci terpasang selalu bisa disalip.
    try:
        await kunci_tiket_untuk_ditaut(db, timbangan_transaksi_id)
    except TiketSudahDipakai as e:
        raise ValueError(str(e))
    tiket = await ambil_tiket(db, timbangan_transaksi_id)
    if tiket is None:
        raise ValueError(
            "Tiket timbang tidak ditemukan atau sudah dibatalkan/ditutup paksa."
        )
    if tiket.get("arah") != "MASUK":
        raise ValueError("Tiket timbang bukan barang MASUK.")
    # Komoditasnya diperiksa DI SINI, bukan hanya di daftar pilihan mini-app.
    # Daftar itu memang sudah menyaring, tetapi ia hanya menentukan apa yang
    # mudah dipilih — bukan apa yang bisa dikirim. Tiket PK yang id-nya
    # dikirim ke jalur gabah dulu lolos utuh dan menjadi batch gabah.
    if not is_gabah(tiket.get("jenis_kode", "")):
        raise ValueError("Tiket ini bukan gabah masuk.")
    # Bobot boleh belum ada (batch dibuat saat bongkar). Referensi bobot = tiket:
    # nota bila ada, selain itu netto timbang. Kosong → status "menunggu bobot",
    # diisi otomatis oleh sinkronisasi saat tiket punya bobot (nota/timbang-2).
    # Tiga keadaan (QA P6, 21 September 2026): pasti / perkiraan dari tara
    # truk yang sama / tak diketahui. Lihat `bobot_awal_dari_tiket`.
    berat, sumber, berat_perkiraan = await bobot_awal_dari_tiket(db, tiket)
    ada_bobot = berat is not None

    # WAKTU KEDATANGAN DIAMBIL DARI TIKET, bukan dari saat operator mengetik.
    #
    # Truk ditimbang saat ia tiba; pencatatannya di produksi bisa menyusul
    # sejam kemudian — atau berhari-hari, pada tiket susulan. Memakai jam
    # ketik berarti laporan "jam kedatangan gabah" menggambarkan kebiasaan
    # mengetik, bukan kebiasaan truk datang, dan atas dasar itulah giliran
    # jaga diatur.
    #
    # `timbang1_waktu` = penimbangan pertama, yaitu truk masuk bermuatan.
    # Bila tiket tak punya (data lama), barulah jatuh ke jam sekarang.
    now = tiket.get("timbang1_waktu") or input_time(tanggal, jam)
    if tanggal or jam:            # operator menyebut waktunya sendiri — itu menang
        now = input_time(tanggal, jam)
    # Supplier: pakai yang tertaut di tiket bila ada; selain itu cari/buat dari nama pihak.
    if tiket.get("supplier_id"):
        supplier = await db.get(Supplier, tiket["supplier_id"])
        created = False
    else:
        nama = tiket.get("nama_supplier") or tiket.get("pihak_nama") or "Tanpa Nama"
        supplier, created = await find_or_create_supplier(db, nama)

    _info = intake_dari_jenis(tiket.get("jenis_kode", ""))
    kondisi = kondisi_gabah or (_info.kondisi if _info and _info.kondisi else "basah")
    # ── Tanggalnya tanggal JAKARTA, bukan tanggal UTC ──
    #
    # `now` di jalur ini datang dari basis data (`timbang1_waktu`), dan
    # asyncpg mengembalikan timestamptz sebagai datetime ber-UTC. Mengambil
    # `.date()` langsung memberi tanggal UTC: truk yang ditimbang 05:30 WIB
    # tanggal 11 dibukukan GB-20260910-01, sementara nota timbangnya
    # bertanggal 11 — dan rekap harian kedua sistem tak pernah cocok.
    hari = tanggal_lokal(now)

    # ── Kiriman ulang? Peristiwanya sudah ada → kembalikan batch yang sama ──
    if kunci_kiriman:
        ada = await _batch_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return CreatedBatch(batch=ada, supplier=supplier, supplier_created=False)
    else:
        urutan = await buku.jumlah_jenis(db, GABAH_MASUK, "timbangan_transaksi_id",
                                         timbangan_transaksi_id)
        kunci_kiriman = f"{GABAH_MASUK}:tiket:{timbangan_transaksi_id}:{urutan + 1}"

    kode = await next_purchase_batch_code(db, hari)
    muatan = {
        "kode_batch": kode, "timbangan_transaksi_id": timbangan_transaksi_id,
        "tiket_kode": tiket.get("kode"), "supplier_id": supplier.id,
        "nama_supplier": supplier.nama_supplier, "berat_kg": berat, "sumber_berat": sumber,
        "kondisi": kondisi, "no_polisi": tiket.get("nomor_polisi"),
        "kadar_air_awal_persen": kadar_air_awal_persen, "tanggal": hari, "waktu": now,
    }
    try:
        e = await buku.catat(db, jenis=GABAH_MASUK, pelaku_id=user.id, kunci_kiriman=kunci_kiriman,
                             muatan=muatan, waktu=now)
    except IntegrityError as e_:
        raise ValueError(_pesan_integritas(e_, "proyeksi_gabah_masuk", kode))
    if not e.baru:
        ada = await _batch_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return CreatedBatch(batch=ada, supplier=supplier, supplier_created=False)

    # Cermin untuk layar & laporan lama — bentuknya persis seperti sebelum
    # Tahap 3, ditambah penunjuk ke peristiwanya.
    batch = PurchaseBatch(
        kode_batch=kode,
        supplier_id=supplier.id,
        berat_total_kg=berat,  # None = menunggu bobot (disinkron dari tiket)
        no_polisi_truk=tiket.get("nomor_polisi"),
        kondisi_gabah=kondisi,
        kadar_air_awal_persen=kadar_air_awal_persen,
        tanggal_pembelian=hari,
        waktu_pembelian=now,
        input_by=user.id,
        status_batch="baru",
        flag_unverified=True,
        timbangan_transaksi_id=timbangan_transaksi_id,
        sumber_berat=sumber,
        berat_perkiraan_kg=berat_perkiraan,
        peristiwa_id=e.id,
    )
    db.add(batch)
    try:
        await db.flush()
    except IntegrityError as e_:
        await db.rollback()
        raise ValueError(_pesan_integritas(e_, "purchase_batches", kode))
    # Penunjuk cermin di proyeksi — objeknya sudah di tangan, tanpa kueri baru.
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "purchase_batch_id", batch.id)

    b_str = (f"{'± ' if sumber == 'perkiraan' else ''}{berat:.0f}kg ({sumber})"
             if ada_bobot else "menunggu bobot")
    await log_activity(
        db, table_name="purchase_batches", record_id=batch.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {b_str} | timbang {tiket['kode']}",
    )
    # Kabar "menunggu verifikasi harga" DIBUANG 28 September 2026: harga keluar
    # dari Pos Produksi (keputusan pemilik), jadi tak ada lagi yang bisa
    # mengerjakannya di sini. Kabar yang menagih pekerjaan yang tak punya
    # pintu akan dibaca, ditekan, lalu diabaikan selamanya.

    await db.commit()
    await db.refresh(batch)
    return CreatedBatch(batch=batch, supplier=supplier, supplier_created=created)


async def _batch_dari_kunci(db: AsyncSession, kunci_kiriman: str) -> PurchaseBatch | None:
    """Cermin batch dari peristiwa berkunci ini — untuk kiriman ulang."""
    from app.models import Peristiwa

    return (await db.execute(
        select(PurchaseBatch).join(Peristiwa, Peristiwa.id == PurchaseBatch.peristiwa_id)
        .where(Peristiwa.kunci_kiriman == kunci_kiriman)
    )).scalars().first()


async def undo_purchase_batch(db: AsyncSession, *, batch_id: int, user: User) -> bool:
    """Batalkan batch dalam jendela waktu (default 15 menit) bila belum diproses.

    Kembalikan True jika berhasil dibatalkan.
    """
    batch = await db.get(PurchaseBatch, batch_id)
    if batch is None:
        return False

    window = timedelta(minutes=settings.undo_window_minutes)
    if now_local() - batch.waktu_pembelian > window:
        return False
    if batch.status_batch != "baru":
        return False  # sudah ada transaksi lanjutan (mis. masuk lot/silo)

    await log_activity(
        db,
        table_name="purchase_batches",
        record_id=batch.id,
        action="DELETE",
        changed_by=user.id,
        old_value=batch.kode_batch,
        alasan="Dibatalkan operator dalam jendela undo",
    )
    await db.delete(batch)
    await db.commit()
    return True
