"""Satu writer administrasi untuk Console dan Pengaturan perusahaan sendiri.

Tidak menyentuh User.role/status, akun masuk, stok, atau transaksi. Ruang
administrasi bukan bukti akses mandiri: pelaku dan cakupannya diperiksa ulang.
"""
import hashlib,json
from dataclasses import dataclass
from sqlalchemy import select,delete,func,or_
from hmu_core import Perusahaan,LokasiPabrik,KeanggotaanPerusahaan,PenempatanGudang,User,Warehouse,AksesLokasiAnggota,AksesGudangAnggota
from hmu_identitas import peran as P
from app.services.organisasi_master import OrganisasiError,teks
from app.services.activity_log import log_activity

from hmu_identitas.organisasi import PERAN_PERUSAHAAN as PERAN_ANGGOTA


@dataclass(frozen=True)
class RuangAdministrasi:
    user_id:int
    company_id:int|None=None  # None hanya diberikan gerbang Console Super Admin.


async def otorisasi(db,ruang,company_id):
    if not id_sah(ruang.user_id) or not id_sah(company_id):
        raise PermissionError('Administrasi perusahaan tidak tersedia.')
    u=await db.scalar(select(User).where(User.id==ruang.user_id).execution_options(populate_existing=True))
    if not u or (u.status or '').lower()!='aktif':raise PermissionError('Administrasi perusahaan tidak tersedia.')
    if ruang.company_id is None:
        if not P.super_saja(u.role):raise PermissionError('Console Center hanya untuk Super Admin.')
        return u,None
    if type(ruang.company_id) is not int or ruang.company_id!=company_id:raise PermissionError('Administrasi hanya untuk perusahaan sendiri.')
    m=await db.scalar(select(KeanggotaanPerusahaan).join(Perusahaan,Perusahaan.id==KeanggotaanPerusahaan.company_id).where(
        KeanggotaanPerusahaan.company_id==company_id,KeanggotaanPerusahaan.user_id==u.id,
        KeanggotaanPerusahaan.aktif.is_(True),Perusahaan.aktif.is_(True)))
    if not m or P.normal(m.peran)!=P.ADMIN:raise PermissionError('Administrasi perusahaan memerlukan keanggotaan Admin aktif.')
    return u,m


def potret_anggota(m,sites,wh):
    return dict(id=m.id,company_id=m.company_id,user_id=m.user_id,peran=P.normal(m.peran),aktif=m.aktif,
        diubah=str(m.updated_at),lokasi=[dict(lokasi_pabrik_id=s.lokasi_pabrik_id,semua_gudang=s.semua_gudang,
        gudang_ids=[w.warehouse_id for w in wh if w.lokasi_pabrik_id==s.lokasi_pabrik_id]) for s in sites])


async def snapshot(db,m):
    if m is None:return None
    sites=list(await db.scalars(select(AksesLokasiAnggota).where(AksesLokasiAnggota.keanggotaan_id==m.id).order_by(AksesLokasiAnggota.lokasi_pabrik_id)))
    wh=list(await db.scalars(select(AksesGudangAnggota).where(AksesGudangAnggota.keanggotaan_id==m.id).order_by(AksesGudangAnggota.warehouse_id)))
    return potret_anggota(m,sites,wh)


def id_sah(n):return type(n) is int and 0<n<=2147483647


def sidik(data):return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def bersihkan(lokasi):
    if not isinstance(lokasi,list) or len(lokasi)>1000:raise OrganisasiError('Daftar akses lokasi tidak valid.')
    result=[];seen=set()
    for row in lokasi:
        if not isinstance(row,dict) or set(row)!={'lokasi_pabrik_id','semua_gudang','gudang_ids'}:raise OrganisasiError('Isian akses lokasi tidak dikenal.')
        lid=row['lokasi_pabrik_id'];ids=row['gudang_ids'];all_=row['semua_gudang']
        if not id_sah(lid) or lid in seen or type(all_) is not bool or not isinstance(ids,list) or len(ids)>1000 or any(not id_sah(i) for i in ids) or len(set(ids))!=len(ids):
            raise OrganisasiError('Identitas atau cakupan lokasi/gudang tidak valid.')
        if all_ and ids:raise OrganisasiError('Pilih semua gudang atau gudang tertentu, bukan keduanya.')
        seen.add(lid);result.append(dict(lokasi_pabrik_id=lid,semua_gudang=all_,gudang_ids=sorted(ids)))
    return sorted(result,key=lambda x:x['lokasi_pabrik_id'])


