"""Daftar audit — siapa mencatat apa, jam berapa.

Laporan menjawab "berapa"; audit menjawab "siapa mencatat apa, jam berapa" —
dan itu pertanyaan yang muncul justru saat angkanya tidak masuk akal. Isinya
sudah lama ada di `activity_logs`; yang belum ada adalah cara membacanya
tanpa membuka basis data.

**Batas 48 jam bukan sekadar saringan tampilan — itu batas MENGUBAH.**
Catatan yang lebih tua tak bisa dibatalkan lagi. Sebabnya sederhana: angka
hari kemarin sudah masuk laporan dan sudah dipakai orang lain memutuskan;
membiarkannya berubah berarti laporan yang sama bisa berbeda isinya tiap kali
dibuka. Salah yang baru ketahuan setelah lewat diperbaiki dengan catatan
koreksi baru, bukan dengan mengubah yang lama.

Karena batas itu sama dengan saringan bawaannya, yang pertama dilihat orang
persis sama dengan yang masih bisa ia perbaiki.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import ActivityLog, User
from app.services.undo import BATAS_UNDO, _UNDOABLE, label_tabel

#: Lewat ini, catatan terkunci. Diambil dari `undo` supaya batas yang
#: DITEGAKKAN dan batas yang DITAMPILKAN tak pernah berbeda — dua angka untuk
#: satu aturan cepat atau lambat berselisih, dan yang salah adalah yang lebih
#: jarang dibaca orang.
BATAS_UBAH = BATAS_UNDO

#: (kunci, label, rentang). None = tanpa batas.
RENTANG = (
    ("48j", "48 jam terakhir", BATAS_UBAH),
    ("24j", "24 jam", timedelta(hours=24)),
    ("semua", "Semua", None),
)

#: Kelompok proses → tabel yang termasuk di dalamnya. Operator tak berpikir
#: dalam nama tabel; ia berpikir "gabah masuk" dan "giling".
KELOMPOK = (
    ("semua", "Semua", None),
    ("masuk", "Gabah masuk", ("purchase_batches", "pk_purchase_batches",
                              "pk_gudang2_intakes")),
    ("kering", "Pengeringan", ("drying_lots", "drying_moisture_logs",
                               "drying_cooling_logs", "silo_storage",
                               "silo_moving_logs")),
    ("giling", "Giling", ("milling_process", "milling_progress_logs",
                          "milling_qc_logs", "milling_process_verifications")),
    ("berhenti", "Berhenti", ("jeda_proses", "jeda_catatan")),
)
_TABEL = {k: t for k, _, t in KELOMPOK}


@dataclass
class Catatan:
    id: int
    waktu: datetime
    tabel: str
    label: str
    aksi: str
    ringkas: str
    oleh: str
    #: Masih di dalam 48 jam — dan karena itu masih mungkin dibatalkan.
    muda: bool
    #: Jenis tindakannya memang didukung undo. Muda saja tak cukup.
    bisa_batal: bool
    dibatalkan: bool = False


async def daftar(
    db: AsyncSession, *, rentang: str = "48j", kelompok: str = "semua",
    cari: str = "", batas: int = 200, customer_predicate=None,
) -> tuple[list[Catatan], int]:
    """Catatan terbaru lebih dulu. Kembalikan (yang tampil, jumlah seluruhnya)."""
    kini = now_local()
    q = select(ActivityLog).order_by(ActivityLog.id.desc())

    # Jejak undo sendiri tak ditampilkan: yang dicari orang adalah apa yang
    # DICATAT, dan baris "undo" cuma menggandakan cerita yang sama dari sisi
    # lain — sementara akibatnya sudah terlihat pada catatan yang dibatalkan.
    q = q.where(ActivityLog.table_name != "undo")

    if customer_predicate is not None:
        q = q.where(customer_predicate)

    delta = next((d for k, _, d in RENTANG if k == rentang), BATAS_UBAH)
    if delta is not None:
        q = q.where(ActivityLog.waktu_perubahan >= kini - delta)

    tabel = _TABEL.get(kelompok)
    if tabel:
        q = q.where(ActivityLog.table_name.in_(tabel))

    cari = (cari or "").strip()
    if cari:
        pola = f"%{cari}%"
        q = q.where(or_(ActivityLog.new_value.ilike(pola),
                        ActivityLog.old_value.ilike(pola),
                        ActivityLog.table_name.ilike(pola)))

    baris = (await db.execute(q.limit(batas))).scalars().all()

    # ── Dihitung di SQL, bukan di memori ──
    #
    # Dulu: seluruh id tabel audit ditarik ke Python hanya untuk diukur
    # panjangnya. Tabel itulah yang paling cepat tumbuh di aplikasi ini —
    # tiap pencatatan menambah satu baris — jadi biayanya naik terus tanpa
    # ada yang menyadarinya sampai layar audit berhenti bisa dibuka.
    # Temuan QA P-S-08.
    total_query = select(func.count(ActivityLog.id)).where(ActivityLog.table_name != "undo")
    if customer_predicate is not None:total_query=total_query.where(customer_predicate)
    semua = (await db.execute(total_query)).scalar_one()

    # Nama hanya untuk pelaku yang benar-benar MUNCUL di halaman ini, bukan
    # seluruh isi tabel orang.
    pelaku = {log.changed_by for log in baris if log.changed_by}
    nama = {
        u.id: u.nama
        for u in (await db.execute(
            select(User).where(User.id.in_(pelaku)) if pelaku
            else select(User).where(User.id.is_(None))
        )).scalars().all()
    }
    keluar = []
    for log in baris:
        ringkas = (log.new_value or log.old_value or "").strip() or f"#{log.record_id}"
        muda = (kini - log.waktu_perubahan) < BATAS_UBAH
        keluar.append(Catatan(
            id=log.id, waktu=log.waktu_perubahan, tabel=log.table_name,
            label=label_tabel(log.table_name), aksi=log.action,
            ringkas=ringkas.split("|")[0].strip()[:110],
            oleh=nama.get(log.changed_by or 0) or "—",
            muda=muda, bisa_batal=muda and log.table_name in _UNDOABLE and log.dibatalkan_pada is None,
            dibatalkan=log.dibatalkan_pada is not None,
        ))
    return keluar, semua
