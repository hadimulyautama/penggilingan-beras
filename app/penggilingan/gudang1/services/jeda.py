"""Menghentikan proses sementara — dan mencatat SEBABNYA.

Mesin berhenti di tengah jalan adalah kejadian sehari-hari. Sebelum ada
tempat untuk itu, operator hanya punya dua pilihan yang sama-sama merusak
catatan: membiarkan prosesnya "berjalan" padahal mesinnya mati, atau
menutupnya lalu memulai proses baru — yang membuat satu muatan gabah
terhitung dua kali.

Dua hal yang dijaga di sini:

  · **Jam berjalan dipisah dari jam tertahan.** Pengeringan 9 jam yang 4 jam
    di antaranya menunggu bahan bakar bukan pengeringan 9 jam. Menjumlahkan
    keduanya menyembunyikan satu-satunya angka yang bisa diperbaiki.

  · **Sebabnya wajib.** Yang ditanyakan saat hasil sehari sedikit selalu
    "kenapa", dan sebab yang tak dicatat akan dikarang berminggu-minggu
    kemudian. Daftarnya tak akan pernah lengkap, jadi ada jalan menulis
    sendiri — sebab yang berulang muncul di situ memang layak naik jadi
    pilihan tetap.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import DryingLot, JedaProses, JedaCatatan, MillingProcess
from app.penggilingan.gudang2.models import PolishingProcess
from app.services.activity_log import log_activity

from hmu_identitas.peran import G1, G2


class JedaError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


#: Sebab BAWAAN. Yang dipakai layar & borang dibaca lewat
#: `app.services.setelan.sebab_jeda`, karena daftarnya memang bertambah di
#: lapangan — kotak "Lainnya, tulis sendiri" adalah katupnya, dan sebab yang
#: berulang muncul di situ layak naik jadi pilihan tetap.
#:
#: Urutannya: yang menghentikan MESIN lebih dulu, lalu
#: yang menghentikan PEKERJAAN. "Mesin giling rusak" dan "mesin pendukung
#: rusak" sengaja dipisah — sebab yang ambigu tak bisa dipakai menghitung
#: apa pun, dan "mesin rusak" saja jadi ambigu begitu ada mesin pendukung.
SEBAB = {
    "pengeringan": ("Listrik padam", "Mesin dryer rusak", "Mesin pendukung rusak",
                    "Bahan bakar habis", "Jam kerja habis"),
    "giling": ("Mesin giling rusak", "Mesin pendukung rusak",
               "Limbah produksi penuh", "Listrik padam", "Jam kerja habis"),
    # Penyosohan Gudang 2 — sejak 12 September 2026 (keputusan pemilik saat
    # aplikasi operator Gudang 2 dirancang). Mesin sosoh tak kehabisan bahan
    # bakar dan limbahnya bukan yang menghentikan; polanya tetap: mesin dulu,
    # lalu pekerjaan.
    "penyosohan": ("Mesin sosoh rusak", "Mesin pendukung rusak",
                   "Listrik padam", "Jam kerja habis"),
}
#: Katup untuk sebab yang belum ada di daftar. Daftar yang tak lengkap memaksa
#: orang memilih yang paling mirip — lalu angkanya berbohong dengan rapi.
SEBAB_LAIN = "Lainnya"

#: Nama proses untuk layar, dan GUDANG pemiliknya — di sini, bersebelahan dengan
#: `SEBAB`, supaya proses keempat cukup didaftar sekali.
#:
#: Layar Pengaturan memakai keduanya: ia menawarkan blok sebab berhenti hanya
#: untuk proses milik gudang yang dipegang pembacanya. Sampai 24 September 2026
#: daftar itu ditulis ulang di dua tempat — dua tuple `PROSES` yang diketik
#: tangan, satu di Pos Produksi (dua proses) dan satu di Meja (tiga) — dan yang
#: pendek itulah yang menyebabkan setelan Penyosohan tak ada di Pos Produksi
#: sama sekali. Menghapus app Meja hari itu akan menghilangkan satu-satunya
#: layar yang bisa menambah atau membuang sebab berhenti mesin sosoh.
NAMA_PROSES: dict[str, str] = {"pengeringan": "Pengeringan", "giling": "Giling",
                               "penyosohan": "Penyosohan"}
GUDANG_PROSES: dict[str, str] = {"pengeringan": "g1", "giling": "g1",
                                 "penyosohan": "g2"}


@dataclass
class JedaResult:
    jenis: str
    kode: str
    sebab: str
    #: Terisi hanya saat MELANJUTKAN: berapa lama ia tertahan barusan.
    tertahan_detik: float | None = None
    kali: int = 0


def _detik(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


async def _lot_berjalan(db: AsyncSession, kode: str) -> DryingLot:
    lot = (await db.execute(
        select(DryingLot).where(DryingLot.kode_lot == kode)
    )).scalars().first()
    if lot is None:
        raise JedaError(f"Pengeringan {kode} tidak ditemukan.")
    if lot.status != "proses":
        raise JedaError(f"Pengeringan {kode} sudah tidak berjalan.")
    return lot


async def _giling_berjalan(db: AsyncSession, kode: str) -> MillingProcess:
    proc = (await db.execute(
        select(MillingProcess).where(MillingProcess.kode_proses == kode)
    )).scalars().first()
    if proc is None:
        raise JedaError(f"Giling {kode} tidak ditemukan.")
    if proc.status != "proses":
        raise JedaError(f"Giling {kode} sudah ditutup.")
    return proc


async def _sosoh_berjalan(db: AsyncSession, kode: str) -> PolishingProcess:
    proc = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.kode_proses == kode)
    )).scalars().first()
    if proc is None:
        raise JedaError(f"Penyosohan {kode} tidak ditemukan.")
    if proc.status != "proses":
        raise JedaError(f"Penyosohan {kode} sudah ditutup.")
    return proc


#: Kolom penunjuk proses per jenis. Satu tempat: tiga jenis, tiga kolom —
#: menulis `if jenis == ...` di tiap fungsi adalah cara jenis ketiga
#: tertinggal di salah satunya.
_KOLOM = {
    "pengeringan": JedaProses.drying_lot_id,
    "giling": JedaProses.milling_process_id,
    "penyosohan": JedaProses.polishing_process_id,
}


def _gudang(jenis: str) -> str:
    """Jeda dicatat pada gudang prosesnya: penyosohan di G2, sisanya di G1."""
    return G2 if jenis == "penyosohan" else G1


def _kolom(jenis: str):
    return _KOLOM.get(jenis, JedaProses.milling_process_id)


async def _proses_berjalan(db: AsyncSession, jenis: str, kode: str):
    if jenis == "pengeringan":
        return await _lot_berjalan(db, kode)
    if jenis == "penyosohan":
        return await _sosoh_berjalan(db, kode)
    return await _giling_berjalan(db, kode)


def _saring(jenis: str):
    return JedaProses.jenis == jenis


def _hidup():
    return JedaProses.dibatalkan_pada.is_(None)


async def _catatan(db, id_):
    return (await db.scalars(select(JedaCatatan).where(
        JedaCatatan.jeda_id == id_, JedaCatatan.dibatalkan_pada.is_(None))
        .order_by(JedaCatatan.waktu_kejadian, JedaCatatan.id).execution_options(populate_existing=True))).all()


def _zona(waktu):
    from zoneinfo import ZoneInfo
    from app.config import settings
    zona = ZoneInfo(settings.app_timezone)
    return waktu.replace(tzinfo=zona) if waktu.tzinfo is None else waktu.astimezone(zona)


def _cap(w):
    return w.timestamp() if w else None


def _mulai(obj, jenis):
    return obj.waktu_mulai_pengeringan if jenis == 'pengeringan' else obj.waktu_mulai


async def ringkasan_jeda(db, *, jenis, kode):
    if jenis not in SEBAB:
        raise JedaError('Jenis proses tidak dikenal.')
    obj = await _proses_berjalan(db, jenis, kode)
    rows = (await db.scalars(select(JedaProses).where(_kolom(jenis) == obj.id)
                            .order_by(JedaProses.id).execution_options(populate_existing=True))).all()
    events = (await db.scalars(select(JedaCatatan).where(
        JedaCatatan.jeda_id.in_([r.id for r in rows] or [-1])).order_by(JedaCatatan.id))).all()
    basis = [jenis, kode, obj.status, _cap(_mulai(obj, jenis)),
             [[r.id, _cap(r.mulai), _cap(r.selesai), r.sebab, _cap(r.dibatalkan_pada)] for r in rows],
             [[e.id, _cap(e.dibatalkan_pada)] for e in events]]
    aktif = next((r for r in rows if r.selesai is None and r.dibatalkan_pada is None), None)
    teks = (f'{kode} · dijeda sejak {_zona(aktif.mulai):%d/%m/%Y %H:%M} · {aktif.sebab}'
            if aktif else f'{kode} · mesin sedang berjalan')
    return {'dasar': hashlib.sha256(json.dumps(basis).encode()).hexdigest(),
            'teks': teks, 'dijeda': aktif is not None}


async def jeda_terbuka(db: AsyncSession, jenis: str, id_: int) -> JedaProses | None:
    return await db.scalar(select(JedaProses).where(
        _kolom(jenis) == id_, JedaProses.selesai.is_(None), _hidup()).execution_options(populate_existing=True))


async def tertahan_detik(db: AsyncSession, jenis: str, id_: int,
                         sampai: datetime | None = None) -> float:
    kini = sampai or now_local()
    rows = (await db.scalars(select(JedaProses).where(_kolom(jenis) == id_, _hidup()))).all()
    return sum(max(0, _detik(j.mulai, min(j.selesai or kini, kini))) for j in rows)


async def _sebab(db, jenis, sebab, sebab_lain):
    from app.services.setelan import sebab_jeda
    if sebab == SEBAB_LAIN:
        nilai = (sebab_lain or '').strip()
        if not nilai:
            raise JedaError('Tulis sebabnya dulu bila memilih Lainnya.')
    else:
        if sebab not in (await sebab_jeda(db)).get(jenis, []):
            raise JedaError('Pilih sebab yang sesuai jenis proses, atau pilih Lainnya.')
        nilai = sebab
    if len(nilai) > 120:
        raise JedaError('Sebab maksimal 120 karakter; gunakan catatan kondisi untuk rinciannya.')
    return nilai


async def _ulang(db, kunci, sidik, user):
    if not kunci:
        return None
    cat = await db.scalar(select(JedaCatatan).where(JedaCatatan.kunci_kiriman == kunci))
    if cat is None:
        return None
    if cat.dicatat_oleh != user.id or cat.sidik_payload != sidik or cat.dibatalkan_pada:
        raise JedaError('Kiriman ini sudah dipakai atau dibatalkan. Buka formulir baru.')
    return JedaResult(**cat.hasil)


async def _kejadian(db, *, user, jenis, kode, aksi, sebab='', sebab_lain=None,
                    waktu_kejadian=None, alasan_terlambat='', catatan='',
                    dasar=None, kunci_kiriman=None):
    if jenis not in SEBAB:
        raise JedaError('Sebutkan prosesnya: pengeringan, giling, atau penyosohan.')
    sidik = hashlib.sha256(json.dumps([jenis, kode, aksi, sebab, sebab_lain,
        waktu_kejadian.isoformat() if waktu_kejadian else None,
        alasan_terlambat, catatan], sort_keys=True).encode()).hexdigest()
    ulang = await _ulang(db, kunci_kiriman, sidik, user)
    if ulang:
        return ulang
    obj = await _proses_berjalan(db, jenis, kode)
    # Semua aksi, termasuk dua HP dan kiriman ulang, diserialkan pada proses
    # yang sama. Mengunci jeda saja tidak menjaga aksi berhenti pertama.
    await db.refresh(obj, with_for_update=True)
    if obj.status != 'proses':
        raise JedaError('Proses sudah selesai. Periksa catatan terbaru.')
    ulang = await _ulang(db, kunci_kiriman, sidik, user)
    if ulang:
        return ulang
    if dasar is not None and (await ringkasan_jeda(db, jenis=jenis, kode=kode))['dasar'] != dasar:
        raise JedaError('Keadaan jeda berubah sejak diperiksa. Periksa ulang sebelum menyimpan.')
    dicatat = now_local()
    waktu = _zona(waktu_kejadian) if waktu_kejadian else dicatat
    if waktu > dicatat:
        raise JedaError('Waktu kejadian tidak boleh di masa depan.')
    mulai = _mulai(obj, jenis)
    if mulai is None or waktu < mulai:
        raise JedaError('Waktu kejadian tidak boleh sebelum proses dimulai.')
    selesai = getattr(obj, 'waktu_selesai', None)
    if selesai and waktu > selesai:
        raise JedaError('Waktu kejadian melewati penyelesaian proses.')
    if waktu_kejadian and not (alasan_terlambat or '').strip():
        raise JedaError('Isi alasan keterlambatan pencatatan waktu aktual.')
    aktif = await jeda_terbuka(db, jenis, obj.id)
    rows = (await db.scalars(select(JedaProses).where(_kolom(jenis) == obj.id, _hidup())
                             .order_by(JedaProses.mulai).execution_options(populate_existing=True))).all()
    if aksi == 'hentikan':
        if aktif:
            raise JedaError('Proses sudah dijeda. Gunakan Perbarui kondisi jeda tanpa melanjutkan mesin.')
        if any(r.selesai and waktu < r.selesai for r in rows):
            raise JedaError('Waktu berhenti bertumpang tindih dengan jeda sebelumnya.')
        nilai = await _sebab(db, jenis, sebab, sebab_lain)
        aktif = JedaProses(jenis=jenis, sebab=nilai, mulai=waktu, dicatat_oleh=user.id,
            drying_lot_id=obj.id if jenis == 'pengeringan' else None,
            milling_process_id=obj.id if jenis == 'giling' else None,
            polishing_process_id=obj.id if jenis == 'penyosohan' else None)
        db.add(aktif)
        await db.flush()
        kali = len(rows) + 1
    else:
        if aktif is None:
            raise JedaError('Proses tidak sedang dijeda. Periksa keadaan terbaru.')
        # Mulai interval tetap, meski alasan/keadaan berubah di tengah jeda.
        events = await _catatan(db, aktif.id)
        if not events:
            # Baris lama yang dibuat sebelum log kejadian tersedia tetap punya
            # penghenti yang diketahui; jangan hilangkan sebab awalnya.
            awal = JedaCatatan(jeda_id=aktif.id, aksi='hentikan',
                waktu_kejadian=aktif.mulai, dicatat_pada=aktif.created_at,
                dicatat_oleh=aktif.dicatat_oleh, sebab=aktif.sebab, asal_lama=True)
            db.add(awal)
            await db.flush()
            events = [awal]
        batas = max([aktif.mulai] + [e.waktu_kejadian for e in events])
        if waktu < batas:
            raise JedaError('Waktu kejadian mendahului kejadian jeda terakhir; urutkan catatannya.')
        nilai = aktif.sebab if aksi == 'lanjutkan' else await _sebab(db, jenis, sebab, sebab_lain)
        if aksi == 'kondisi':
            if nilai == aktif.sebab and not (catatan or '').strip():
                raise JedaError('Tuliskan perubahan kondisi atau pilih penyebab yang berubah.')
            aktif.sebab = nilai
        elif aksi == 'lanjutkan':
            aktif.selesai = waktu
        kali = len(rows)
    hasil = JedaResult(jenis=jenis, kode=kode, sebab=nilai, kali=kali,
        tertahan_detik=_detik(aktif.mulai, waktu) if aksi == 'lanjutkan' else None)
    event = JedaCatatan(jeda_id=aktif.id, aksi=aksi, waktu_kejadian=waktu,
        dicatat_pada=dicatat, dicatat_oleh=user.id, sebab=nilai, catatan=catatan or None,
        alasan_terlambat=(alasan_terlambat or '').strip() or None,
        kunci_kiriman=kunci_kiriman, sidik_payload=sidik, hasil=asdict(hasil))
    db.add(event)
    await db.flush()
    await log_activity(db, table_name='jeda_catatan', record_id=event.id,
        action='INSERT', changed_by=user.id, aksi='jeda_' + aksi,
        new_value=f'{kode} · {aksi} · {nilai} · kejadian {waktu.isoformat()}',
        alasan=alasan_terlambat or catatan or None, gudang=_gudang(jenis))
    await db.commit()
    return hasil


async def hentikan(db: AsyncSession, *, user, jenis: str, kode: str,
                   sebab: str, sebab_lain: str | None = None, **kw) -> JedaResult:
    return await _kejadian(db, user=user, jenis=jenis, kode=kode, aksi='hentikan',
                           sebab=sebab, sebab_lain=sebab_lain, **kw)


async def lanjutkan(db: AsyncSession, *, user, jenis: str, kode: str, **kw) -> JedaResult:
    return await _kejadian(db, user=user, jenis=jenis, kode=kode, aksi='lanjutkan', **kw)


async def perbarui_kondisi(db: AsyncSession, *, user, jenis: str, kode: str,
                          sebab: str, sebab_lain=None, **kw) -> JedaResult:
    return await _kejadian(db, user=user, jenis=jenis, kode=kode, aksi='kondisi',
                           sebab=sebab, sebab_lain=sebab_lain, **kw)


async def tutup_bersama_proses(db, *, jenis, obj, saat, user):
    jeda = await jeda_terbuka(db, jenis, obj.id)
    if jeda is None:
        return
    events = await _catatan(db, jeda.id)
    if saat < max([jeda.mulai] + [e.waktu_kejadian for e in events]):
        raise JedaError('Waktu selesai proses mendahului kejadian jeda terakhir.')
    jeda.selesai = saat
    db.add(JedaCatatan(jeda_id=jeda.id, aksi='akhir_proses', waktu_kejadian=saat,
        dicatat_pada=now_local(), dicatat_oleh=user.id if user else None, sebab=jeda.sebab))


async def batalkan_akhir_proses(db, jeda):
    events = await _catatan(db, jeda.id)
    if any(e.aksi == 'lanjutkan' and e.waktu_kejadian == jeda.selesai for e in events):
        return
    for e in events:
        if e.aksi == 'akhir_proses' and e.waktu_kejadian == jeda.selesai:
            e.dibatalkan_pada = now_local()
    jeda.selesai = None


async def batalkan_kejadian(db, *, event_id, user):
    event = await db.get(JedaCatatan, event_id)
    if not event or event.dibatalkan_pada or event.aksi not in ('hentikan','lanjutkan','kondisi'):
        raise JedaError('Kejadian ini tidak bisa dibatalkan.')
    jeda = await db.get(JedaProses, event.jeda_id)
    fk = _kolom(jeda.jenis).key
    obj = await _proses_berjalan(db, jeda.jenis, event.hasil['kode'])
    await db.refresh(obj, with_for_update=True)
    if obj.status != 'proses':
        raise JedaError('Buka kembali proses yang selesai sebelum membatalkan kejadian jedanya.')
    await db.refresh(event)
    if event.dibatalkan_pada:
        raise JedaError('Kejadian ini sudah dibatalkan.')
    events = await _catatan(db, jeda.id)
    if events[-1].id != event.id:
        raise JedaError('Ada kejadian jeda sesudahnya. Batalkan langkah berikutnya dahulu.')
    if event.aksi == 'hentikan':
        jeda.dibatalkan_pada = now_local()
    elif event.aksi == 'lanjutkan':
        berikut = await db.scalar(select(JedaProses.id).where(
            _kolom(jeda.jenis) == getattr(jeda, fk), JedaProses.id != jeda.id,
            JedaProses.mulai >= event.waktu_kejadian, _hidup()).limit(1))
        if berikut:
            raise JedaError('Ada jeda berikutnya; pembatalan akan menimbulkan tumpang tindih.')
        jeda.selesai = None
    else:
        sebelumnya = [e for e in events if e.id != event.id]
        if not sebelumnya:
            raise JedaError('Penyebab sebelumnya tidak dapat dipastikan.')
        jeda.sebab = sebelumnya[-1].sebab
    event.dibatalkan_pada = now_local()
    event.dibatalkan_oleh = user.id
    await db.flush()
    return f'Dibatalkan: {event.aksi} pada {event.hasil["kode"]}. Riwayat tetap tersimpan.'


@dataclass
class Berhenti:
    sebab: str
    detik: float
    kali: int


async def rekap_berhenti(db: AsyncSession, *, sejak: datetime,
                         sampai: datetime | None = None) -> list[Berhenti]:
    """Durasi tiap sebab mengikuti perubahan kondisi dalam interval yang sama."""
    from sqlalchemy import or_
    kini = sampai or now_local()
    rows = (await db.scalars(select(JedaProses).where(_hidup(),
        JedaProses.mulai <= kini, or_(JedaProses.selesai.is_(None), JedaProses.selesai >= sejak)))).all()
    events = (await db.scalars(select(JedaCatatan).where(
        JedaCatatan.jeda_id.in_([j.id for j in rows] or [-1]),
        JedaCatatan.dibatalkan_pada.is_(None)).order_by(JedaCatatan.waktu_kejadian,JedaCatatan.id))).all()
    per = {}
    for j in rows:
        jejak = [e for e in events if e.jeda_id==j.id]
        sebab = jejak[0].sebab if jejak else j.sebab
        awal = j.mulai
        akhir = min(j.selesai or kini, kini)
        dilihat = set()
        def tambah(sampai):
            detik = max(0, (min(sampai,akhir)-max(awal,sejak)).total_seconds())
            if detik <= 0:
                return
            b = per.setdefault(sebab,Berhenti(sebab=sebab,detik=0,kali=0))
            b.detik += detik
            if sebab not in dilihat:
                b.kali += 1
                dilihat.add(sebab)
        for e in jejak:
            if e.aksi!='kondisi' or e.waktu_kejadian>akhir:
                continue
            tambah(e.waktu_kejadian)
            awal,sebab=e.waktu_kejadian,e.sebab
        tambah(akhir)
    return sorted(per.values(),key=lambda b:b.detik,reverse=True)
