"""Statistik nyata, konteks perusahaan dan pemulihan tanpa perubahan bisnis."""
import asyncio,json,uuid
from datetime import timedelta
import pytest
from sqlalchemy import select,text,func
from hmu_core import User,Perusahaan,LokasiPabrik,Warehouse,PenempatanGudang,Pelanggan,KeanggotaanPerusahaan
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.sandi import hash_sandi,cek_sandi
from hmu_identitas.monitoring import KejadianPemakaian as E,SumberMonitoring,PelakuPemakaian,PemulihanAkun,PembukaanMasuk
from app.models import ActivityLog
from app.models.portal import PortalAccount
from app.services import console_monitoring as mon,console_bantuan as help
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

@pytest.fixture
async def orang(pg,running,monkeypatch):
    async with pg() as db:
        co=Perusahaan(kode='uji-monitor',nama='Pabrik pengujian');other=Perusahaan(kode='uji-lain',nama='Registry tanpa layanan');db.add_all([co,other]);await db.flush()
        site=LokasiPabrik(company_id=co.id,kode='lokasi',nama='Pabrik uji');db.add(site);await db.flush()
        for w in await db.scalars(select(Warehouse)):db.add(PenempatanGudang(company_id=co.id,lokasi_pabrik_id=site.id,warehouse_id=w.id))
        root=User(nama='Admin Sistem uji',role=P.SUPERADMIN,status='aktif');op=User(nama='Operator aktif',role=P.OPERATOR,status='aktif');off=User(nama='Operator nonaktif',role=P.OPERATOR,status='nonaktif');db.add_all([root,op,off]);await db.flush()
        pw=hash_sandi('sandi-uji-12345')
        a=Akun(user_id=op.id,username='operator-aktif',password_hash=pw,status='aktif',token_version=1)
        z=Akun(user_id=off.id,username='operator-off',password_hash=pw,status='nonaktif',token_version=1)
        r=Akun(user_id=root.id,username='root-monitor',password_hash=pw,status='aktif',token_version=1)
        cust=Pelanggan(nama_pelanggan='Pelanggan portal uji');db.add_all([a,z,r,cust]);await db.flush()
        portal=PortalAccount(pelanggan_id=cust.id,username='portal-uji',password_hash=pw,active=True,token_version=1);db.add(portal)
        member=KeanggotaanPerusahaan(company_id=co.id,user_id=op.id,peran=P.OPERATOR,aktif=False);db.add(member);await db.commit()
        data=dict(cid=co.id,asing=other.id,uid=op.id,root=root.id,aid=a.id,off=z.id,portal=portal.id,mid=member.id)
    monkeypatch.setenv('HMU_COMPANY_ID',str(data['cid']));monkeypatch.setenv('HMU_RUANG_DATA',str(uuid.uuid4()));monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI','0')
    from app.monitoring import pengumpul
    while not pengumpul.antrean.empty():pengumpul.antrean.get_nowait()
    return data

async def ev(db,x,app='padiflow',kind='staf',aid=None,typ='interaksi',code='',when=None,metode=''):
    db.add(E(company_id=x['cid'],aplikasi=app,event_id=str(uuid.uuid4()),jenis_akun=kind,akun_id=x['aid'] if aid is None else aid,user_id=x['uid'] if kind=='staf' else None,peran=P.OPERATOR if kind=='staf' else '',jenis=typ,layar='stok',kode=code,metode=metode,browser='safari',perangkat='iphone',waktu=when or mon.sekarang(),durasi_ms=123))

async def test_pengguna_unik_tidak_dobel_padiflow_teraflow_atau_id_portal(pg,orang):
    x=orang
    async with pg() as db:
        for app in ['padiflow','teraflow']:await ev(db,x,app=app)
        await ev(db,x,app='portal',kind='pelanggan',aid=x['portal'])
        db.add(SumberMonitoring(company_id=x['cid'],aplikasi='padiflow',versi='uji',mulai=mon.sekarang()-timedelta(days=2),terakhir=mon.sekarang()))
        db.add(E(company_id=x['asing'],aplikasi='padiflow',event_id=str(uuid.uuid4()),jenis_akun='staf',akun_id=999,peran=P.OPERATOR,jenis='interaksi',layar='stok',kode='',metode='',browser='chrome',perangkat='desktop',waktu=mon.sekarang()))
        await db.commit()
        r=await mon.ringkasan(db,mon.FilterMonitoring())
        assert r['metrik']['aktif_hari']==2 and r['metrik']['interaksi']==3
        assert r['metrik']['aktif_sekarang']==2
        assert len(r['pengguna_aktif'])==2
        assert r['harian'][0]['pengguna'] is None
        foreign=await mon.ringkasan(db,mon.FilterMonitoring(x['asing']))
        assert not foreign['cakupan']['tersedia'] and foreign['metrik'] is None

