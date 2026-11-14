"""Bacaan Console terikat ruang layanan; statistik bersumber catatan nyata."""
from dataclasses import dataclass
from datetime import datetime,timedelta,time,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select,func,case,cast,String,Date,text,or_,and_,literal,union_all,table,column,Integer,DateTime
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.monitoring import KejadianPemakaian as E,SumberMonitoring,PembukaanMasuk,PemulihanAkun
from hmu_identitas.ruang_data import RuangData
from hmu_core import User,Perusahaan,KeanggotaanPerusahaan,LokasiPabrik,Warehouse,PenempatanGudang,AksesLokasiAnggota,AksesGudangAnggota,Pelanggan
from app.models import ActivityLog
from app.models.portal import PortalAccount
from app.config import settings

APLIKASI=('padiflow','teraflow','portal')
JENIS=('staf','pelanggan','timbangan_lama','staf_belum_login')

@dataclass(frozen=True)
class FilterMonitoring:
    company_id:int|None=None
    hari:int=30
    aplikasi:str=''
    def __post_init__(self):
        if self.company_id is not None and (type(self.company_id) is not int or not 0<self.company_id<=2147483647):raise ValueError('Perusahaan tidak valid.')
        if self.hari not in (7,30,90) or self.aplikasi not in ('',*APLIKASI):raise ValueError('Periode/aplikasi tidak valid.')


def sekarang():return datetime.now(timezone.utc)
def label_role(role):
    if P.super_saja(role):return P.SUPERADMIN
    if P.admin_keatas(role):return P.ADMIN
    return P.normal(role)


async def cakupan(db,company_id=None):
    rows=list(await db.scalars(select(Perusahaan).order_by(Perusahaan.nama,Perusahaan.id)))
    ruang=RuangData.lingkungan()
    if company_id is not None and not any(c.id==company_id for c in rows):raise LookupError('Perusahaan tidak ditemukan.')
    local=next((c for c in rows if ruang and c.id==ruang.company_id),None)
    terpilih=next((c for c in rows if c.id==company_id),None) if company_id else local
    tersedia=bool(local and (company_id is None or company_id==local.id))
    return dict(perusahaan=[dict(id=c.id,nama=c.nama,terhubung=bool(local and c.id==local.id)) for c in rows],
                company_id=terpilih.id if terpilih else None,nama=terpilih.nama if terpilih else '',
                tersedia=tersedia,jumlah_terhubung=int(local is not None),jumlah_registry=len(rows))


def pastikan_lokal(cid):
    ruang=RuangData.lingkungan()
    if not ruang:raise PermissionError('Identitas ruang perusahaan belum dikonfigurasi.')
    ruang.pastikan_perusahaan(cid)


