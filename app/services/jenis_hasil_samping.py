"""Jenis hasil samping yang dapat dikelola per pabrik, tanpa enum pilihan UI."""
from __future__ import annotations
from contextvars import ContextVar
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select, text
from app.models import SetelanPabrik
from app.services.activity_log import log_activity
from app.performa import baca_sekali

AWALAN = 'jenis_hasil_samping:'
_katalog = ContextVar('master_hasil_samping', default=None)
# Pembaca historis murni tetap berfungsi di luar konteks permintaan/DB.
_LAMA = {'broken': 50, 'menir': 50, 'bekatul': 40, 'reject': 50}


def adalah_samping(jenis):
    return bool(jenis) and (jenis in _LAMA or jenis.startswith('hs_'))


def nama_samping(jenis):
    return (next((r['nama'] for r in (_katalog.get() or []) if r['kode'] == jenis), None))


def jenis_ringkasan(outputs):
    """Jenis aktif serta jenis yang benar-benar ada pada hasil historis."""
    rows = _katalog.get()
    aktif = list(_LAMA) if rows is None else [r['kode'] for r in rows if r['aktif']]
    return list(dict.fromkeys([*aktif, *(j for j in outputs if adalah_samping(j))]))


def ukuran_otomatis(jenis):
    rows = _katalog.get()
    if rows is None:
        return _LAMA.get(jenis, 0)
    return next((r['kg_karung'] or 0 for r in rows if r['kode'] == jenis), 0)


@baca_sekali
async def _baca(db):
    return [json.loads(v) for v in (await db.scalars(select(SetelanPabrik.nilai)
        .where(SetelanPabrik.kunci.like(AWALAN + '%')).order_by(SetelanPabrik.kunci))).all()]


async def daftar(db, *, termasuk_nonaktif=False):
    rows = await _baca(db)
    _katalog.set(rows)
    return [dict(r, versi=hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest())
            for r in rows if termasuk_nonaktif or r['aktif']]


async def _pemakaian(db, codes):
    if not codes:
        return set()
    cols = (await db.execute(text("""
        SELECT table_schema, table_name, column_name FROM information_schema.columns
        WHERE table_schema='public' AND column_name IN ('jenis','jenis_produk','jenis_byproduct','jenis_kode','kategori','komoditas')
          AND data_type IN ('character varying','text')
    """))).all()
    quote = db.bind.dialect.identifier_preparer.quote
    parts = [f'SELECT {quote(col)} AS kode FROM {quote(schema)}.{quote(table)} '
             f'WHERE {quote(col)}=ANY(CAST(:codes AS varchar[])) OR {quote(col)}=ANY(CAST(:upper_codes AS varchar[]))' for schema, table, col in cols]
    if not parts:
        return set()
    return {value.lower().removesuffix('_masuk') for value in (await db.scalars(text(' UNION '.join(parts)),
        {'codes': list(codes), 'upper_codes': [v for c in codes for v in (c.upper(),c.upper()+'_MASUK')]})).all()}


async def dipakai(db, kode):
    return kode in await _pemakaian(db, [kode])


async def rincian(db):
    rows = await daftar(db, termasuk_nonaktif=True)
    used = await _pemakaian(db, [r['kode'] for r in rows])
    for row in rows:
        row['dipakai'] = row['kode'] in used
    return rows