async def test_error_browser_dan_polling_tidak_menambah_pengguna_aktif(pg,orang):
    async with pg() as db:
        for _ in range(3):await ev(db,orang,typ='respons_web',code='200',metode='POST')
        await ev(db,orang,typ='galat_browser')
        await ev(db,orang,typ='respons_web',code='422',metode='POST')
        await ev(db,orang,typ='respons_web',code='500',metode='GET')
        await db.commit();r=await mon.ringkasan(db,mon.FilterMonitoring())
        assert r['metrik']['aktif_hari']==0
        assert r['metrik']['respons_simpan']==4 and r['metrik']['respons_diterima']==3
        assert r['metrik']['validasi']==1 and r['metrik']['galat']==2
        assert r['metrik']['p95_ms']==123

async def test_direktori_dan_diagnosis_memakai_kredensial_dan_status_sebenarnya(pg,orang):
    async with pg() as db:
        users=await mon.daftar_akun(db,cari='operator-aktif',company_id=orang['cid'])
        assert users['total']==1 and users['pengguna'][0]['id']==orang['aid']
        d=await help.diagnosis(db,cid=orang['cid'],jenis='staf',aid=orang['aid'])
        assert 'keanggotaan_nonaktif' in d['sebab'] and d['akun']['aktif']
        assert {a['aplikasi'] for a in d['aplikasi']}=={'padiflow','teraflow'}
        assert 'aktifkan_keanggotaan' in d['tindakan']
        with pytest.raises(PermissionError):await help.diagnosis(db,cid=orang['asing'],jenis='staf',aid=orang['aid'])
        bad=await mon.daftar_akun(db,cari='%',company_id=orang['cid'])
        assert bad['total']==0

async def action(pg,x,act,kind='staf',aid=None):
    aid=x['aid'] if aid is None else aid
    async with pg() as db:
        p=await help.pratinjau(db,cid=x['cid'],jenis=kind,aid=aid,pelaku_id=x['root'],aksi=act,alasan='Permintaan pemulihan dari pemilik akun pengujian')
        await db.commit()
    async with pg() as db:
        out=await help.terapkan(db,cid=x['cid'],jenis=kind,aid=aid,pelaku_id=x['root'],plan_id=p['id']);await db.commit();return out,p

ALLOWED={'hmu_support_plans','hmu_account_recoveries','hmu_login_unlocks','produksi_akun','users','portal_accounts','timbangan_akun','activity_logs'}
async def test_tautan_dan_pemulihan_hanya_mengubah_metadata_tanpa_bisnis(pg,orang):
    x=orang
    async with pg() as db:
        before=await sidik(db);old=(await db.get(Akun,x['aid'])).password_hash
    r,plan=await action(pg,x,'tautan_sandi');cap=r['cap']
    async with pg() as db:
        assert (await db.get(Akun,x['aid'])).password_hash==old
        assert (await db.get(Akun,x['aid'])).token_version==1
        await help.pulihkan_sandi(db,cap=cap,sandi='kata-sandi-baru-123',ulangi='kata-sandi-baru-123');await db.commit()
    async with pg() as db:
        a=await db.get(Akun,x['aid']);assert a.token_version==2 and cek_sandi('kata-sandi-baru-123',a.password_hash)
        after=await sidik(db)
        assert {k:v for k,v in before.items() if k not in ALLOWED}=={k:v for k,v in after.items() if k not in ALLOWED}
        logs=list(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='console_bantuan')))
        assert len(logs)==2
        raw=''.join((e.new_value or '')+(e.old_value or '') for e in logs)
        assert cap not in raw and old not in raw and a.password_hash not in raw
        with pytest.raises(ValueError):await help.periksa_pemulihan(db,cap)

