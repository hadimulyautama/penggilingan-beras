"""Administrasi perusahaan terikat keanggotaan; terpisah dari izin operasi lama."""
import json,re
from sqlalchemy import select,func
from hmu_core import User,Perusahaan,LokasiPabrik,Warehouse,PenempatanGudang,KeanggotaanPerusahaan,AksesLokasiAnggota
from hmu_identitas import peran as P
from app.models import ActivityLog
from app.services import keanggotaan as anggota,organisasi_master as master
from app.services.activity_log import log_activity


async def daftar(db,user_id):
    from hmu_identitas.ruang_data import RuangData
    lokal=RuangData.lingkungan()
    with db.no_autoflush:
        return list(await db.scalars(select(Perusahaan).join(KeanggotaanPerusahaan,KeanggotaanPerusahaan.company_id==Perusahaan.id)
            .join(User,User.id==KeanggotaanPerusahaan.user_id).where(User.id==user_id,func.lower(User.status)=='aktif',
                Perusahaan.aktif.is_(True),KeanggotaanPerusahaan.aktif.is_(True),
                Perusahaan.id==lokal.company_id if lokal else True,
                func.lower(func.trim(KeanggotaanPerusahaan.peran))==P.ADMIN).order_by(Perusahaan.nama,Perusahaan.id)))


async def baca(db,ruang,**kwargs):
    data=await anggota.rincian(db,ruang=ruang,company_id=ruang.company_id,**kwargs)
    _,own=await anggota.otorisasi(db,ruang,ruang.company_id)
    grants=(await anggota.snapshot(db,own))['lokasi']
    data['lokasi_penuh']=[s['lokasi_pabrik_id'] for s in grants if s['semua_gudang']]
    sites=list(await db.scalars(select(LokasiPabrik).where(LokasiPabrik.id.in_([s['id'] for s in data['lokasi']]))))
    for s in data['lokasi']:
        row=next(x for x in sites if x.id==s['id']);s.update(kode=row.kode,alamat=row.alamat or '',bukti=master.sidik(row))
    ids=[w['id'] for s in data['lokasi'] for w in s['gudang']]
    wh=list(await db.scalars(select(Warehouse).where(Warehouse.id.in_(ids))))
    for s in data['lokasi']:
        for w in s['gudang']:
            row=next(x for x in wh if x.id==w['id']);w.update(alamat=row.alamat or '',bukti=anggota.sidik(potret_gudang(row)))
    return data


def potret_gudang(row):
    return dict(id=row.id,nama=row.nama_gudang,alamat=row.alamat or '',aktif=row.aktif,
        fungsi=row.kode_fungsi,diubah=str(row.updated_at))


