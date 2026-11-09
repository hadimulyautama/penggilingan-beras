"""Master jenis beras bersama. Nilai acuan bukan hasil pengukuran QC."""
from __future__ import annotations

from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
import hashlib
import json
from uuid import uuid4

from sqlalchemy import func, select, text
from app.models import RiceQualityStandard, SetelanPabrik
from app.performa import baca_sekali
from app.services.activity_log import log_activity

_nama: ContextVar[dict[str, str]] = ContextVar('nama_spesifikasi_beras', default={})
K_BAWAAN_PENERIMAAN = 'spesifikasi_penerimaan_beras_id'
_KODE_LAMA = frozenset(('premium', 'medsuper', 'medium', 'sayur'))


def adalah_spek(kode):
    # Kode baru milik master selalu spek_. Penulisan tetap memeriksa DB aktif.
    return bool(kode) and (kode in _KODE_LAMA or kode in _nama.get() or kode.startswith('spek_'))


def nama_spek(kode):
    return _nama.get().get(kode)


@baca_sekali
async def _master(db):
    rows = (await db.execute(select(RiceQualityStandard).order_by(
        RiceQualityStandard.urutan, RiceQualityStandard.id))).scalars().all()
    return [dict(id=r.id, kode=r.kode, nama=r.nama, aktif=r.aktif) for r in rows]


async def daftar(db, *, termasuk_nonaktif=False):
    from app.services.jenis_hasil_samping import daftar as samping
    await samping(db, termasuk_nonaktif=True)
    rows = await _master(db)
    _nama.set({r['kode']: r['nama'] for r in rows})
    return [r for r in rows if termasuk_nonaktif or r['aktif']]


async def jenis_hasil(db, *, termasuk_nonaktif=False):
    from app.services.jenis_hasil_samping import daftar as samping
    return [r['kode'] for r in await daftar(db, termasuk_nonaktif=termasuk_nonaktif)] + ['beras_b'] + [r['kode'] for r in await samping(db, termasuk_nonaktif=termasuk_nonaktif)]


async def jenis_beras(db, *, termasuk_nonaktif=False):
    return [r['kode'] for r in await daftar(db, termasuk_nonaktif=termasuk_nonaktif)] + ['beras_b']


async def bawaan_penerimaan(db):
    nilai = await db.get(SetelanPabrik, K_BAWAAN_PENERIMAAN)
    if not nilai or not nilai.nilai.isdigit():
        return None
    row = await db.get(RiceQualityStandard, int(nilai.nilai))
    return row if row and row.aktif else None


async def standar_penerimaan(db, kode=None):
    await db.execute(text('SELECT pg_advisory_xact_lock_shared(861274003)'))
    if kode:
        row = await db.scalar(select(RiceQualityStandard).where(
            RiceQualityStandard.kode == kode, RiceQualityStandard.aktif.is_(True)))
    else:
        row = await bawaan_penerimaan(db)
    if row is None:
        raise ValueError('Pilih spesifikasi beras yang aktif. Spesifikasi bawaan penerimaan belum tersedia.')
    return row


def _kunci(id_):
    return f'spesifikasi_beras:{id_}'