@pytest.mark.parametrize('kind',['staf','pelanggan'])
async def test_pemulihan_kadaluarsa_dicabut_dan_versi_berubah_ditolak(pg,orang,kind):
    aid=orang['aid'] if kind=='staf' else orang['portal']
    r,_=await action(pg,orang,'tautan_sandi',kind,aid)
    async with pg() as db:
        row=await db.scalar(select(PemulihanAkun));row.kedaluwarsa=mon.sekarang()-timedelta(seconds=1);await db.commit()
        with pytest.raises(ValueError):await help.periksa_pemulihan(db,r['cap'])
    newer,_=await action(pg,orang,'tautan_sandi',kind,aid)
    async with pg() as db:
        if kind=='staf':(await db.get(Akun,aid)).token_version+=1
        else:(await db.get(PortalAccount,aid)).token_version+=1
        await db.commit()
        with pytest.raises(ValueError):await help.periksa_pemulihan(db,newer['cap'])

async def test_pratinjau_bukan_izin_untuk_keadaan_akun_yang_sudah_berubah(pg,orang):
    x=orang
    async with pg() as db:
        p=await help.pratinjau(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],aksi='cabut_sesi',alasan='Perangkat hilang dilaporkan oleh pemilik akun');await db.commit()
        (await db.get(Akun,x['aid'])).token_version+=1;await db.commit()
    async with pg() as db:
        with pytest.raises(ValueError,match='berubah'):await help.terapkan(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],plan_id=p['id'])
        await db.rollback();assert (await db.get(Akun,x['aid'])).token_version==2

async def test_operator_tidak_bisa_memakai_bantuan_platform(pg,orang):
    async with pg() as db:
        with pytest.raises(PermissionError):await help.pratinjau(db,cid=orang['cid'],jenis='staf',aid=orang['aid'],pelaku_id=orang['uid'],aksi='tautan_sandi',alasan='Permintaan tidak mempunyai wewenang platform')
        with pytest.raises(PermissionError):await help.pratinjau(db,cid=orang['asing'],jenis='staf',aid=orang['aid'],pelaku_id=orang['root'],aksi='tautan_sandi',alasan='Target dari perusahaan yang berbeda')

async def test_aktifkan_akun_dan_keanggotaan_tidak_memperluas_peran(pg,orang):
    await action(pg,orang,'aktifkan_akun',aid=orang['off'])
    await action(pg,orang,'aktifkan_keanggotaan')
    async with pg() as db:
        a=await db.get(Akun,orang['off']);assert a.aktif and a.user.role==P.OPERATOR
        member=await db.get(KeanggotaanPerusahaan,orang['mid']);assert member.aktif and member.peran==P.OPERATOR
        assert await db.scalar(select(func.count()).select_from(PembukaanMasuk))==0

async def test_cap_mentah_tidak_masuk_url_pemulihan_dan_json_galat_terbaca(pg,orang):
    import httpx
    from app.main import app
    from bs4 import BeautifulSoup
    r,_=await action(pg,orang,'tautan_sandi')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        response=await c.get('/pemulihan');assert response.status_code==200
        csrf=BeautifulSoup(response.text,'html.parser').select_one('[data-csrf-pemulihan]')['value']
        headers={'X-CSRF-Token':csrf}
        valid=await c.post('/pemulihan/periksa',json={'cap':r['cap']},headers=headers)
        assert valid.status_code==200 and valid.json()['username']=='operator-aktif'
        invalid=await c.post('/pemulihan/periksa',json={'cap':'X'*64},headers=headers)
        assert invalid.status_code==422 and isinstance(invalid.json()['detail'],str)
        final=await c.post('/pemulihan/simpan',json={'cap':r['cap'],'sandi':'baru-sandi-aman-123','ulangi':'baru-sandi-aman-123'},headers=headers)
        assert final.status_code==200 and final.json()['berhasil']
        again=await c.post('/pemulihan/simpan',json={'cap':r['cap'],'sandi':'baru-sandi-lain-123','ulangi':'baru-sandi-lain-123'},headers=headers)
        assert again.status_code==422

