"""Permintaan operator Gudang 2 atas lot PK Gudang 1.

Keputusan pemilik 24 September 2026: operator polesan MELIHAT lot PK Gudang 1
(bahan bakunya) dan boleh MEMINTA satu lot dipindah; yang mencatat perpindahan
tetap Admin. Yang lahir di sini permintaan, bukan izin — `peran.can_transfer_pk`
tidak berubah sama sekali.

Kenapa perlu dicatat, bukan cukup ditelepon: yang lewat telepon tak pernah
tercatat, dan seminggu kemudian tak ada yang bisa menjawab "kenapa lot ini yang
dipindah". Dan Admin yang sedang di luar gudang tak punya cara tahu ada yang
menunggu bahan.

TIGA KEADAAN YANG MENUTUPNYA, dan ketiganya harus ada — daftar yang tak pernah
habis adalah daftar yang berhenti dibaca:

  · transfernya DICATAT      → `selesai` (ditutup `services.transfer`)
  · Admin MENOLAK            → `ditolak`, sebabnya WAJIB (CHECK di basis data)
  · lotnya habis lewat jalan lain (dijual, atau terkirim seluruhnya tanpa
    menyebut permintaannya) → `gugur`, ditutup saat kartunya disusun
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import MillingProcess, PermintaanPk
from app.models.permintaan import DITOLAK, GUGUR, SELESAI, TERBUKA


class PermintaanError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


@dataclass(frozen=True)
class Diminta:
    """Keadaan permintaan satu lot, untuk kartu di layar Stok operator."""

    id: int
    oleh: str
    sejak: object | None = None


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
                         waktu_minta=now_local(), status=TERBUKA)
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
    return (await db.execute(select(PermintaanPk).where(
        PermintaanPk.milling_process_id == proses_id,
        PermintaanPk.status == TERBUKA))).scalars().first()


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
               PermintaanPk.status == TERBUKA)
    )).all()
    return {r[0].milling_process_id: Diminta(id=r[0].id, oleh=r[1] or "?",
                                             sejak=r[0].waktu_minta)
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
               PermintaanPk.status == TERBUKA)
        .values(status=status, ditutup_oleh=(user.id if user is not None else None),
                waktu_tutup=now_local(), sebab=sebab))
    return r.rowcount or 0


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
    if baris is None or baris.status != TERBUKA:
        raise PermintaanError("Permintaan itu sudah tidak terbuka lagi.")
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

    terbuka = (await db.execute(select(PermintaanPk).where(
        PermintaanPk.status == TERBUKA))).scalars().all()
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


#: Dipakai `services.transfer` saat transfernya benar-benar dicatat.
async def selesaikan(db: AsyncSession, proses_id: int, *, user) -> int:
    return await tutup(db, proses_id, status=SELESAI, user=user,
                       sebab="Transfer dicatat.")
