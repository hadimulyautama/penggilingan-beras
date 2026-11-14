"""API administrasi pusat. Tidak menerima cookie CMS atau token API operator."""
import re,hmac,math
from urllib.parse import urlencode,urlsplit
from fastapi import APIRouter,Depends,Request,HTTPException
from fastapi.responses import RedirectResponse,JSONResponse
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from sqlalchemy import select,func,or_
from sqlalchemy.exc import IntegrityError
from hmu_identitas import peran as P
from app.config import settings
from app.database import SessionLocal
from app.models import ActivityLog
from hmu_core import Perusahaan,KeanggotaanPerusahaan,User,LokasiPabrik,PenempatanGudang
from app.services import console_auth as auth,keanggotaan as svc,organisasi_master as master
from app.web.security import akun_opsional

class RuteConsole(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def private(request):
            try:
                if request.url.path=='/internal/console/masuk':
                    # Periksa identitas klien sebelum parsing badan (termasuk input sandi).
                    key=settings.console_login_secret.get_secret_value()
                    supplied=request.headers.get('x-console-login-key','')
                    if len(key)<32:raise HTTPException(503,dict(kode='konfigurasi'))
                    if not hmac.compare_digest(key.encode(),supplied.encode()):raise HTTPException(403,dict(kode='klien'))
                    if len(await request.body())>8192:raise HTTPException(413,dict(kode='isian'))
                response=await original(request)
            except HTTPException as e:response=JSONResponse(dict(detail=e.detail),status_code=e.status_code,headers=e.headers)
            except RequestValidationError as e:
                # Pydantic menyertakan input dalam errors(); sandi tidak boleh dipantulkan.
                detail=(dict(kode='isian') if request.url.path=='/internal/console/masuk' else
                    'Isian pemulihan tidak valid. Periksa tautan dan isi sandi minimal 8 karakter.' if request.url.path.startswith('/pemulihan/') else jsonable_encoder(e.errors()))
                response=JSONResponse(dict(detail=detail),status_code=422)
            response.headers['Cache-Control']='no-store, private'
            response.headers['Pragma']='no-cache'
            response.headers['X-Robots-Tag']='noindex, nofollow'
            return response
        return private


router=APIRouter(route_class=RuteConsole)


def callback():
    url=settings.console_website_url.rstrip('/')
    u=urlsplit(url)
    if not url or u.scheme!='https' or not u.hostname or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
        raise HTTPException(503,'Console Center belum dikonfigurasi.')
    return url+'/console/kembali'


@router.get('/console/otorisasi')
async def otorisasi(request:Request,tantangan:str,state:str,akun=Depends(akun_opsional)):
    tujuan=callback()
    if akun is None:
        return RedirectResponse('/masuk?'+urlencode(dict(next=request.url.path+'?'+request.url.query)),status_code=303)
    if not akun.is_super:raise HTTPException(403,'Console Center hanya untuk Super Admin.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{22,100}',state):raise HTTPException(422,'Keadaan masuk tidak valid.')
    try:
        async with SessionLocal() as db:
            kode=await auth.terbitkan(db,akun_id=akun.id,versi=akun.token_version,tantangan=tantangan);await db.commit()
    except (auth.TolakConsole,ValueError) as e:raise HTTPException(403,str(e)) from e
    r=RedirectResponse(tujuan+'?'+urlencode(dict(kode=kode,state=state)),status_code=303)
    r.headers['Cache-Control']='no-store';r.headers['Referrer-Policy']='no-referrer';return r


class Tukar(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kode:str
    verifier:str


@router.post('/internal/console/tukar')
async def tukar(data:Tukar):
    callback()
    try:
        async with SessionLocal() as db:
            token=await auth.tukar(db,kode=data.kode,verifier=data.verifier);await db.commit()
    except auth.TolakConsole as e:raise HTTPException(401,str(e)) from e
    return dict(token=token,berlaku_detik=3600)


class MasukLangsung(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=1,max_length=50)
    sandi:SecretStr=Field(min_length=1,max_length=1024)
    jejak:str=Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/internal/console/masuk')
async def masuk_langsung(data:MasukLangsung,request:Request):
    callback()
    from hmu_identitas import masuk as identitas
    from app.web import gerbang_masuk as gerbang
    from app.monitoring import petunjuk_masuk,catat_login
    from app.services import console_masuk
    uname=identitas.normal_username(data.username)
    # Jejak IP dibuat HMAC oleh server Console yang identitasnya sudah diperiksa.
    # Namespace terpisah: penolakan Console tidak mengunci sesi/operator harian.
    sumber='console:'+data.jejak
    from app.services.console_pembatas import pembatas
    delay=pembatas.mulai(data.jejak)
    if delay is not None:raise HTTPException(429,dict(kode='sibuk'),headers={'Retry-After':str(math.ceil(delay))})
    try:
        await petunjuk_masuk(request,uname,gerbang)
        sisa=gerbang.boleh_coba(uname,sumber)
        if sisa is not None:
            catat_login(request,'ditahan')
            raise HTTPException(429,dict(kode='ditahan'),headers={'Retry-After':str(math.ceil(sisa))})
        try:
            async with SessionLocal() as db:
                result=await console_masuk.masuk(db,uname,data.sandi.get_secret_value())
                await db.commit()
        except console_masuk.Ditolak as e:
            if e.kode=='kredensial':gerbang.catat_gagal(uname,sumber)
            else:gerbang.catat_sandi_benar(uname,sumber)
            catat_login(request,'nonaktif' if e.kode=='nonaktif' else 'peran' if e.kode in ('peran','wajib_sandi') else 'kredensial')
            raise HTTPException(e.status,dict(kode=e.kode)) from None
        except auth.TolakConsole:
            raise HTTPException(403,dict(kode='peran')) from None
        gerbang.catat_berhasil(uname,sumber);catat_login(request,'berhasil')
        return result

    finally:pembatas.selesai()

async def pelaku(request:Request):
    callback()
    raw=request.headers.get('authorization','')
    token=raw[7:] if raw.startswith('Bearer ') else ''
    try:
        async with SessionLocal() as db:
            row,a=await auth.periksa(db,token);return dict(ruang=svc.RuangAdministrasi(a.user.id),sesi_id=row.id,nama=a.user.nama)
    except auth.TolakConsole as e:raise HTTPException(401,str(e)) from e


@router.get('/internal/console/saya')
async def saya(actor=Depends(pelaku)):return dict(nama=actor['nama'])


@router.post('/internal/console/keluar')
async def keluar(actor=Depends(pelaku)):
    from app.models import SesiConsole
    async with SessionLocal() as db:
        row=await db.get(SesiConsole,actor['sesi_id']);row.dicabut=True;await db.commit()
    return dict(ok=True)


@router.get('/internal/console/perusahaan')
async def perusahaan(cari:str='',status:str='',halaman:int=1,actor=Depends(pelaku)):
    if halaman<1 or halaman>100000 or len(cari)>100 or status not in ('','aktif','nonaktif'):raise HTTPException(422,'Pencarian perusahaan tidak valid.')
    async with SessionLocal() as db:
        q=select(Perusahaan)
        if cari:q=q.where(or_(Perusahaan.nama.ilike('%'+cari+'%'),Perusahaan.kode.ilike('%'+cari+'%')))
        if status:q=q.where(Perusahaan.aktif.is_(status=='aktif'))
        total=await db.scalar(select(func.count()).select_from(q.subquery()))
        stats=dict((await db.execute(select(Perusahaan.aktif,func.count()).group_by(Perusahaan.aktif))).all())
        rows=list(await db.scalars(q.order_by(Perusahaan.id).offset((halaman-1)*20).limit(20)))
        ids=[x.id for x in rows]
        counts=[]
        for model in (LokasiPabrik,PenempatanGudang,KeanggotaanPerusahaan):
            counts.append(dict((await db.execute(select(model.company_id,func.count()).where(model.company_id.in_(ids)).group_by(model.company_id))).all()))
    return dict(perusahaan=[dict(id=x.id,kode=x.kode,nama=x.nama,aktif=x.aktif,lokasi=counts[0].get(x.id,0),gudang=counts[1].get(x.id,0),anggota=counts[2].get(x.id,0)) for x in rows],
        total=total,halaman=halaman,halaman_total=max(1,(total+19)//20),statistik=dict(total=sum(stats.values()),aktif=stats.get(True,0),nonaktif=stats.get(False,0)))


@router.get('/internal/console/calon-admin')
async def calon_admin(cari:str='',halaman:int=1,user_id:int|None=None,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:return await svc.calon_admin(db,cari=cari,halaman=halaman,user_id=user_id)
    except ValueError as e:raise HTTPException(422,str(e)) from e


@router.get('/internal/console/pengguna')
async def direktori(cari:str='',halaman:int=1,actor=Depends(pelaku)):
    if len(cari)>100 or not 1<=halaman<=100000:raise HTTPException(422,'Pencarian pengguna tidak valid.')
    async with SessionLocal() as db:
        q=select(User).where(User.id.in_(select(KeanggotaanPerusahaan.user_id)))
        if cari:q=q.where(User.nama.ilike('%'+cari+'%'))
        rows=list(await db.scalars(q.order_by(User.nama,User.id).offset((halaman-1)*50).limit(51)))
        memberships=(await db.execute(select(KeanggotaanPerusahaan,Perusahaan.nama).join(Perusahaan,Perusahaan.id==KeanggotaanPerusahaan.company_id)
            .where(KeanggotaanPerusahaan.user_id.in_([u.id for u in rows[:50]])))).all()
    return dict(pengguna=[dict(id=u.id,nama=u.nama,keanggotaan=[dict(company_id=m.company_id,perusahaan=n,peran=m.peran,aktif=m.aktif) for m,n in memberships if m.user_id==u.id]) for u in rows[:50]],lanjut=halaman+1 if len(rows)>50 else None)


@router.get('/internal/console/audit')
async def jejak_pusat(sebelum:int|None=None,actor=Depends(pelaku)):
    async with SessionLocal() as db:
        q=select(ActivityLog,User.nama).outerjoin(User,User.id==ActivityLog.changed_by).where(ActivityLog.aksi.in_(
            ['keanggotaan_perusahaan','master_organisasi','penetapan_gudang','pengaturan_perusahaan','penetapan_perusahaan_lama','penetapan_ruang_perusahaan','console_bantuan']))
        if sebelum:q=q.where(ActivityLog.id<sebelum)
        rows=(await db.execute(q.order_by(ActivityLog.id.desc()).limit(51))).all()
    return dict(catatan=[dict(id=x.id,pelaku=n or 'Sistem',waktu=x.waktu_perubahan.isoformat(),alasan=x.alasan_perubahan,sebelum=x.old_value,sesudah=x.new_value) for x,n in rows[:50]],lanjut=rows[49][0].id if len(rows)>50 else None)


@router.get('/internal/console/perusahaan/{company_id:int}')
async def rincian(company_id:int,cari_pengguna:str="",anggota_id:int|None=None,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:
            data=await svc.rincian(db,ruang=actor['ruang'],company_id=company_id,cari_pengguna=cari_pengguna,anggota_id=anggota_id)
            from hmu_identitas.ruang_data import RuangData
            lokal=RuangData.lingkungan()
            data['ruang_data_lokal']=lokal is not None and lokal.company_id==company_id
            data['ruang_data_ditetapkan']=lokal is not None
            return data
    except (PermissionError,master.OrganisasiError) as e:raise HTTPException(403,str(e)) from e


class Anggota(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    user_id:int
    peran:str
    aktif:bool
    lokasi:list[dict]
    bukti:str
    alasan:str


@router.post('/internal/console/perusahaan/{company_id:int}/anggota')
async def anggota(company_id:int,data:Anggota,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:
            result=await svc.simpan(db,ruang=actor['ruang'],company_id=company_id,**data.model_dump());await db.commit()
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (master.OrganisasiError,IntegrityError) as e:
        raise HTTPException(422,str(e) if isinstance(e,master.OrganisasiError) else 'Data anggota berubah. Baca data terbaru.') from e
    return result


@router.get('/internal/console/perusahaan/{company_id:int}/audit')
async def audit(company_id:int,sebelum:int|None=None,actor=Depends(pelaku)):
    async with SessionLocal() as db:
        await svc.otorisasi(db,actor['ruang'],company_id)
        q=select(ActivityLog,User.nama).outerjoin(User,User.id==ActivityLog.changed_by).where(
            ActivityLog.table_name=='hmu_company_memberships',ActivityLog.aksi=='keanggotaan_perusahaan',
            ActivityLog.record_id.in_(select(KeanggotaanPerusahaan.id).where(KeanggotaanPerusahaan.company_id==company_id)))
        if sebelum is not None:q=q.where(ActivityLog.id<sebelum)
        rows=list((await db.execute(q.order_by(ActivityLog.id.desc()).limit(51))).all())
    return dict(catatan=[dict(id=x.id,pelaku=n or 'Tidak diketahui',waktu=x.waktu_perubahan.isoformat(),alasan=x.alasan_perubahan,
        sebelum=x.old_value,sesudah=x.new_value) for x,n in rows[:50]],lanjut=rows[49][0].id if len(rows)>50 else None)


class MasterBaru(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    nama:str
    kode:str
    alasan:str
    alamat:str=''


class MasterUbah(MasterBaru):
    aktif:bool
    bukti:str


class PerusahaanBaru(MasterBaru):
    admin_user_id:int|None=None


@router.post('/internal/console/perusahaan/{company_id:int}/identitas')
async def identitas_perusahaan(company_id:int,data:MasterUbah,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:
            row=await master.simpan(db,user_id=actor['ruang'].user_id,objek='perusahaan',identitas=company_id,
                nama=data.nama,kode=data.kode,aktif=data.aktif,alasan=data.alasan,bukti=data.bukti)
            await db.commit();return dict(id=row.id)
    except (master.OrganisasiError,IntegrityError) as e:raise HTTPException(422,str(e) if isinstance(e,master.OrganisasiError) else 'Data perusahaan berubah.') from e


@router.post('/internal/console/perusahaan')
async def tambah_perusahaan(data:PerusahaanBaru,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:
            if data.admin_user_id is not None:
                from hmu_identitas.model import Akun
                if not await db.scalar(select(Akun.id).join(User,User.id==Akun.user_id).where(
                    Akun.user_id==data.admin_user_id,Akun.status=='aktif',func.lower(User.status)=='aktif')):
                    raise master.OrganisasiError('Admin pertama harus mempunyai akun masuk aktif yang sudah ada.')
            row=await master.simpan(db,user_id=actor['ruang'].user_id,objek='perusahaan',nama=data.nama,kode=data.kode,aktif=True,alasan=data.alasan)
            if data.admin_user_id is not None:
                await db.flush()
                await svc.simpan(db,ruang=actor['ruang'],company_id=row.id,user_id=data.admin_user_id,peran=P.ADMIN,
                    aktif=True,lokasi=[],bukti=svc.sidik(None),alasan=data.alasan)
            await db.commit();return dict(id=row.id)
    except (master.OrganisasiError,IntegrityError) as e:raise HTTPException(422,str(e) if isinstance(e,master.OrganisasiError) else 'Kode sudah digunakan.') from e


@router.post('/internal/console/perusahaan/{company_id:int}/lokasi')
async def tambah_lokasi(company_id:int,data:MasterBaru,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:
            row=await master.simpan(db,user_id=actor['ruang'].user_id,objek='lokasi',company_id=company_id,nama=data.nama,kode=data.kode,aktif=True,alamat=data.alamat,alasan=data.alasan)
            await db.commit();return dict(id=row.id)
    except (master.OrganisasiError,IntegrityError) as e:raise HTTPException(422,str(e) if isinstance(e,master.OrganisasiError) else 'Kode sudah digunakan.') from e


@router.get('/internal/console/fasilitas')
async def fasilitas(actor=Depends(pelaku)):
    from app.services.organisasi_rencana import fasilitas
    async with SessionLocal() as db:
        companies,sites,bindings=await master.baca(db);wh,_=await fasilitas(db)
    return dict(perusahaan=[dict(id=c.id,nama=c.nama,kode=c.kode,aktif=c.aktif) for c in companies],
        lokasi=[dict(id=s.id,company_id=s.company_id,nama=s.nama,kode=s.kode,aktif=s.aktif) for s in sites],
        gudang=[dict(id=w.id,nama=w.nama_gudang,aktif=w.aktif) for w in wh],
        penetapan=[dict(warehouse_id=b.warehouse_id,company_id=b.company_id,lokasi_pabrik_id=b.lokasi_pabrik_id) for b in bindings])


@router.get('/internal/console/penetapan')
async def pratinjau_penetapan(request:Request,lokasi_pabrik_id:int,actor=Depends(pelaku)):
    from dataclasses import asdict
    from app.services import organisasi_rencana as r
    try:
        ids=[int(i) for i in request.query_params.getlist('warehouse_id')]
        async with SessionLocal() as db:plan=await r.pratinjau(db,lokasi_pabrik_id=lokasi_pabrik_id,warehouse_ids=ids)
        return dict(rencana=asdict(plan),bisa=plan.bisa_diterapkan,baru=plan.jumlah_baru,
            bukti=r.buat_bukti(plan,user_id=actor['ruang'].user_id) if plan.bisa_diterapkan and plan.jumlah_baru else '')
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (master.OrganisasiError,ValueError) as e:raise HTTPException(422,str(e)) from e


class Penetapan(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    bukti:str
    alasan:str
    konfirmasi:bool


@router.post('/internal/console/penetapan')
async def terapkan_penetapan(data:Penetapan,actor=Depends(pelaku)):
    from app.services.organisasi_rencana import terapkan
    if not data.konfirmasi:raise HTTPException(422,'Periksa dan konfirmasi pratinjau penetapan.')
    try:
        async with SessionLocal() as db:
            result=await terapkan(db,user_id=actor['ruang'].user_id,bukti=data.bukti,alasan=data.alasan);await db.commit()
        return dict(lokasi_pabrik_id=result.lokasi_pabrik_id)
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (master.OrganisasiError,IntegrityError) as e:raise HTTPException(422,str(e) if isinstance(e,master.OrganisasiError) else 'Data penetapan berubah.') from e

# Layar kerja Admin Sistem: hanya API Console, tidak menerima sesi operator.
from app.services import console_monitoring as monitoring,console_bantuan as bantuan

@router.get('/internal/console/monitoring')
async def monitoring_ringkas(company_id:int|None=None,hari:int=30,aplikasi:str='',actor=Depends(pelaku)):
    try:
        f=monitoring.FilterMonitoring(company_id,hari,aplikasi)
        async with SessionLocal() as db:return await monitoring.ringkasan(db,f)
    except LookupError as e:raise HTTPException(404,str(e))
    except (ValueError,PermissionError) as e:raise HTTPException(422,str(e))

@router.get('/internal/console/monitoring/pengguna')
async def monitoring_pengguna(company_id:int|None=None,cari:str='',jenis:str='',status:str='',halaman:int=1,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:return await monitoring.daftar_akun(db,company_id=company_id,cari=cari,jenis=jenis,status=status,halaman=halaman)
    except LookupError as e:raise HTTPException(404,str(e))
    except (ValueError,PermissionError) as e:raise HTTPException(422,str(e))

@router.get('/internal/console/monitoring/perusahaan/{cid:int}/pengguna/{jenis}/{aid:int}')
async def monitoring_diagnosis(cid:int,jenis:str,aid:int,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:return await bantuan.diagnosis(db,cid=cid,jenis=jenis,aid=aid)
    except LookupError as e:raise HTTPException(404,str(e))
    except PermissionError as e:raise HTTPException(403,str(e))

class PratinjauBantuan(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    aksi:str
    alasan:str

class TerapkanBantuan(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    plan_id:str
    konfirmasi:bool

@router.post('/internal/console/monitoring/perusahaan/{cid:int}/pengguna/{jenis}/{aid:int}/pratinjau')
async def monitoring_pratinjau(cid:int,jenis:str,aid:int,data:PratinjauBantuan,actor=Depends(pelaku)):
    try:
        async with SessionLocal() as db:
            result=await bantuan.pratinjau(db,cid=cid,jenis=jenis,aid=aid,pelaku_id=actor['ruang'].user_id,aksi=data.aksi,alasan=data.alasan)
            await db.commit();return result
    except LookupError as e:raise HTTPException(404,str(e))
    except PermissionError as e:raise HTTPException(403,str(e))
    except ValueError as e:raise HTTPException(422,str(e))

@router.post('/internal/console/monitoring/perusahaan/{cid:int}/pengguna/{jenis}/{aid:int}/terapkan')
async def monitoring_terapkan(cid:int,jenis:str,aid:int,data:TerapkanBantuan,actor=Depends(pelaku)):
    if data.konfirmasi is not True:raise HTTPException(422,'Periksa pratinjau dan konfirmasikan tindakan.')
    try:
        async with SessionLocal() as db:
            result=await bantuan.terapkan(db,cid=cid,jenis=jenis,aid=aid,pelaku_id=actor['ruang'].user_id,plan_id=data.plan_id)
            await db.commit();return result
    except LookupError as e:raise HTTPException(404,str(e))
    except PermissionError as e:raise HTTPException(403,str(e))
    except ValueError as e:raise HTTPException(409,str(e))
