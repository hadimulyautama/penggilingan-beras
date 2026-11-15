"""Identitas lokasi transfer berasal dari master perusahaan/pabrik/gudang."""
from sqlalchemy import select
from app.models import Warehouse, Silo
from hmu_core.organisasi import PenempatanGudang, LokasiPabrik, Perusahaan


async def daftar(db):
    rows = (await db.execute(select(Warehouse, PenempatanGudang, LokasiPabrik, Perusahaan)
        .outerjoin(PenempatanGudang, PenempatanGudang.warehouse_id == Warehouse.id)
        .outerjoin(LokasiPabrik, LokasiPabrik.id == PenempatanGudang.lokasi_pabrik_id)
        .outerjoin(Perusahaan, Perusahaan.id == PenempatanGudang.company_id))).all()
    return {w.id:dict(gudang_id=w.id,gudang_nama=w.nama_gudang,kode_fungsi=w.kode_fungsi,
        pabrik_id=p.id if p else None,pabrik_nama=p.nama if p else None,
        company_id=c.id if c else None,perusahaan_nama=c.nama if c else None,
        aktif=bool(w.aktif and p and p.aktif and c and c.aktif)) for w,b,p,c in rows}


async def tujuan_sah(db, asal_id, tujuan_id):
    from hmu_identitas.ruang_data import pastikan_perusahaan
    locations = await daftar(db)
    a,t = locations.get(asal_id),locations.get(tujuan_id)
    if not a or not t or not a['aktif'] or not t['aktif']:
        raise ValueError('Pilih gudang aktif yang sudah ditetapkan ke pabrik dan perusahaan aktif pada master.')
    if a['company_id'] != t['company_id']:
        raise ValueError('Transfer hanya dapat dilakukan dalam satu perusahaan. Pemilik barang tetap sama.')
    if asal_id == tujuan_id:
        raise ValueError('Pilih gudang tujuan yang berbeda dari gudang asal.')
    pastikan_perusahaan(a['company_id'])
    return a,t


async def lengkapi_lintasan(db, journeys):
    locations = await daftar(db)
    silo_ids = {j['lintasan']['tujuan'].get('silo_id') for j in journeys}
    silos = dict((await db.execute(select(Silo.id,Silo.nama_silo).where(Silo.id.in_(silo_ids-{None})))).all())
    for j in journeys:
        for side in ('asal','tujuan'):
            loc = j['lintasan'][side]
            loc.update(locations.get(loc.get('gudang_id'), {}))
            if side == 'tujuan':
                loc['penempatan'] = silos.get(loc.get('silo_id')) or (
                    'Area stok' if j.get('jenis_transfer') == 'barang' else 'Tumpukan')