async def simpan(db, *, user, aksi, kode='', versi='', nama='', bentuk='', kg_karung=''):
    await db.execute(text('SELECT pg_advisory_xact_lock(861274003)'))
    lama = None
    if aksi != 'tambah':
        lama = next((r for r in await daftar(db, termasuk_nonaktif=True) if r['kode'] == kode), None)
        if lama is None or lama['versi'] != versi:
            raise ValueError('Jenis hasil samping berubah atau tidak ditemukan. Muat ulang halaman.')
        used = await dipakai(db, kode)
    else:
        used = False
        kode = 'hs_' + uuid4().hex[:15]
    row = await db.get(SetelanPabrik, AWALAN + kode)
    sebelum = row.nilai if row else None
    if aksi in {'hapus', 'nonaktifkan', 'aktifkan'}:
        if aksi == 'hapus' and used:
            raise ValueError('Jenis sudah dipakai. Gunakan Nonaktifkan untuk menjaga riwayat.')
        if aksi == 'nonaktifkan' and not used:
            raise ValueError('Jenis belum dipakai. Gunakan Hapus.')
        if aksi == 'hapus':
            await db.delete(row)
            baru = None
        else:
            baru = {k: v for k, v in lama.items() if k != 'versi'}
            baru['aktif'] = aksi == 'aktifkan'
    else:
        nama = ' '.join(nama.split())
        if not 2 <= len(nama) <= 50:
            raise ValueError('Nama wajib 2–50 karakter.')
        if bentuk not in {'curah', 'karung'}:
            raise ValueError('Pilih stok curah atau berkarung.')
        if bentuk == 'karung':
            try:
                kg = int(kg_karung)
            except (ValueError, TypeError):
                raise ValueError('Kapasitas karung wajib berupa kg bulat.') from None
            if not 1 <= kg <= 1000:
                raise ValueError('Kapasitas karung harus 1–1000 kg.')
        else:
            kg = None
        if used and (bentuk != lama['bentuk'] or kg != lama['kg_karung']):
            raise ValueError('Bentuk stok dan kapasitas karung yang sudah dipakai tidak dapat diubah agar stok lama tetap konsisten.')
        if any(r['kode'] != kode and r['nama'].casefold() == nama.casefold()
               for r in await daftar(db, termasuk_nonaktif=True)):
            raise ValueError('Nama hasil samping sudah dipakai.')
        baru = dict(kode=kode, nama=nama, bentuk=bentuk, kg_karung=kg,
                    aktif=lama['aktif'] if lama else True)
    if baru is not None:
        nilai = json.dumps(baru, ensure_ascii=False)
        if row:
            row.nilai, row.diubah_oleh = nilai, user.id
        else:
            db.add(SetelanPabrik(kunci=AWALAN + kode, nilai=nilai, diubah_oleh=user.id))
    await log_activity(db, table_name='setelan_pabrik', record_id=0, action='DELETE' if aksi == 'hapus' else 'UPDATE' if lama else 'INSERT',
        changed_by=user.id, field_name=AWALAN + kode, old_value=sebelum,
        new_value=json.dumps(baru, ensure_ascii=False), aksi='jenis_hasil_samping_' + aksi)
    await db.flush()
    return kode


async def pastikan_identitas_penerimaan(db, jenis, *, user):
    """Pertahankan identitas komoditas fisik dari tiket, tanpa mengaktifkan
    kembali pilihan hasil produksi yang pernah dihapus pengguna.
    """
    if jenis not in _LAMA:
        raise ValueError('Jenis komoditas penerimaan tidak dikenal.')
    await db.execute(text('SELECT pg_advisory_xact_lock(861274003)'))
    if await db.get(SetelanPabrik, AWALAN + jenis):
        return
    from app.models import ActivityLog
    old = await db.scalar(select(ActivityLog.old_value).where(
        ActivityLog.field_name == AWALAN + jenis,
        ActivityLog.aksi == 'jenis_hasil_samping_hapus').order_by(ActivityLog.id.desc()).limit(1))
    lama = json.loads(old) if old else {}
    data = dict(kode=jenis, nama=lama.get('nama', jenis.title()), aktif=False,
                bentuk=lama.get('bentuk', 'karung'), kg_karung=lama.get('kg_karung', _LAMA[jenis]))
    db.add(SetelanPabrik(kunci=AWALAN + jenis, nilai=json.dumps(data), diubah_oleh=user.id))
    await log_activity(db, table_name='setelan_pabrik', record_id=0, action='INSERT',
        changed_by=user.id, field_name=AWALAN + jenis, new_value=json.dumps(data),
        aksi='identitas_jenis_penerimaan')
    await db.flush()


async def jenis_penerimaan(db):
    return {r['kode'].upper()+'_MASUK': r for r in await daftar(db, termasuk_nonaktif=True)
            if r['kode'] != 'broken'}


def nama_timbang_sql(kolom='t.jenis_kode', nama_lama='j.nama'):
    """Ekspresi internal untuk label tiket virtual, tanpa master timbang duplikat.

    Argumen hanya alias kolom tetap milik pembaca SQL, bukan input perangkat.
    """
    return ("coalesce((SELECT cfg.nilai::jsonb->>'nama' FROM setelan_pabrik cfg "
            "WHERE cfg.kunci='jenis_hasil_samping:'||lower(regexp_replace("
            + kolom + ", '_MASUK$', ''))), " + nama_lama + ", " + kolom + ")")