def dalam_batas(pilihan,batas):
    own={x['lokasi_pabrik_id']:x for x in batas}
    return all(x['lokasi_pabrik_id'] in own and
        (own[x['lokasi_pabrik_id']]['semua_gudang'] or
         (not x['semua_gudang'] and set(x['gudang_ids'])<=set(own[x['lokasi_pabrik_id']]['gudang_ids']))) for x in pilihan)


async def simpan(db,*,ruang,company_id,user_id,peran,aktif,lokasi,bukti,alasan):
    if db.new or db.dirty or db.deleted:raise OrganisasiError('Administrasi anggota harus memakai transaksi tersendiri.')
    if not id_sah(user_id) or type(aktif) is not bool or peran not in PERAN_ANGGOTA:raise OrganisasiError('Pengguna, peran, atau status anggota tidak valid.')
    lokasi=bersihkan(lokasi);alasan=teks(alasan,'Alasan perubahan',500,5)
    # Kunci induk juga menserialisasi penambahan anggota yang belum punya baris.
    company=await db.scalar(select(Perusahaan).where(Perusahaan.id==company_id).with_for_update(key_share=True))
    actor,own=await otorisasi(db,ruang,company_id)
    if not company or not company.aktif:raise OrganisasiError('Perusahaan tidak aktif atau tidak tersedia.')
    m=await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.company_id==company_id,
        KeanggotaanPerusahaan.user_id==user_id).with_for_update().execution_options(populate_existing=True))
    old=await snapshot(db,m)
    if own and m is None:raise PermissionError('Keanggotaan baru sementara ditetapkan melalui Console Center.')
    target=await db.get(User,user_id)
    if not target or (aktif and (target.status or '').lower()!='aktif'):raise OrganisasiError('Pengguna aktif tidak tersedia.')
    if own:
        batas=(await snapshot(db,own))['lokasi']
        if not dalam_batas(lokasi,batas) or not dalam_batas(old['lokasi'],batas):raise PermissionError('Akses anggota melampaui lokasi/gudang yang boleh Anda kelola.')
        if old['peran']==P.ADMIN and old['aktif'] and (peran!=P.ADMIN or not aktif):
            admins=await db.scalar(select(func.count()).select_from(KeanggotaanPerusahaan).where(
                KeanggotaanPerusahaan.company_id==company_id,KeanggotaanPerusahaan.aktif.is_(True),func.lower(func.trim(KeanggotaanPerusahaan.peran))==P.ADMIN))
            if admins<=1:raise OrganisasiError('Admin perusahaan terakhir tidak dapat dinonaktifkan dari Pengaturan perusahaan.')
    site_ids=[x['lokasi_pabrik_id'] for x in lokasi]
    sites=list(await db.scalars(select(LokasiPabrik).where(LokasiPabrik.id.in_(site_ids),LokasiPabrik.company_id==company_id,LokasiPabrik.aktif.is_(True)).with_for_update(key_share=True)))
    if {s.id for s in sites}!=set(site_ids):raise OrganisasiError('Lokasi tidak aktif atau bukan milik perusahaan ini.')
    for s in lokasi:
        valid=set(await db.scalars(select(PenempatanGudang.warehouse_id).join(Warehouse,Warehouse.id==PenempatanGudang.warehouse_id).where(
            PenempatanGudang.company_id==company_id,PenempatanGudang.lokasi_pabrik_id==s['lokasi_pabrik_id'],
            PenempatanGudang.warehouse_id.in_(s['gudang_ids']),Warehouse.aktif.is_(True))))
        if valid!=set(s['gudang_ids']):raise OrganisasiError('Gudang tidak aktif atau tidak cocok dengan perusahaan/lokasi.')
    if old and old['peran']==peran and old['aktif']==aktif and old['lokasi']==lokasi:return old
    if (bukti or '')!=sidik(old):raise OrganisasiError('Keanggotaan sudah berubah. Baca data terbaru sebelum menyimpan.')
    if m is None:
        m=KeanggotaanPerusahaan(company_id=company_id,user_id=user_id,peran=peran,aktif=aktif);db.add(m);await db.flush()
    else:m.peran=peran;m.aktif=aktif
    await db.execute(delete(AksesGudangAnggota).where(AksesGudangAnggota.keanggotaan_id==m.id))
    await db.execute(delete(AksesLokasiAnggota).where(AksesLokasiAnggota.keanggotaan_id==m.id))
    for s in lokasi:db.add(AksesLokasiAnggota(keanggotaan_id=m.id,company_id=company_id,lokasi_pabrik_id=s['lokasi_pabrik_id'],semua_gudang=s['semua_gudang']))
    await db.flush()
    for s in lokasi:
        for wid in s['gudang_ids']:db.add(AksesGudangAnggota(keanggotaan_id=m.id,company_id=company_id,lokasi_pabrik_id=s['lokasi_pabrik_id'],warehouse_id=wid))
    await db.flush();await db.refresh(m)
    new=await snapshot(db,m)
    await log_activity(db,table_name='hmu_company_memberships',record_id=m.id,action='UPDATE' if old else 'INSERT',
        changed_by=actor.id,field_name='keanggotaan_dan_akses',old_value=json.dumps(old,ensure_ascii=False) if old else None,
        new_value=json.dumps(new,ensure_ascii=False),alasan=alasan,aksi='keanggotaan_perusahaan')
    return new


