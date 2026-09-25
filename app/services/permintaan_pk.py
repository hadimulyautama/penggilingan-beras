"""Permintaan operator Gudang 2 atas lot PK Gudang 1.

Keputusan pemilik 24 September 2026: operator polesan MELIHAT lot PK Gudang 1
(bahan bakunya) dan boleh MEMINTA satu lot dipindah; yang mencatat perpindahan
tetap Admin. Yang lahir di sini permintaan, bukan izin — `peran.can_transfer_pk`
tidak berubah sama sekali.

Kenapa perlu dicatat, bukan cukup ditelepon: yang lewat telepon tak pernah
tercatat, dan seminggu kemudian tak ada yang bisa menjawab "kenapa lot ini yang
dipindah". Dan Admin yang sedang di luar gudang tak punya cara tahu ada yang
menunggu bahan.

EMPAT LANGKAH, EMPAT TANGAN (keputusan pemilik 25 September 2026). Sampai hari
itu ini cuma PENGINGAT: Admin mengerjakan seluruhnya sendiri dalam satu
langkah, permintaannya menutup dirinya sendiri begitu transfer dicatat, dan
operator Gudang 1 tak pernah terlibat sama sekali.

  1 MINTA   operator G2  → `diminta`
  2 ACC     admin        → `disetujui` + TUJUAN dan BOBOT yang disetujui
  3 KIRIM   operator G1  → `dikirim`   ← DI SINI BARANGNYA BERPINDAH
  4 TUTUP   admin        → `selesai`   admin boleh mengubah bobotnya

DUA JALAN KELUAR YANG LAIN, dan keduanya harus ada — daftar yang tak pernah
habis adalah daftar yang berhenti dibaca:

  · Admin MENOLAK → `ditolak`, sebabnya WAJIB (CHECK di basis data)
  · lotnya habis lewat jalan lain (dijual, atau terkirim seluruhnya tanpa
    menyebut permintaannya) → `gugur`, ditutup saat kartunya disusun. Berlaku
    juga untuk yang SUDAH disetujui tetapi belum dieksekusi: kalau tidak,
    kartunya menggantung di antrean operator Gudang 1 atas lot yang sudah
    tak ada.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import MillingProcess, PermintaanPk
from app.models.permintaan import (DIKIRIM, DIMINTA, DISETUJUI, DITOLAK, GUGUR,
                                   HIDUP, SELESAI)


class PermintaanError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


@dataclass(frozen=True)
class Diminta:
    """Keadaan permintaan satu lot, untuk kartu di layar Stok operator.

    `status` ikut dibawa sejak 25 September 2026: yang meminta perlu tahu
    permintaannya sedang di tangan siapa. Sebelum itu ia menekan tombol lalu
    tak pernah diberi kabar lagi sampai barangnya muncul — atau tidak muncul.
    """

    id: int
    oleh: str
    sejak: object | None = None
    status: str = DIMINTA


async def _proses(db: AsyncSession, kode: str | None) -> MillingProcess:
    p = (await db.execute(select(MillingProcess).where(
        MillingProcess.kode_proses == (kode or "").strip()))).scalars().first()
    if p is None:
        raise PermintaanError(f"Lot {kode} tidak ditemukan.")
    return p


async def minta(db: AsyncSession, *, user, kode_proses: str | None) -> PermintaanPk:
    """Operator Gudang 2 meminta satu lot. Satu yang terbuka per lot.

    Pagarnya INDEKS, bukan pemeriksaan di depan: dua operator yang menekan pada
    detik yang sama sama-sama lolos pemeriksaan "sudah ada belum?" lalu keduanya
    menulis. Yang kalah menerima `IntegrityError`, dan itu diterjemahkan jadi
    kalimat yang menenangkan — bukan galat, sebab hasil akhirnya memang yang ia
    inginkan: lot itu sudah diminta.
    """
    from app.penggilingan.gudang1.services.milling import _pk_breakdown

    p = await _proses(db, kode_proses)
    # Lot yang sudah habis tak bisa diminta: permintaan atas barang yang tak ada
    # akan berdiri di layar Admin sampai seseorang menyadarinya. Sisanya dibaca
    # lewat `_pk_breakdown` — SATU jawaban untuk "berapa PK lot ini masih ada",
    # yang sama dengan yang dipakai layar Stok (hasil − dikirim − dijual).
    if (await _pk_breakdown(db, p.id)).tersedia <= 0:
        raise PermintaanError(
            f"Lot {p.kode_proses} sudah habis — tak ada PK tersisa untuk dipindah.")

    # Dipegang sebelum menulis: sesudah `rollback()` + `expunge_all()` di bawah,
    # `p` lepas dari sesi dan membaca atributnya akan memicu pemuatan ulang yang
    # gagal.
    kode, proses_id = p.kode_proses, p.id

    baris = PermintaanPk(milling_process_id=proses_id, diminta_oleh=user.id,
                         waktu_minta=now_local(), status=DIMINTA)
    db.add(baris)
    try:
        await db.commit()
    except IntegrityError:
        # `expunge_all` setelah rollback, dan itu BUKAN kerapian: baris yang
        # gagal tetap menggantung sebagai objek tertunda di sesi, dan kueri
        # berikutnya memicu autoflush yang mencoba menulisnya LAGI — galat yang
        # sama muncul dari baris yang kelihatannya cuma membaca.
        await db.rollback()
        db.expunge_all()
        if await terbuka_untuk(db, proses_id) is not None:
            raise PermintaanError(
                f"Lot {kode} sudah diminta dan masih menunggu Admin.") from None
        raise
    await db.refresh(baris)
    return baris


async def terbuka_untuk(db: AsyncSession, proses_id: int) -> PermintaanPk | None:
    """Permintaan yang masih BERJALAN atas lot ini — keadaan mana pun dari tiga."""
    return (await db.execute(select(PermintaanPk).where(
        PermintaanPk.milling_process_id == proses_id,
        PermintaanPk.status.in_(HIDUP)))).scalars().first()


async def diminta_peta(db: AsyncSession, proses_ids) -> dict[int, Diminta]:
    """proses_id → keadaan permintaannya yang terbuka. SATU kueri.

    Dipakai layar Stok operator: kartu yang sudah diminta tak menawarkan tombol
    "Minta lot ini" lagi — tombol yang ditekan dua kali karena layarnya tak
    berubah adalah tombol yang mengajari orang menekan dua kali.
    """
    from app.models import User

    ids = [int(x) for x in proses_ids]
    if not ids:
        return {}
    baris = (await db.execute(
        select(PermintaanPk, User.nama)
        .join(User, User.id == PermintaanPk.diminta_oleh)
        .where(PermintaanPk.milling_process_id.in_(ids),
               PermintaanPk.status.in_(HIDUP))
    )).all()
    return {r[0].milling_process_id: Diminta(id=r[0].id, oleh=r[1] or "?",
                                             sejak=r[0].waktu_minta,
                                             status=r[0].status)
            for r in baris}


async def tutup(db: AsyncSession, proses_id: int, *, status: str, user=None,
                sebab: str | None = None) -> int:
    """Tutup permintaan TERBUKA sebuah lot. → jumlah baris yang tertutup.

    Idempoten: memanggilnya untuk lot yang tak punya permintaan terbuka bukan
    kesalahan — ia memang sering dipanggil "kalau-kalau", dari jalur transfer
    yang tak tahu apakah lotnya pernah diminta.
    """
    r = await db.execute(
        update(PermintaanPk)
        .where(PermintaanPk.milling_process_id == proses_id,
               PermintaanPk.status.in_(HIDUP))
        .values(status=status, ditutup_oleh=(user.id if user is not None else None),
                waktu_tutup=now_local(), sebab=sebab))
    return r.rowcount or 0


async def _kunci(db: AsyncSession, permintaan_id: int, *, keadaan: str) -> PermintaanPk:
    """Ambil permintaan SAMBIL MENGUNCI barisnya, lalu pastikan keadaannya.

    `FOR UPDATE` bukan hiasan: dua admin yang menekan ACC pada detik yang sama
    sama-sama membaca "masih diminta", lalu keduanya menulis — dan yang kedua
    menimpa tujuan serta bobot yang sudah ditetapkan yang pertama. Sama untuk
    dua operator Gudang 1 yang menekan Kirim: yang kedua akan melahirkan
    perpindahan KEDUA atas PK yang sama.

    Yang kalah menunggu, membaca ulang, lalu menerima kalimat yang menyebut
    keadaan barunya — bukan galat mentah.
    """
    baris = (await db.execute(
        select(PermintaanPk).where(PermintaanPk.id == permintaan_id).with_for_update()
    )).scalars().first()
    if baris is None:
        raise PermintaanError("Permintaan itu sudah tidak ada.")
    if baris.status != keadaan:
        raise PermintaanError(_kalimat_keadaan(baris, keadaan))
    return baris


def _kalimat_keadaan(baris: PermintaanPk, diharap: str) -> str:
    """Kenapa langkah ini tak bisa dikerjakan — menyebut keadaan yang SEKARANG.

    "Permintaan itu sudah tidak terbuka" tak memberi tahu apa pun yang bisa
    ditindaklanjuti. Yang menekan perlu tahu ia terlambat oleh siapa, atau
    justru terlalu cepat.
    """
    kabar = {
        DIMINTA: "masih menunggu keputusan Admin",
        DISETUJUI: "sudah disetujui dan menunggu dikirim Gudang 1",
        DIKIRIM: "sudah dikirim dan menunggu ditutup Admin",
        SELESAI: "sudah selesai",
        DITOLAK: "sudah ditolak",
        GUGUR: "sudah gugur — lotnya habis lewat jalan lain",
    }.get(baris.status, baris.status)
    return f"Tidak bisa dikerjakan sekarang: permintaan ini {kabar}."


async def setujui(db: AsyncSession, *, user, permintaan_id: int,
                  tujuan: str | None, berat: float | None) -> PermintaanPk:
    """LANGKAH 2 — Admin menyetujui, sambil menetapkan TUJUAN dan BOBOT.

    Tujuannya ditetapkan DI SINI, bukan saat barangnya berangkat: yang tahu
    gudang mana yang sedang kosong adalah Admin, dan operator Gudang 1 yang
    memuat tak boleh disuruh menebaknya sambil berdiri di samping tumpukan.

    Bobotnya batas ATAS, bukan perintah: Gudang 1 boleh memuat kurang (karung
    terakhir tak penuh), tetapi tidak boleh lebih daripada yang disetujui.
    """
    from app.penggilingan.gudang1.services.milling import _pk_breakdown
    from app.penggilingan.gudang2.service import Gudang2Error, _tujuan_and_silo

    baris = await _kunci(db, permintaan_id, keadaan=DIMINTA)
    try:
        jenis, silo_id = await _tujuan_and_silo(db, tujuan)
    except Gudang2Error as e:
        raise PermintaanError(e.args[0] if e.args else "Tujuan tidak dikenali.") from None

    kg = float(berat or 0)
    if kg <= 0:
        raise PermintaanError("Sebutkan berapa kg yang disetujui.")
    tersedia = (await _pk_breakdown(db, baris.milling_process_id)).tersedia
    if kg > tersedia + 0.001:
        raise PermintaanError(
            f"Lot ini tinggal {tersedia:,.0f} kg — tak bisa menyetujui "
            f"{kg:,.0f} kg.".replace(",", "."))

    baris.status = DISETUJUI
    baris.tujuan, baris.silo_id = jenis, silo_id
    baris.berat_setuju_kg = kg
    baris.disetujui_oleh, baris.waktu_setuju = user.id, now_local()
    await db.commit()
    await db.refresh(baris)
    return baris


async def kirim(db: AsyncSession, *, user, permintaan_id: int,
                berat: float | None) -> PermintaanPk:
    """LANGKAH 3 — operator Gudang 1 memuat dan mengirim. BARANGNYA BERPINDAH.

    Perpindahannya lewat `services.transfer`, jalur yang sudah ada: dua
    peristiwa dalam satu transaksi, cermin `internal_transfers`, dan pemasukan
    di Gudang 2. Tabel permintaan tetap TIDAK menumpang buku besar — ia memuat
    niat, dan di sinilah niat bertemu barang, lewat satu kolom penyambung.

    Wewenangnya TIDAK datang dari peran: `can_transfer_pk` tak disentuh sama
    sekali. Yang memberi izin adalah BARIS INI — permintaan yang sudah
    disetujui Admin. Operator Gudang 1 tetap tak bisa memindahkan apa pun atas
    kehendaknya sendiri.
    """
    from app.services.transfer import TransferError, create_internal_transfer

    # ── DIREBUT dulu, baru barangnya berangkat ──
    #
    # `FOR UPDATE` saja TIDAK cukup di sini, dan itu ketahuan dari ujinya:
    # `create_internal_transfer` melakukan commit-nya sendiri, jadi kuncinya
    # terlepas SEBELUM status sempat berubah — dua operator Gudang 1 yang
    # menekan bersamaan sama-sama lolos, dan lahirlah DUA perpindahan atas PK
    # yang sama.
    #
    # Yang memutuskan karena itu satu `UPDATE` bersyarat: Postgres mengunci
    # barisnya lalu menguji ulang syaratnya sesudah kunci didapat, jadi yang
    # kedua menerima nol baris. Pola yang sama dengan klaim silo giling
    # (migrasi 0056).
    baris = await _kunci(db, permintaan_id, keadaan=DISETUJUI)
    kg = float(berat if berat is not None else (baris.berat_setuju_kg or 0))
    if kg <= 0:
        raise PermintaanError("Sebutkan berapa kg yang dimuat.")
    setuju = float(baris.berat_setuju_kg or 0)
    if setuju and kg > setuju + 0.001:
        # Lebih sedikit boleh — karung terakhir tak selalu penuh. Lebih banyak
        # tidak: yang disetujui Admin adalah batas, dan melewatinya berarti
        # memindahkan barang yang tak pernah disetujui siapa pun.
        raise PermintaanError(
            f"Yang disetujui {setuju:,.0f} kg — tak bisa mengirim {kg:,.0f} kg. "
            "Kirim sebanyak yang disetujui, atau mintakan persetujuan baru."
            .replace(",", "."))

    proc = await db.get(MillingProcess, baris.milling_process_id)
    # Tujuannya disebut dengan NAMA silonya: `create_internal_transfer`
    # menormalisasi sendiri lewat master (migrasi 0057).
    from app.penggilingan.gudang2.service import label_tujuan

    tujuan = await label_tujuan(db, baris.tujuan, baris.silo_id)
    lokasi = tujuan if baris.silo_id is not None else "ditumpuk"
    kode_proses = proc.kode_proses

    direbut = (await db.execute(
        update(PermintaanPk)
        .where(PermintaanPk.id == permintaan_id, PermintaanPk.status == DISETUJUI)
        .values(status=DIKIRIM, berat_kirim_kg=kg, dikirim_oleh=user.id,
                waktu_kirim=now_local())
    )).rowcount or 0
    await db.commit()
    if not direbut:
        raise PermintaanError(
            "Permintaan ini baru saja dikirim rekan Anda — barangnya sudah "
            "berangkat. Tak perlu dikirim dua kali.")

    try:
        r = await create_internal_transfer(
            db, user=user, kode_proses=kode_proses, lokasi_tujuan=lokasi, berat=kg)
    except TransferError as e:
        # Dikembalikan ke keadaan semula, DAN itu bukan kerapian: permintaan
        # yang tertinggal di `dikirim` tanpa perpindahan akan berdiri di meja
        # Admin menunggu ditutup atas barang yang tak pernah berangkat.
        await db.execute(
            update(PermintaanPk).where(PermintaanPk.id == permintaan_id)
            .values(status=DISETUJUI, berat_kirim_kg=None, dikirim_oleh=None,
                    waktu_kirim=None))
        await db.commit()
        raise PermintaanError(e.args[0] if e.args else "Gagal mengirim.") from None

    await db.execute(
        update(PermintaanPk).where(PermintaanPk.id == permintaan_id)
        .values(internal_transfer_id=r.transfer.id))
    await db.commit()
    return (await db.execute(select(PermintaanPk).where(
        PermintaanPk.id == permintaan_id))).scalars().one()


async def tutup_admin(db: AsyncSession, *, user, permintaan_id: int,
                      berat_final: float | None) -> tuple[PermintaanPk, str]:
    """LANGKAH 4 — Admin menutup, dan boleh membetulkan bobotnya.

    → (baris, kalimat tambahan bila ada koreksi)

    ⚠ BAGIAN PALING BERISIKO DARI SELURUH ALUR INI, dan sebabnya: barangnya
    SUDAH berpindah di langkah 3. Mengubah bobot di sini berarti mengubah
    perpindahan yang sudah tercatat — bukan menyunting satu kolom.

    Aturan repo ini sudah menamainya: "Pembatalan = peristiwa LAWAN
    (`membatalkan_id`), bukan penghapusan." Jadi koreksinya MEMBATALKAN
    transfer lamanya lalu mencatat yang baru pada bobot Admin, keduanya dalam
    SATU transaksi. Kalau `internal_transfers` di-UPDATE di tempat, stok kedua
    gudang bergeser tanpa satu baris pun di buku besar yang menjelaskan
    kenapa — dan `bangun_ulang_proyeksi` akan mengembalikan angka LAMA.

    Jalur pembatalannya yang SUDAH ADA dipakai apa adanya (`_undo_transfer`):
    ia sudah membatalkan kedua peristiwanya lewat penjaga hilir, dan ia sudah
    tahu cara menolak bila PK-nya terlanjur dipakai menyosoh. Bila begitu,
    penutupannya DITOLAK sambil menyebutkan sebabnya — bukan diam-diam
    membiarkan angkanya berbeda.

    `berat_kirim_kg` TIDAK ditimpa: selisih antara yang dimuat Gudang 1 dan
    yang diakui Admin justru itulah yang kelak perlu ditelusuri.
    """
    from app.services.transfer import TransferError, create_internal_transfer
    from app.services.undo import UndoError, _undo_transfer

    baris = await _kunci(db, permintaan_id, keadaan=DIKIRIM)
    dikirim = float(baris.berat_kirim_kg or 0)
    final = float(berat_final if berat_final is not None else dikirim)
    if final <= 0:
        raise PermintaanError("Berat akhir harus lebih dari nol.")

    catatan = ""
    if abs(final - dikirim) > 0.001:
        if baris.internal_transfer_id is None:
            raise PermintaanError(
                "Perpindahannya tak tertaut — bobotnya tak bisa dibetulkan dari "
                "sini. Mintakan koreksi lewat Batalkan input terakhir.")
        proc = await db.get(MillingProcess, baris.milling_process_id)
        from app.penggilingan.gudang2.service import label_tujuan

        tujuan = await label_tujuan(db, baris.tujuan, baris.silo_id)
        try:
            await _undo_transfer(db, baris.internal_transfer_id)
        except UndoError as e:
            raise PermintaanError(
                f"Bobotnya tak bisa dibetulkan: {e.args[0] if e.args else e}"
            ) from None
        try:
            r = await create_internal_transfer(
                db, user=user, kode_proses=proc.kode_proses,
                lokasi_tujuan=(tujuan if baris.silo_id is not None else "ditumpuk"),
                berat=final)
        except TransferError as e:
            raise PermintaanError(
                f"Koreksi ditolak: {e.args[0] if e.args else e}") from None
        baris.internal_transfer_id = r.transfer.id
        catatan = (f"Bobot dibetulkan {dikirim:,.0f} → {final:,.0f} kg "
                   f"(kiriman Gudang 1 tetap tercatat).".replace(",", "."))

    baris.status = SELESAI
    baris.berat_final_kg = final
    baris.ditutup_oleh, baris.waktu_tutup = user.id, now_local()
    baris.sebab = "Ditutup Admin."
    await db.commit()
    await db.refresh(baris)
    return baris, catatan


async def tolak(db: AsyncSession, *, user, permintaan_id: int, sebab: str) -> PermintaanPk:
    """Admin menolak. Sebabnya WAJIB — dan itu bukan formalitas.

    Permintaan yang lenyap tanpa kabar membuat operator menekannya lagi besok,
    dan Admin menolaknya lagi; keduanya mengira pihak satunya yang lalai.
    """
    sebab = (sebab or "").strip()
    if not sebab:
        raise PermintaanError(
            "Tulis sebabnya — permintaan yang hilang tanpa kabar akan diajukan lagi.")
    baris = await db.get(PermintaanPk, permintaan_id)
    if baris is None or baris.status != DIMINTA:
        raise PermintaanError(
            "Permintaan itu sudah tidak menunggu keputusan lagi.")
    baris.status = DITOLAK
    baris.ditutup_oleh = user.id
    baris.waktu_tutup = now_local()
    baris.sebab = sebab[:500]
    await db.commit()
    await db.refresh(baris)
    return baris


async def gugurkan_yang_habis(db: AsyncSession) -> int:
    """Tutup permintaan atas lot yang sudah habis lewat jalan lain.

    Lot bisa habis tanpa permintaannya pernah disebut: dijual langsung, atau
    dikirim sebagian-sebagian sampai nol. Kartunya harus ikut hilang — daftar
    yang memuat pekerjaan yang tak bisa dikerjakan lagi berhenti dibaca orang.

    Dipanggil saat kartu Admin disusun, bukan oleh poller: di situlah akibatnya
    langsung terlihat, dan tak ada jeda antara "kartunya hilang" dengan "sudah
    tak ada gunanya".
    """
    from app.penggilingan.gudang1.services.milling import pk_breakdown_banyak

    # Yang SUDAH DIKIRIM tak ikut digugurkan: barangnya sudah berpindah, dan
    # lot yang "habis" memang habis karena kiriman itu sendiri. Yang menggugur
    # sesudah barangnya jalan akan menghapus kartu penutupan milik Admin.
    terbuka = (await db.execute(select(PermintaanPk).where(
        PermintaanPk.status.in_((DIMINTA, DISETUJUI))))).scalars().all()
    if not terbuka:
        return 0
    # Satu kueri untuk semuanya: fungsi ini dipanggil tiap kali kartu Admin
    # disusun, yaitu di tiap halaman.
    rincian = await pk_breakdown_banyak(db, [b.milling_process_id for b in terbuka])
    n = 0
    for baris in terbuka:
        bd = rincian.get(baris.milling_process_id)
        if bd is None or bd.tersedia <= 0:
            baris.status = GUGUR
            baris.waktu_tutup = now_local()
            baris.sebab = "Lot habis sebelum permintaan dikerjakan."
            n += 1
    if n:
        await db.commit()
    return n


# `selesaikan()` DIHAPUS 25 September 2026. Ia menutup permintaan begitu
# transfernya dicatat — dan penutupan itu kini milik Admin, sebagai langkah
# keempat. Yang menggantikannya `tutup_admin` di atas.