async def _kunci(db,ruang):
    if db.new or db.dirty or db.deleted:raise master.OrganisasiError('Pengaturan harus memakai transaksi tersendiri.')
    if ruang.company_id is None:raise PermissionError('Pilih perusahaan sendiri yang memiliki keanggotaan Admin.')
    company=await db.scalar(select(Perusahaan).where(Perusahaan.id==ruang.company_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    actor,own=await anggota.otorisasi(db,ruang,ruang.company_id)
    return company,actor,own


async def _lokasi(db,ruang,own,lid):
    if not anggota.id_sah(lid):raise master.OrganisasiError('Lokasi tidak valid.')
    grant=await db.scalar(select(AksesLokasiAnggota).where(AksesLokasiAnggota.keanggotaan_id==own.id,
        AksesLokasiAnggota.lokasi_pabrik_id==lid,AksesLokasiAnggota.company_id==ruang.company_id).execution_options(populate_existing=True))
    if not grant or not grant.semua_gudang:raise PermissionError('Pengelolaan lokasi memerlukan akses seluruh gudang pada lokasi ini.')
    row=await db.scalar(select(LokasiPabrik).where(LokasiPabrik.id==lid,LokasiPabrik.company_id==ruang.company_id)
        .with_for_update(key_share=True).execution_options(populate_existing=True))
    if not row or not row.aktif:raise PermissionError('Lokasi aktif tidak tersedia dalam perusahaan Anda.')
    return row


async def simpan_lokasi(db,*,ruang,nama,kode,alamat,alasan,lokasi_id=None,bukti=''):
    _,actor,own=await _kunci(db,ruang)
    nama=master.teks(nama,'Nama lokasi',200,2);alamat=master.teks(alamat,'Alamat',1000,multibaris=True)
    alasan=master.teks(alasan,'Alasan perubahan',500,5)
    row=await _lokasi(db,ruang,own,lokasi_id) if lokasi_id is not None else None
    if row:
        if master.sidik(row)!=bukti:raise master.OrganisasiError('Lokasi sudah berubah. Buka data terbaru sebelum menyimpan.')
        if kode!=row.kode:raise master.OrganisasiError('Kode lokasi tetap; perusahaan lokasi tidak dapat dipindahkan.')
    elif not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,49}',kode):raise master.OrganisasiError('Kode harus 2–50 huruf kecil, angka, - atau _.')
    if await db.scalar(select(LokasiPabrik.id).where(LokasiPabrik.company_id==ruang.company_id,LokasiPabrik.kode==kode,LokasiPabrik.id!=(lokasi_id or 0))):
        raise master.OrganisasiError('Kode sudah digunakan dalam perusahaan Anda.')
    old=master.potret(row) if row else None
    if row and row.nama==nama and (row.alamat or '')==alamat:return row
    if row is None:
        row=LokasiPabrik(company_id=ruang.company_id,nama=nama,kode=kode,alamat=alamat,aktif=True);db.add(row);await db.flush()
        # Pembuat mengelola lokasi yang baru dibuatnya; tidak memperoleh akses
        # lokasi lama. Grant dan audit ikut commit yang sama dengan lokasi.
        before=await anggota.snapshot(db,own)
        db.add(AksesLokasiAnggota(keanggotaan_id=own.id,company_id=ruang.company_id,lokasi_pabrik_id=row.id,semua_gudang=True));await db.flush()
        after=await anggota.snapshot(db,own)
        await _audit(db,'hmu_company_memberships',own.id,actor.id,before,after,alasan)
    else:row.nama=nama;row.alamat=alamat
    await db.flush();await db.refresh(row)
    await _audit(db,'hmu_factory_sites',row.id,actor.id,old,master.potret(row),alasan)
    return row


async def simpan_gudang(db,*,ruang,lokasi_id,nama,alamat,alasan,gudang_id=None,bukti=''):
    _,actor,own=await _kunci(db,ruang);await _lokasi(db,ruang,own,lokasi_id)
    nama=master.teks(nama,'Nama gudang',100,2);alamat=master.teks(alamat,'Alamat',1000,multibaris=True)
    alasan=master.teks(alasan,'Alasan perubahan',500,5)
    row=None
    if gudang_id is not None:
        row=await db.scalar(select(Warehouse).join(PenempatanGudang,PenempatanGudang.warehouse_id==Warehouse.id).where(
            Warehouse.id==gudang_id,PenempatanGudang.company_id==ruang.company_id,PenempatanGudang.lokasi_pabrik_id==lokasi_id)
            .with_for_update(of=Warehouse,key_share=True).execution_options(populate_existing=True))
        if row is None:raise PermissionError('Gudang tidak tersedia dalam lokasi perusahaan Anda.')
        if anggota.sidik(potret_gudang(row))!=bukti:raise master.OrganisasiError('Gudang sudah berubah. Buka data terbaru sebelum menyimpan.')
    old=potret_gudang(row) if row else None
    if row and row.nama_gudang==nama and (row.alamat or '')==alamat:return row
    if row is None:
        existing=await db.scalar(select(Warehouse).join(PenempatanGudang,PenempatanGudang.warehouse_id==Warehouse.id).where(
            PenempatanGudang.company_id==ruang.company_id,PenempatanGudang.lokasi_pabrik_id==lokasi_id,
            func.lower(Warehouse.nama_gudang)==nama.lower()))
        if existing:
            if (existing.alamat or '')==alamat:return existing
            raise master.OrganisasiError('Nama gudang sudah digunakan pada lokasi ini. Buka identitas gudang yang sudah ada.')
        row=Warehouse(nama_gudang=nama,alamat=alamat,aktif=True);db.add(row);await db.flush()
        db.add(PenempatanGudang(warehouse_id=row.id,company_id=ruang.company_id,lokasi_pabrik_id=lokasi_id))
    else:row.nama_gudang=nama;row.alamat=alamat
    await db.flush();await db.refresh(row)
    new=dict(potret_gudang(row),company_id=ruang.company_id,lokasi_pabrik_id=lokasi_id)
    await _audit(db,'warehouses',row.id,actor.id,old,new,alasan)
    return row


async def _audit(db,table,rid,uid,old,new,reason):
    await log_activity(db,table_name=table,record_id=rid,changed_by=uid,action='UPDATE' if old else 'INSERT',
        old_value=json.dumps(old,ensure_ascii=False) if old else None,new_value=json.dumps(new,ensure_ascii=False),
        alasan=reason,field_name='pengaturan_perusahaan',aksi='pengaturan_perusahaan')


async def riwayat(db,ruang,*,sebelum=None):
    data=await baca(db,ruang)
    _,own=await anggota.otorisasi(db,ruang,ruang.company_id);batas=(await anggota.snapshot(db,own))['lokasi']
    mids=select(KeanggotaanPerusahaan.id).where(KeanggotaanPerusahaan.company_id==ruang.company_id)
    lids=[s['id'] for s in data['lokasi']];wids=[w['id'] for s in data['lokasi'] for w in s['gudang']]
    from sqlalchemy import and_,or_
    q=select(ActivityLog).where(or_(and_(ActivityLog.table_name=='hmu_company_memberships',ActivityLog.record_id.in_(mids)),
        and_(ActivityLog.table_name=='hmu_factory_sites',ActivityLog.record_id.in_(lids)),
        and_(ActivityLog.table_name=='warehouses',ActivityLog.record_id.in_(wids))),
        ActivityLog.aksi.in_(['keanggotaan_perusahaan','pengaturan_perusahaan']))
    if sebelum:q=q.where(ActivityLog.id<sebelum)
    rows=list(await db.scalars(q.order_by(ActivityLog.id.desc()).limit(51)))
    safe=[]
    for log in rows[:50]:
        if log.table_name=='hmu_company_memberships':
            snapshots=[json.loads(v) for v in (log.old_value,log.new_value) if v]
            if any(not anggota.dalam_batas(s.get('lokasi',[]),batas) for s in snapshots):continue
        safe.append(log)
    return safe,rows[49].id if len(rows)>50 else None