async def test_pengumpul_dedup_dan_gangguan_database_tidak_menghilangkan_batch(pg,orang):
    from hmu_identitas.monitoring import PengumpulPemakaian
    c=PengumpulPemakaian(pg,'padiflow');a=PelakuPemakaian('staf',orang['aid'],orang['uid']);key=str(uuid.uuid4())
    for _ in range(2):c.catat(a,jenis='interaksi',event_id=key)
    await c.kirim()
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(E).where(E.event_id==key))==1
        assert await db.scalar(select(func.count()).select_from(SumberMonitoring))==2
    class Rusak:
        async def __aenter__(self):raise RuntimeError('offline')
        async def __aexit__(self,*args):pass
    c.sesi=lambda:Rusak();c.catat(a,jenis='respons_web',kode='201');await c.kirim()
    assert c.antrean.qsize()==1
    c.sesi=pg;await c.kirim();assert c.antrean.empty()

async def test_penerapan_ulang_tidak_menerbitkan_token_kedua_dan_target_salah_ditolak(pg,orang):
    result,plan=await action(pg,orang,'tautan_sandi')
    async with pg() as db:
        repeat=await help.terapkan(db,cid=orang['cid'],jenis='staf',aid=orang['aid'],pelaku_id=orang['root'],plan_id=plan['id'])
        assert repeat['sudah'] and 'cap' not in repeat
        assert await db.scalar(select(func.count()).select_from(PemulihanAkun))==1
        with pytest.raises(ValueError):await help.terapkan(db,cid=orang['cid'],jenis='staf',aid=orang['off'],pelaku_id=orang['root'],plan_id=plan['id'])

async def test_dua_pemakaian_tautan_bersamaan_hanya_satu_berhasil(pg,orang):
    result,_=await action(pg,orang,'tautan_sandi')
    async def use():
        async with pg() as db:
            try:
                await help.pulihkan_sandi(db,cap=result['cap'],sandi='sandi-bersamaan-123',ulangi='sandi-bersamaan-123');await db.commit();return True
            except ValueError:await db.rollback();return False
    assert sorted(await asyncio.gather(use(),use()))==[False,True]
    async with pg() as db:assert (await db.get(Akun,orang['aid'])).token_version==2

async def test_http_monitoring_bearer_csrf_dan_pergantian_identitas(pg,orang,monkeypatch):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_console_akses import sesi
    from app.config import settings
    from app.web.security import NAMA_COOKIE,buat_token
    monkeypatch.setattr(settings,'console_website_url','https://website.uji')
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        assert (await c.get('/internal/console/monitoring')).status_code==401
        h=await sesi(c)
        r=await c.get('/internal/console/monitoring',headers=h);assert r.status_code==200,r.text
        assert r.json()['cakupan']['company_id']==orang['cid']
        target=f"/internal/console/monitoring/perusahaan/{orang['cid']}/pengguna/staf/{orang['aid']}"
        r=await c.post(target+'/pratinjau',headers=h,json=dict(aksi='cabut_sesi',alasan='Perangkat hilang; pencabutan diminta pemilik akun'))
        assert r.status_code==200,r.text
        plan=r.json()['id']
        assert (await c.post(target+'/terapkan',headers=h,json=dict(plan_id=plan,konfirmasi=False))).status_code==422
        r=await c.post(target+'/terapkan',headers=h,json=dict(plan_id=plan,konfirmasi=True));assert r.status_code==200,r.text
        assert (await c.post('/internal/console/keluar',headers=h,json={})).status_code==200
        assert (await c.get('/internal/console/monitoring',headers=h)).status_code==401
    async with await _klien(pg,peran=P.OPERATOR) as c:
        r=await c.get('/monitoring/konteks');assert r.status_code==200,r.text
        ctx=r.json();payload=dict(cap=ctx['cap'],kejadian=[dict(event_id=str(uuid.uuid4()),jenis='interaksi',layar='stok')])
        headers={'X-CSRF-Token':ctx['csrf']}
        r=await c.post('/monitoring/aktivitas',headers=headers,json=payload);assert r.status_code==202,r.text
        assert (await c.post('/monitoring/aktivitas',headers=headers,json={**payload,'company_id':orang['asing']})).status_code==422
        assert (await c.post('/monitoring/aktivitas',headers=headers,json={**payload,'cap':'salah'})).status_code==403
        async with pg() as db:token=buat_token(await db.get(Akun,orang['aid']))
        c.cookies.set(NAMA_COOKIE,token)
        assert (await c.post('/monitoring/aktivitas',headers=headers,json=payload)).status_code==403