def _versi(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def _pemakaian(db, ids):
    if not ids:
        return set()
    refs = (await db.execute(text("""
        SELECT ns.nspname, tab.relname, att.attname
        FROM pg_constraint c
        JOIN pg_class tab ON tab.oid=c.conrelid
        JOIN pg_namespace ns ON ns.oid=tab.relnamespace
        JOIN pg_attribute att ON att.attrelid=tab.oid AND att.attnum=c.conkey[1]
        WHERE c.contype='f' AND c.confrelid='rice_quality_standards'::regclass
    """))).all()
    quote = db.bind.dialect.identifier_preparer.quote
    bagian = [f'SELECT {quote(col)} AS id FROM {quote(schema)}.{quote(table)} '
              f'WHERE {quote(col)}=ANY(CAST(:ids AS integer[]))' for schema, table, col in refs]
    for table in ('polishing_output_logs', 'sampel_qc_sosoh'):
        bagian.append(f'SELECT m.id FROM rice_quality_standards m JOIN {quote(table)} r '
                      'ON r.jenis=m.kode WHERE m.id=ANY(CAST(:ids AS integer[]))')
    return set((await db.scalars(text(' UNION '.join(bagian)), {'ids': list(ids)})).all())


async def sudah_dipakai(db, row):
    """Termasuk FK aplikasi lain, log hasil, dan sampel QC historis."""
    return row.id in await _pemakaian(db, [row.id])


async def rincian(db, *, pemakaian=False):
    rows = await daftar(db, termasuk_nonaktif=True)
    attrs = dict((await db.execute(select(SetelanPabrik.kunci, SetelanPabrik.nilai)
        .where(SetelanPabrik.kunci.like('spesifikasi_beras:%')))).all())
    bawaan = await bawaan_penerimaan(db)
    dipakai = await _pemakaian(db, [r['id'] for r in rows]) if pemakaian else set()
    for row in rows:
        acuan = json.loads(attrs.get(_kunci(row['id']), '{}'))
        row.update(broken=acuan.get('broken', ''), sosoh=acuan.get('sosoh', ''),
                   bawaan_penerimaan=bool(bawaan and bawaan.id == row['id']))
        row['versi'] = _versi(row)
        if pemakaian:
            row['dipakai'] = row['id'] in dipakai
    return rows


def _angka(raw, nama, maksimum):
    try:
        n = Decimal(str(raw).strip().replace(',', '.'))
    except InvalidOperation:
        raise ValueError(f'{nama} wajib berupa angka.') from None
    if not n.is_finite() or not 0 <= n <= maksimum:
        raise ValueError(f'{nama} harus antara 0 dan {maksimum}%.')
    if n.as_tuple().exponent < -2:
        raise ValueError(f'{nama} maksimal dua angka di belakang koma.')
    return format(n, 'f')


async def simpan(db, *, user, nama='', broken='', sosoh='', id_=None, versi='', aksi='tambah'):
    # Urutkan administrasi master; penguncian FOR UPDATE juga melindungi FK.
    await db.execute(text('SELECT pg_advisory_xact_lock(861274003)'))
    row = None
    if id_ is not None:
        row = await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.id == id_)
                              .with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise ValueError('Spesifikasi tidak ditemukan. Muat ulang halaman.')
        sebelum = next(r for r in await rincian(db) if r['id'] == id_)
        if versi != sebelum['versi']:
            raise ValueError('Spesifikasi telah berubah. Muat ulang lalu periksa nilai terbaru.')
    else:
        sebelum = None
    if aksi == 'bawaan':
        if not row.aktif:
            raise ValueError('Aktifkan spesifikasi sebelum menjadikannya bawaan penerimaan.')
        cfg = await db.get(SetelanPabrik, K_BAWAAN_PENERIMAAN)
        old_id = cfg.nilai if cfg else None
        if cfg:
            cfg.nilai, cfg.diubah_oleh, cfg.updated_at = str(row.id), user.id, func.now()
        else:
            db.add(SetelanPabrik(kunci=K_BAWAAN_PENERIMAAN, nilai=str(row.id), diubah_oleh=user.id))
        await log_activity(db, table_name='setelan_pabrik', record_id=0, action='UPDATE',
            changed_by=user.id, field_name=K_BAWAAN_PENERIMAAN, old_value=old_id,
            new_value=str(row.id), aksi='spek_bawaan_penerimaan')
        sesudah = {**sebelum, 'bawaan_penerimaan': True}
    elif aksi in {'hapus', 'nonaktifkan', 'aktifkan'}:
        if aksi in {'hapus', 'nonaktifkan'} and sebelum['bawaan_penerimaan']:
            cfg = await db.get(SetelanPabrik, K_BAWAAN_PENERIMAAN)
            cfg.nilai, cfg.diubah_oleh, cfg.updated_at = '', user.id, func.now()

        dipakai = await sudah_dipakai(db, row)
        if aksi == 'hapus' and dipakai:
            raise ValueError('Spesifikasi sudah dipakai. Nonaktifkan agar riwayat tetap tersimpan.')
        if aksi == 'nonaktifkan' and not dipakai:
            raise ValueError('Spesifikasi belum dipakai. Gunakan Hapus untuk menghapusnya.')
        if aksi == 'hapus':
            # Seed tidak boleh membuat ulang jenis bawaan yang sengaja dihapus.
            key = 'spesifikasi_beras_dihapus:' + row.kode
            db.add(SetelanPabrik(kunci=key, nilai='1', diubah_oleh=user.id))
            attrs = await db.get(SetelanPabrik, _kunci(row.id))
            if attrs:
                await db.delete(attrs)
            await db.delete(row)
            sesudah = None
        else:
            row.aktif = aksi == 'aktifkan'
            sesudah = {**sebelum, 'aktif': row.aktif,
                       'bawaan_penerimaan': sebelum['bawaan_penerimaan'] if row.aktif else False}
    else:
        nama = ' '.join(nama.split())
        if not 2 <= len(nama) <= 50:
            raise ValueError('Nama spesifikasi wajib 2–50 karakter.')
        b = _angka(broken, 'Kadar broken acuan', 100)
        s = _angka(sosoh, 'Derajat sosoh acuan', Decimal('9999999999.99'))
        duplicate = await db.scalar(select(RiceQualityStandard.id).where(
            func.lower(RiceQualityStandard.nama) == nama.lower(),
            RiceQualityStandard.id != (id_ or 0)))
        if duplicate:
            raise ValueError('Nama spesifikasi sudah dipakai. Gunakan nama lain.')
        if row is None:
            urut = await db.scalar(select(func.coalesce(func.max(RiceQualityStandard.urutan), 0)))
            row = RiceQualityStandard(kode='spek_' + uuid4().hex[:15], nama=nama,
                                      urutan=urut + 1, aktif=True)
            db.add(row)
            await db.flush()
        else:
            row.nama = nama
        attrs = await db.get(SetelanPabrik, _kunci(row.id))
        nilai = json.dumps(dict(broken=b, sosoh=s))
        if attrs is None:
            db.add(SetelanPabrik(kunci=_kunci(row.id), nilai=nilai, diubah_oleh=user.id))
        else:
            attrs.nilai, attrs.diubah_oleh, attrs.updated_at = nilai, user.id, func.now()
        sesudah = dict(id=row.id, kode=row.kode, nama=nama, aktif=row.aktif, broken=b, sosoh=s)
    await log_activity(db, table_name='rice_quality_standards', record_id=row.id,
        action='DELETE' if aksi == 'hapus' else 'UPDATE' if sebelum else 'INSERT', changed_by=user.id,
        old_value=json.dumps(sebelum, ensure_ascii=False) if sebelum else None,
        new_value=json.dumps(sesudah, ensure_ascii=False), aksi=f'spesifikasi_beras_{aksi}')
    await db.flush()
    return row


async def jenis_untuk_proses(db, proses_id, *, beras_saja=False):
    from app.models import PolishingProcess, PolishingOutputLog, SampelQcSosoh
    aktif = await jenis_beras(db) if beras_saja else await jenis_hasil(db)
    proc = await db.get(PolishingProcess, proses_id)
    if proc is None or proc.status != 'proses':
        return aktif
    dikenal = set(await jenis_beras(db, termasuk_nonaktif=True) if beras_saja
                  else await jenis_hasil(db, termasuk_nonaktif=True))
    lama = set((await db.scalars(select(PolishingOutputLog.jenis).where(
        PolishingOutputLog.polishing_process_id == proses_id))).all())
    lama.update((await db.scalars(select(SampelQcSosoh.jenis).where(
        SampelQcSosoh.polishing_process_id == proses_id,
        SampelQcSosoh.dibatalkan_pada.is_(None)))).all())
    return list(dict.fromkeys([*aktif, *sorted(lama & dikenal)]))