async def _rincian(db,*,ruang,company_id,cari_pengguna="",anggota_id=None):
    _,own=await otorisasi(db,ruang,company_id)
    co=await db.get(Perusahaan,company_id)
    if not co:raise OrganisasiError('Perusahaan tidak tersedia.')
    sites=list(await db.scalars(select(LokasiPabrik).where(LokasiPabrik.company_id==company_id).order_by(LokasiPabrik.nama)))
    wh=(await db.execute(select(PenempatanGudang,Warehouse).join(Warehouse,Warehouse.id==PenempatanGudang.warehouse_id).where(PenempatanGudang.company_id==company_id).order_by(Warehouse.nama_gudang))).all()
    cari=teks(cari_pengguna,'Pencarian pengguna',100)
    member_q=select(KeanggotaanPerusahaan,User).join(User,User.id==KeanggotaanPerusahaan.user_id).where(KeanggotaanPerusahaan.company_id==company_id).order_by(User.nama,User.id)
    if anggota_id is not None:
        if not id_sah(anggota_id):raise OrganisasiError('Identitas anggota tidak valid.')
        member_q=member_q.where(User.id==anggota_id)
    elif cari:member_q=member_q.where(or_(User.nama.ilike('%'+cari+'%'),User.id==int(cari) if cari.isdigit() and len(cari)<=9 else False))
    members=list((await db.execute(member_q.limit(201))).all());member_lebih=len(members)>200;members=members[:200]
    mids=[m.id for m,_ in members]
    akses_s=list(await db.scalars(select(AksesLokasiAnggota).where(AksesLokasiAnggota.keanggotaan_id.in_(mids)).order_by(AksesLokasiAnggota.lokasi_pabrik_id)))
    akses_w=list(await db.scalars(select(AksesGudangAnggota).where(AksesGudangAnggota.keanggotaan_id.in_(mids)).order_by(AksesGudangAnggota.warehouse_id)))
    data=[]
    for m,u in members:
        d=potret_anggota(m,[s for s in akses_s if s.keanggotaan_id==m.id],[w for w in akses_w if w.keanggotaan_id==m.id]);d.update(nama=u.nama,bukti=sidik(d));data.append(d)
    q=select(User).where(func.lower(User.status)=='aktif').order_by(User.nama,User.id)
    cari=teks(cari_pengguna,'Pencarian pengguna',100)
    if cari:q=q.where(or_(User.nama.ilike('%'+cari+'%'),User.id==int(cari) if cari.isdigit() and len(cari)<=9 else False))
    users=list(await db.scalars(q.limit(201))) if own is None else [u for _,u in members]
    lebih=len(users)>200;users=users[:200]
    return dict(perusahaan=dict(id=co.id,nama=co.nama,kode=co.kode,aktif=co.aktif),anggota=data,anggota_lebih=member_lebih,
        pengguna=[dict(id=u.id,nama=u.nama) for u in users],pengguna_lebih=lebih,bukti_baru=sidik(None),
        lokasi=[dict(id=s.id,nama=s.nama,aktif=s.aktif,gudang=[dict(id=w.id,nama=w.nama_gudang,aktif=w.aktif) for b,w in wh if b.lokasi_pabrik_id==s.id]) for s in sites])


async def rincian(db,*,ruang,company_id,cari_pengguna="",anggota_id=None):
    with db.no_autoflush:
        return await _rincian(db,ruang=ruang,company_id=company_id,cari_pengguna=cari_pengguna,anggota_id=anggota_id)