async def timbangan_siap(db):
    # PadiFlow dapat berdiri sebelum migrasi aplikasi TeraFlow dijalankan.
    # Stub tabel lama tidak boleh dianggap sebagai profil tertaut yang siap.
    cols=set(await db.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='timbangan_akun'")))
    return {'id','akun_id','user_id','nama','username','role','status','token_version','terakhir_login'}.issubset(cols)


async def sumber_akun(db,cid):
    """Union identitas lokal. Filter dan LIMIT dikerjakan database sebelum nama dimuat."""
    shared=select(case((Akun.id.is_(None),'staf_belum_login'),else_='staf').label('jenis'),
        case((Akun.id.is_(None),User.id),else_=Akun.id).label('id'),User.id.label('user_id'),User.nama.label('nama'),
        func.coalesce(Akun.username,'').label('username'),User.role.label('peran'),
        and_(Akun.status=='aktif',func.lower(User.status)=='aktif').label('aktif'),Akun.terakhir_login.label('terakhir_login'))        .select_from(User).outerjoin(Akun,Akun.user_id==User.id)
    last=select(func.max(E.waktu)).where(E.company_id==cid,E.jenis_akun=='pelanggan',E.akun_id==PortalAccount.id,E.jenis=='login',E.kode=='berhasil').correlate(PortalAccount).scalar_subquery()
    portal=select(literal('pelanggan').label('jenis'),PortalAccount.id.label('id'),cast(literal(None),Integer).label('user_id'),
        Pelanggan.nama_pelanggan.label('nama'),PortalAccount.username.label('username'),literal('pelanggan').label('peran'),PortalAccount.active.label('aktif'),last.label('terakhir_login')).join(Pelanggan,Pelanggan.id==PortalAccount.pelanggan_id)
    queries=[shared,portal]
    if await timbangan_siap(db):
        t=table('timbangan_akun',column('id',Integer),column('akun_id',Integer),column('user_id',Integer),column('nama',String),column('username',String),column('role',String),column('status',String),column('terakhir_login',DateTime(timezone=True)))
        queries.append(select(literal('timbangan_lama').label('jenis'),t.c.id.label('id'),t.c.user_id.label('user_id'),t.c.nama.label('nama'),t.c.username.label('username'),t.c.role.label('peran'),
            and_(t.c.status=='aktif',or_(User.id.is_(None),func.lower(User.status)=='aktif')).label('aktif'),t.c.terakhir_login.label('terakhir_login')).select_from(t).outerjoin(User,User.id==t.c.user_id).where(t.c.akun_id.is_(None)))
    return union_all(*queries).subquery('identitas_lokal')


async def daftar_akun(db,*,company_id=None,cari='',jenis='',status='',halaman=1,limit=30):
    if len(cari)>100 or jenis not in ('',*JENIS) or status not in ('','aktif','nonaktif','belum_login') or not 1<=halaman<=100000 or not 1<=limit<=100:raise ValueError('Pencarian pengguna tidak valid.')
    scope=await cakupan(db,company_id)
    if not scope['tersedia']:return dict(cakupan=scope,pengguna=[],total=0,halaman=1,halaman_total=1)
    cid=scope['company_id'];u=await sumber_akun(db,cid);where=[]
    if jenis:where.append(u.c.jenis==jenis)
    if status=='aktif':where.append(u.c.aktif.is_(True))
    if status=='nonaktif':where.append(func.coalesce(u.c.aktif,False).is_(False))
    if status=='belum_login':where.append(u.c.terakhir_login.is_(None))
    if cari:
        pattern='%'+cari.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        where.append(or_(u.c.nama.ilike(pattern,escape='\\'),u.c.username.ilike(pattern,escape='\\'),cast(u.c.id,String)==cari.strip()))
    total=await db.scalar(select(func.count()).select_from(u).where(*where))
    halaman_total=max(1,(total+limit-1)//limit);halaman=min(halaman,halaman_total)
    records=(await db.execute(select(u).where(*where).order_by(func.lower(u.c.nama),u.c.jenis,u.c.id).offset((halaman-1)*limit).limit(limit))).mappings().all()
    ids={}
    for r in records:ids.setdefault(r['jenis'],[]).append(r['id'])
    seen={}
    if records:
        checks=[and_(E.jenis_akun==kind,E.akun_id.in_(values)) for kind,values in ids.items()]
        seen={(k,i):t for k,i,t in (await db.execute(select(E.jenis_akun,E.akun_id,func.max(E.waktu)).where(E.company_id==cid,E.jenis=='interaksi',or_(*checks)).group_by(E.jenis_akun,E.akun_id))).all()}
    result=[]
    for r in records:
        data=dict(r);data['aktif']=bool(data['aktif']);data['peran']=label_role(data['peran']);last=seen.get((data['jenis'],data['id']))
        data.update(company_id=cid,terakhir_login=data['terakhir_login'].isoformat() if data['terakhir_login'] else None,terlihat=last.isoformat() if last else None,aktif_sekarang=bool(last and last>=sekarang()-timedelta(minutes=5)))
        result.append(data)
    return dict(cakupan=scope,pengguna=result,total=total,halaman=halaman,halaman_total=max(1,(total+limit-1)//limit))


async def ringkasan(db,f:FilterMonitoring):
    scope=await cakupan(db,f.company_id);now=sekarang();tz=ZoneInfo(settings.app_timezone)
    today=now.astimezone(tz).date();start=datetime.combine(today-timedelta(days=f.hari-1),time.min,tz).astimezone(timezone.utc)
    empty=dict(cakupan=scope,diperbarui=now.isoformat(),hari=f.hari,aplikasi=f.aplikasi,zona=settings.app_timezone,
        metrik=None,sumber=[],harian=[],per_aplikasi=[],fitur=[],kendala=[],pengguna_aktif=[],cakupan_mulai=None)
    if not scope['tersedia']:return empty
    cid=scope['company_id'];where=[E.company_id==cid,E.waktu>=start,E.waktu<=now]
    if f.aplikasi:where.append(E.aplikasi==f.aplikasi)
    subject=func.concat(E.jenis_akun,':',cast(E.akun_id,String))
    manual=[*where,E.jenis=='interaksi',E.akun_id>0]
    def batas(days):return datetime.combine(today-timedelta(days=days-1),time.min,tz).astimezone(timezone.utc)
    activity={}
    for key,lower in [('aktif_sekarang',now-timedelta(minutes=5)),('aktif_hari',batas(1)),('aktif_minggu',batas(7)),('aktif_bulan',batas(30))]:
        # Metrik hari/minggu/bulan selalu memakai rentang definisinya sendiri,
        # bukan dipotong tanggal grafik 7 hari yang sedang dipilih.
        w=[E.company_id==cid,E.jenis=='interaksi',E.akun_id>0,E.waktu>=lower,E.waktu<=now]
        if f.aplikasi:w.append(E.aplikasi==f.aplikasi)
        activity[key]=await db.scalar(select(func.count(func.distinct(subject))).where(*w))
    identities=await sumber_akun(db,cid)
    account_counts=(await db.execute(select(func.count(),func.sum(case((identities.c.jenis!='staf_belum_login',1),else_=0)),func.sum(case((identities.c.aktif.is_(True),1),else_=0))).select_from(identities))).one()
    sources=list(await db.scalars(select(SumberMonitoring).where(SumberMonitoring.company_id==cid)))
    applicable=[s for s in sources if not f.aplikasi or s.aplikasi==f.aplikasi]
    first=min((s.mulai for s in applicable),default=None)
    events=await db.scalar(select(func.count()).select_from(E).where(*manual))
    posts=[*where,E.jenis=='respons_web',E.metode.in_(['POST','PUT','PATCH','DELETE']),E.layar!='masuk']
    response=(await db.execute(select(func.count(),func.sum(case((func.substr(E.kode,1,1).in_(['2','3']),1),else_=0)),
        func.sum(case((E.kode.in_(['401','403']),1),else_=0)),func.sum(case((E.kode.in_(['409','422']),1),else_=0)),
        func.sum(case((func.substr(E.kode,1,1)=='5',1),else_=0))).where(*posts))).one()
    p95=await db.scalar(select(func.percentile_cont(.95).within_group(E.durasi_ms)).where(*posts,E.durasi_ms.isnot(None)))
    errors=await db.scalar(select(func.count()).select_from(E).where(*where,or_(E.jenis=='galat_browser',and_(E.jenis=='respons_web',func.substr(E.kode,1,1)=='5'))))
    loginfails=await db.scalar(select(func.count()).select_from(E).where(*where,E.jenis=='login',E.kode!='berhasil'))
    tanggal_event=cast(func.timezone(settings.app_timezone,E.waktu),Date)
    perday=(await db.execute(select(tanggal_event,func.count(func.distinct(subject)),func.count()).where(*manual).group_by(tanggal_event))).all()
    days={d:(u,n) for d,u,n in perday};daily=[]
    for n in range(f.hari):
        day=today-timedelta(days=f.hari-1-n);known=first is not None and day>=first.astimezone(tz).date()
        u,c=days.get(day,(0,0));daily.append(dict(tanggal=day.isoformat(),pengguna=u if known else None,interaksi=c if known else None))
    byapp=(await db.execute(select(E.aplikasi,func.count(func.distinct(subject)),func.count()).where(*manual).group_by(E.aplikasi))).all()
    features=(await db.execute(select(E.aplikasi,E.layar,func.count(),func.count(func.distinct(subject))).where(*manual).group_by(E.aplikasi,E.layar).order_by(func.count().desc()).limit(15))).all()
    issues=(await db.execute(select(E.aplikasi,E.jenis,E.kode,func.count(),func.count(func.distinct(case((E.akun_id>0,subject),else_=None))),func.max(E.waktu)).where(*where,or_(and_(E.jenis=='login',E.kode!='berhasil'),E.jenis=='galat_browser',and_(E.jenis=='respons_web',func.substr(E.kode,1,1)=='5'))).group_by(E.aplikasi,E.jenis,E.kode).order_by(func.count().desc()).limit(15))).all()
    latest=(await db.execute(select(E.jenis_akun,E.akun_id,func.max(E.waktu),func.count(),func.count(func.distinct(cast(func.timezone(settings.app_timezone,E.waktu),Date)))).where(*manual).group_by(E.jenis_akun,E.akun_id).order_by(func.max(E.waktu).desc()).limit(10))).all()
    checks=[and_(identities.c.jenis==k,identities.c.id==i) for k,i,*_ in latest]
    names={(a['jenis'],a['id']):dict(a) for a in (await db.execute(select(identities).where(or_(*checks)))).mappings()} if checks else {}
    audit_count=await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.waktu_perubahan>=start,ActivityLog.waktu_perubahan<=now,ActivityLog.changed_by.isnot(None),~ActivityLog.table_name.in_(['users','produksi_akun','portal_accounts','hmu_company_memberships','hmu_factory_sites','hmu_companies','hmu_warehouse_sites','setelan_pabrik'])))
    return dict(empty,metrik=dict(activity,total_identitas=int(account_counts[0]),total_akun=int(account_counts[1] or 0),akun_aktif=int(account_counts[2] or 0),
        interaksi=events,respons_simpan=int(response[0]),respons_diterima=int(response[1] or 0),akses_ditolak=int(response[2] or 0),validasi=int(response[3] or 0),server_error_simpan=int(response[4] or 0),p95_ms=round(p95) if p95 is not None else None,
        galat=errors,login_gagal=loginfails,catatan_audit=audit_count),
        cakupan_mulai=first.isoformat() if first else None,
        sumber=[dict(aplikasi=app,tercatat=s is not None,mulai=s.mulai.isoformat() if s else None,terakhir=s.terakhir.isoformat() if s else None,versi=s.versi if s else '',segar=bool(s and s.terakhir>=now-timedelta(seconds=120))) for app in APLIKASI for s in [next((r for r in sources if r.aplikasi==app),None)]],
        harian=daily,per_aplikasi=[dict(aplikasi=a,pengguna=u,interaksi=n) for a,u,n in byapp],
        fitur=[dict(aplikasi=a,layar=l,interaksi=n,pengguna=u) for a,l,n,u in features],
        kendala=[dict(aplikasi=a,jenis=j,kode=k,jumlah=n,pengguna=u,terakhir=t.isoformat()) for a,j,k,n,u,t in issues],
        pengguna_aktif=[dict(jenis=k,id=i,nama=names.get((k,i),{}).get('nama','Akun tidak tersedia'),username=names.get((k,i),{}).get('username',''),company_id=cid,terakhir=t.isoformat(),interaksi=n,hari_aktif=d) for k,i,t,n,d in latest])


async def akun(db,cid,jenis,aid,*,kunci=False):
    pastikan_lokal(cid)
    if jenis not in JENIS or type(aid) is not int or not 0<aid<=2147483647:raise LookupError('Akun tidak ditemukan.')
    user=None;row=None
    if jenis=='staf':
        row=await db.scalar(select(Akun).where(Akun.id==aid).execution_options(populate_existing=True))
        if row:
            if kunci:
                await db.scalar(select(User).where(User.id==row.user_id).with_for_update(key_share=True).execution_options(populate_existing=True))
                row=await db.scalar(select(Akun).where(Akun.id==aid).with_for_update(of=Akun,key_share=True).execution_options(populate_existing=True))
            user=row.user
            data=dict(id=row.id,jenis=jenis,user_id=user.id,nama=user.nama,username=row.username,peran=label_role(user.role),aktif=row.aktif,
                status_akun=row.status,status_pengguna=user.status,versi=row.token_version,wajib_ganti=row.harus_ganti_sandi,
                terakhir_login=row.terakhir_login.isoformat() if row.terakhir_login else None)
    elif jenis=='pelanggan':
        q=select(PortalAccount).where(PortalAccount.id==aid).execution_options(populate_existing=True)
        row=await db.scalar(q.with_for_update() if kunci else q)
        if row:
            name=await db.scalar(select(Pelanggan.nama_pelanggan).where(Pelanggan.id==row.pelanggan_id))
            data=dict(id=row.id,jenis=jenis,user_id=None,nama=name,username=row.username,peran='pelanggan',aktif=row.active,versi=row.token_version,status_akun='aktif' if row.active else 'nonaktif',status_pengguna='',wajib_ganti=False,terakhir_login=None)
    elif jenis=='timbangan_lama':
        if await timbangan_siap(db):
            row=(await db.execute(text('SELECT id,user_id,nama,username,role,status,token_version,terakhir_login FROM timbangan_akun WHERE id=:id AND akun_id IS NULL'+(' FOR UPDATE' if kunci else '')),{'id':aid})).mappings().one_or_none()
        if row:
            user=await db.get(User,row['user_id']) if row['user_id'] else None
            data=dict(id=aid,jenis=jenis,user_id=row['user_id'],nama=row['nama'],username=row['username'],peran=label_role(row['role']),aktif=row['status']=='aktif' and (user is None or user.status=='aktif'),versi=row['token_version'],status_akun=row['status'],status_pengguna=user.status if user else '',wajib_ganti=False,terakhir_login=row['terakhir_login'].isoformat() if row['terakhir_login'] else None)
    else:
        q=select(User).where(User.id==aid)
        user=await db.scalar(q.with_for_update() if kunci else q)
        if user and not await db.scalar(select(Akun.id).where(Akun.user_id==aid)):
            row=user;data=dict(id=aid,jenis=jenis,user_id=user.id,nama=user.nama,username='',peran=label_role(user.role),aktif=False,versi=0,status_akun='belum_ada',status_pengguna=user.status,wajib_ganti=False,terakhir_login=None)
    if row is None:raise LookupError('Akun tidak ditemukan.')
    data['company_id']=cid
    gen=await db.scalar(select(PembukaanMasuk.generasi).where(PembukaanMasuk.company_id==cid,PembukaanMasuk.jenis_akun==jenis,PembukaanMasuk.akun_id==aid))
    data['generasi']=gen or 0
    data['jumlah_pemulihan']=await db.scalar(select(func.count()).select_from(PemulihanAkun).where(PemulihanAkun.company_id==cid,PemulihanAkun.jenis_akun==jenis,PemulihanAkun.akun_id==aid))
    data['pemulihan_terakhir']=await db.scalar(select(PemulihanAkun.id).where(PemulihanAkun.company_id==cid,PemulihanAkun.jenis_akun==jenis,PemulihanAkun.akun_id==aid).order_by(PemulihanAkun.kedaluwarsa.desc()).limit(1))
    membership=None
    if data['user_id']:
        q=select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.company_id==cid,KeanggotaanPerusahaan.user_id==data['user_id']).execution_options(populate_existing=True)
        membership=await db.scalar(q.with_for_update() if kunci else q)
    data['keanggotaan']=dict(id=membership.id,aktif=membership.aktif,peran=membership.peran,diubah=membership.updated_at.isoformat()) if membership else None
    return data
