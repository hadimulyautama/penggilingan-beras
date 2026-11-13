"""Penetapan identitas lama yang ditinjau, tanpa menulis ulang transaksi lama."""
import json,re
from sqlalchemy import select,text,func
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,KeanggotaanPerusahaan,AksesLokasiAnggota,Warehouse,User
from hmu_identitas.model import Akun
from hmu_identitas import peran as P
from hmu_dokumen.perusahaan import baca
from app.models import SetelanPabrik
from app.services import keanggotaan as anggota,organisasi_master as master
from app.services.activity_log import log_activity

KUNCI='organisasi_perusahaan_lama'


async def pratinjau(db,*,kode,lokasi_nama,warehouse_ids):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,49}',kode):raise master.OrganisasiError('Kode perusahaan tidak valid.')
    lokasi_nama=master.teks(lokasi_nama,'Nama lokasi',200,2)
    if not isinstance(warehouse_ids,list) or not warehouse_ids or len(set(warehouse_ids))!=len(warehouse_ids) or any(not anggota.id_sah(x) for x in warehouse_ids):
        raise master.OrganisasiError('Pilih gudang lama yang sudah dikonfirmasi lokasinya.')
    with db.no_autoflush:
        identity=await baca(db)
        link=await db.get(SetelanPabrik,KUNCI)
        if link:return dict(sudah=True,company_id=json.loads(link.nilai)['company_id'])
        if await db.scalar(select(Perusahaan.id).limit(1)):
            raise master.OrganisasiError('Master perusahaan sudah terisi. Tinjau pengaitan identitas lama melalui Console sebelum melanjutkan.')
        wh=list(await db.scalars(select(Warehouse).where(Warehouse.id.in_(warehouse_ids),Warehouse.aktif.is_(True)).order_by(Warehouse.id)))
        if len(wh)!=len(warehouse_ids):raise master.OrganisasiError('Gudang aktif tidak cocok dengan pratinjau.')
        if await db.scalar(select(PenempatanGudang.warehouse_id).where(PenempatanGudang.warehouse_id.in_(warehouse_ids)).limit(1)):
            raise master.OrganisasiError('Ada gudang yang sudah ditetapkan. Tinjau penetapan lama.')
        accounts=list((await db.execute(select(User,Akun).join(Akun,Akun.user_id==User.id).where(
            func.lower(User.status)=='aktif',Akun.status=='aktif').order_by(User.id))).unique().all())
        users=[dict(id=u.id,nama=u.nama,peran=P.ADMIN if P.admin_keatas(u.role) else P.OPERATOR,
            role_asli=u.role,akun_id=a.id,versi=a.token_version) for u,a in accounts if P.normal(u.role) in (P.OPERATOR,P.ADMIN,P.SUPERADMIN)]
        if not any(u['peran']==P.ADMIN for u in users):raise master.OrganisasiError('Belum ada Admin aktif untuk perusahaan lama.')
        data=dict(sudah=False,nama=identity.nama,alamat=identity.alamat,kode=kode,lokasi_nama=lokasi_nama,
            gudang=[dict(id=w.id,nama=w.nama_gudang,diubah=str(w.updated_at)) for w in wh],pengguna=users)
        data['bukti']=anggota.sidik(data);return data


async def terapkan(db,*,kode,lokasi_nama,warehouse_ids,bukti,alasan,user_id=None,sistem=False):
    if db.new or db.dirty or db.deleted:raise master.OrganisasiError('Penetapan harus memakai transaksi metadata tersendiri.')
    if not sistem:await master.pengelola(db,user_id)
    alasan=master.teks(alasan,'Alasan penetapan',500,5)
    await db.execute(text('SELECT pg_advisory_xact_lock(18900131)'))
    # Kunci sumber dan identitas akun selama snapshot diperiksa. Tidak ada
    # perubahan password, token, status global, gudang lama, atau catatan proses.
    await db.execute(select(Warehouse).where(Warehouse.id.in_(warehouse_ids)).order_by(Warehouse.id).with_for_update(key_share=True))
    await db.execute(select(User.id).join(Akun,Akun.user_id==User.id).order_by(User.id).with_for_update(read=True,of=User))
    await db.execute(select(Akun.id).order_by(Akun.id).with_for_update(read=True))
    plan=await pratinjau(db,kode=kode,lokasi_nama=lokasi_nama,warehouse_ids=warehouse_ids)
    if plan['sudah']:return plan['company_id']
    if plan['bukti']!=bukti:raise master.OrganisasiError('Sumber penetapan berubah. Buat pratinjau baru.')
    c=Perusahaan(kode=kode,nama=plan['nama'],aktif=True);db.add(c);await db.flush()
    site=LokasiPabrik(company_id=c.id,kode='lokasi-lama',nama=lokasi_nama,alamat=plan['alamat'],aktif=True);db.add(site);await db.flush()
    for w in plan['gudang']:db.add(PenempatanGudang(warehouse_id=w['id'],company_id=c.id,lokasi_pabrik_id=site.id))
    for u in plan['pengguna']:
        m=KeanggotaanPerusahaan(company_id=c.id,user_id=u['id'],peran=u['peran'],aktif=True);db.add(m);await db.flush()
        db.add(AksesLokasiAnggota(keanggotaan_id=m.id,company_id=c.id,lokasi_pabrik_id=site.id,semua_gudang=True))
    db.add(SetelanPabrik(kunci=KUNCI,nilai=json.dumps(dict(company_id=c.id,lokasi_pabrik_id=site.id)),diubah_oleh=user_id))
    await log_activity(db,table_name='hmu_companies',record_id=c.id,action='INSERT',changed_by=user_id,
        field_name=KUNCI,new_value=json.dumps(dict(company_id=c.id,lokasi_pabrik_id=site.id,rencana=plan,
            sumber='penetapan_sistem_disetujui' if sistem else 'console'),ensure_ascii=False),alasan=alasan,aksi='penetapan_perusahaan_lama')
    await db.flush();return c.id
