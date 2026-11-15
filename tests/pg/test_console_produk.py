"""Aktivasi per produk, isolasi, sesi hidup dan transaksi bisnis tidak berubah."""
import pytest
from sqlalchemy import select
from hmu_core import User,KeanggotaanPerusahaan,ProdukAplikasiPerusahaan as CP,AksesProdukAnggota as UP,IntegrasiProdukPerusahaan as CI
from hmu_identitas import peran as P
from hmu_identitas.produk import hak_pengguna,hak_lokal,integrasi_lokal,ProdukDitolak,PADIFLOW,TERAFLOW
from hmu_identitas.model import Akun
from app.services import produk_perusahaan as svc,keanggotaan as mem,console_monitoring as mon
from app.services.organisasi_master import OrganisasiError
from tests.pg.test_console_monitoring import orang
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]
META={'hmu_company_products','hmu_member_products','hmu_company_integrations','activity_logs'}
def bisnis(snapshot):return {k:v for k,v in snapshot.items() if k not in META}

async def simpan(db,x,**changes):
    ruang=mem.RuangAdministrasi(x['root']);old=await svc.rincian(db,ruang=ruang,company_id=x['cid'])
    body=dict(produk=[dict(kode=p['kode'],aktif=p['aktif']) for p in old['produk']],integrasi=old['integrasi'],bukti=old['bukti'],alasan='Pengujian aktivasi produk tanpa perubahan transaksi')
    body.update(changes);return await svc.simpan(db,ruang=ruang,company_id=x['cid'],**body)

async def test_warisan_hmu_dan_peran_produk_tidak_mengubah_master(pg,orang):
    x=orang;before=await fakta(pg)
    async with pg() as db:
        assert (await hak_pengguna(db,company_id=x['cid'],produk=PADIFLOW,user_id=x['uid'])).sumber=='warisan'
        member=await db.get(KeanggotaanPerusahaan,x['mid']);member.aktif=True
        db.add_all([UP(company_id=x['cid'],user_id=x['uid'],produk=PADIFLOW,peran=P.ADMIN,aktif=True),UP(company_id=x['cid'],user_id=x['uid'],produk=TERAFLOW,peran=P.OPERATOR,aktif=True)]);await db.commit()
    async with pg() as db:
        assert (await hak_pengguna(db,company_id=x['cid'],produk=PADIFLOW,user_id=x['uid'])).peran==P.ADMIN
        assert (await hak_pengguna(db,company_id=x['cid'],produk=TERAFLOW,user_id=x['uid'])).peran==P.OPERATOR
        assert (await db.get(User,x['uid'])).role==P.OPERATOR
        (await db.get(UP,(x['cid'],x['uid'],TERAFLOW))).aktif=False;await db.commit()
    async with pg() as db:
        with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['cid'],produk=TERAFLOW,user_id=x['uid'])
        assert (await hak_pengguna(db,company_id=x['cid'],produk=PADIFLOW,user_id=x['uid'])).peran==P.ADMIN
    # Fixture membership is intentionally activated above; business rows stay exact.
    after=await fakta(pg)
    assert {k:v for k,v in bisnis(before).items() if k!='hmu_company_memberships'}=={k:v for k,v in bisnis(after).items() if k!='hmu_company_memberships'}

@pytest.mark.parametrize('pf,tf',[(True,False),(False,True),(True,True),(False,False)])
async def test_kombinasi_produk_dan_integrasi(pg,orang,pf,tf):
    x=orang;before=await fakta(pg)
    async with pg() as db:
        await simpan(db,x,produk=[dict(kode=PADIFLOW,aktif=pf),dict(kode=TERAFLOW,aktif=tf)],integrasi=False);await db.commit()
    async with pg() as db:
        for code,enabled in [(PADIFLOW,pf),(TERAFLOW,tf)]:
            if enabled:assert (await hak_pengguna(db,company_id=x['cid'],produk=code,user_id=x['uid'])).peran==P.OPERATOR
            else:
                with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['cid'],produk=code,user_id=x['uid'])
        with pytest.raises(ProdukDitolak):await integrasi_lokal(db)
        if pf and tf:
            await simpan(db,x,integrasi=True);await db.commit();await integrasi_lokal(db)
        else:
            with pytest.raises(OrganisasiError):await simpan(db,x,integrasi=True)
        assert (await db.get(User,x['uid'])).role==P.OPERATOR
    assert bisnis(await fakta(pg))==bisnis(before)

async def test_perusahaan_baru_tidak_mewarisi_akses_dan_tidak_bisa_memakai_bukti_perusahaan_lain(pg,orang):
    x=orang;ruang=mem.RuangAdministrasi(x['root']);before=await fakta(pg)
    async with pg() as db:
        with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['asing'],produk=TERAFLOW,user_id=x['uid'])
        old=await svc.rincian(db,ruang=ruang,company_id=x['cid'])
        with pytest.raises(OrganisasiError):await svc.simpan(db,ruang=ruang,company_id=x['asing'],produk=[dict(kode=PADIFLOW,aktif=False),dict(kode=TERAFLOW,aktif=True)],integrasi=False,bukti=old['bukti'],alasan='Bukti perusahaan lain harus ditolak')
        other=await svc.rincian(db,ruang=ruang,company_id=x['asing'])
        await svc.simpan(db,ruang=ruang,company_id=x['asing'],produk=[dict(kode=PADIFLOW,aktif=False),dict(kode=TERAFLOW,aktif=True)],integrasi=False,bukti=other['bukti'],alasan='Perusahaan uji hanya memakai TeraFlow');await db.commit()
        assert not (await db.get(CP,(x['asing'],TERAFLOW))).warisan
        with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['asing'],produk=TERAFLOW,user_id=x['uid'])
        # Grant for another registry company cannot open the local data space.
        with pytest.raises(OrganisasiError):await svc.rincian(db,ruang=ruang,company_id=x['asing'],user_id=x['uid'])
    assert bisnis(await fakta(pg))==bisnis(before)

async def test_akses_eksplisit_diatur_dengan_audit_tanpa_perubahan_bisnis(pg,orang):
    x=orang;ruang=mem.RuangAdministrasi(x['root']);before=await fakta(pg)
    async with pg() as db:
        old=await svc.rincian(db,ruang=ruang,company_id=x['cid'],user_id=x['uid'])
        new=await svc.simpan_akses(db,ruang=ruang,company_id=x['cid'],user_id=x['uid'],akses=[dict(produk=PADIFLOW,mode=P.ADMIN),dict(produk=TERAFLOW,mode='nonaktif')],bukti=old['bukti'],alasan='Akses produk berbeda untuk satu pengguna');await db.commit()
        assert new['akses']==[dict(produk=PADIFLOW,mode=P.ADMIN),dict(produk=TERAFLOW,mode='nonaktif')]
        with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['cid'],produk=PADIFLOW,user_id=x['uid']) # membership disabled
        with pytest.raises(OrganisasiError):await svc.simpan_akses(db,ruang=ruang,company_id=x['cid'],user_id=x['uid'],akses=old['akses'],bukti=old['bukti'],alasan='Pratinjau lama tidak boleh menimpa data baru')
        with pytest.raises(PermissionError):await svc.rincian(db,ruang=mem.RuangAdministrasi(x['uid'],x['cid']),company_id=x['cid'])
    assert bisnis(await fakta(pg))==bisnis(before)

async def test_monitoring_hanya_memperingatkan_produk_aktif(pg,orang):
    x=orang
    async with pg() as db:
        await simpan(db,x,produk=[dict(kode=PADIFLOW,aktif=False),dict(kode=TERAFLOW,aktif=True)],integrasi=False);await db.commit()
        result=await mon.ringkasan(db,mon.FilterMonitoring())
        assert result['aplikasi_aktif']==[TERAFLOW]
        assert [p['aplikasi'] for p in result['sumber']]==[TERAFLOW]
        with pytest.raises(ValueError):await mon.ringkasan(db,mon.FilterMonitoring(aplikasi=PADIFLOW))

async def test_sesi_aktif_mengikuti_peran_produk_dan_pencabutan(pg,orang):
    import httpx
    from app.main import app
    from app.web.security import buat_token,NAMA_COOKIE
    x=orang
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        db.add(UP(company_id=x['cid'],user_id=x['uid'],produk=PADIFLOW,peran=P.ADMIN,aktif=True));await db.commit()
        cookie=buat_token(await db.get(Akun,x['aid']))
    before=await fakta(pg)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={NAMA_COOKIE:cookie}) as c:
        r=await c.get('/api/me');assert r.status_code==200 and r.json()['role']==P.ADMIN
        async with pg() as db:
            (await db.get(UP,(x['cid'],x['uid'],PADIFLOW))).aktif=False;await db.commit()
        r=await c.get('/api/me');assert r.status_code==403
    async with pg() as db:assert (await db.get(User,x['uid'])).role==P.OPERATOR
    assert bisnis(await fakta(pg))==bisnis(before)


async def test_console_tetap_bisa_masuk_saat_padiflow_nonaktif_dan_api_hanya_metadata(pg,orang,monkeypatch):
    import httpx
    from pydantic import SecretStr
    from app.main import app
    from app.config import settings
    from tests.pg.test_console_masuk_langsung import KEY,HEADERS
    from app.web.gerbang_masuk import bersihkan
    bersihkan()
    monkeypatch.setattr(settings,'console_login_secret',SecretStr(KEY))
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    x=orang
    async with pg() as db:
        await simpan(db,x,produk=[dict(kode=PADIFLOW,aktif=False),dict(kode=TERAFLOW,aktif=True)],integrasi=False);await db.commit()
    before=await fakta(pg)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        r=await c.post('/internal/console/masuk',headers=HEADERS,json=dict(username='root-monitor',sandi='sandi-uji-12345',jejak='a'*64))
        assert r.status_code==200,r.text
        auth={'Authorization':'Bearer '+r.json()['token']}
        path=f"/internal/console/perusahaan/{x['cid']}/produk"
        old=(await c.get(path,headers=auth)).json()
        body=dict(produk=[dict(kode=PADIFLOW,aktif=False),dict(kode=TERAFLOW,aktif=True)],integrasi=False,bukti=old['bukti'],alasan='Hanya TeraFlow tetap dapat diatur di Console',konfirmasi=False)
        assert (await c.post(path,headers=auth,json=body)).status_code==422
        assert (await c.post(path,headers=auth,json={**body,'konfirmasi':True,'produk':[dict(kode=PADIFLOW,aktif=False,warisan=True),dict(kode=TERAFLOW,aktif=True)]})).status_code==422
        body.update(konfirmasi=True,produk=[dict(kode=PADIFLOW,aktif=True),dict(kode=TERAFLOW,aktif=True)])
        assert (await c.post(path,headers=auth,json=body)).status_code==200
        assert (await c.post(path,headers=auth,json=body)).status_code==422 # stale proof
        assert (await c.post(path,json=body)).status_code in (401,403)
        target=f"/internal/console/perusahaan/{x['cid']}/anggota/{x['uid']}/produk"
        out=await c.get(target,headers=auth);assert out.status_code==200
        invalid=dict(akses=[dict(produk=PADIFLOW,mode='superadmin'),dict(produk=TERAFLOW,mode='operator')],alasan='Peran platform bukan peran produk',bukti=out.json()['bukti'],konfirmasi=True)
        assert (await c.post(target,headers=auth,json=invalid)).status_code==422
    after=await fakta(pg)
    excluded=META|{'hmu_console_sessions','produksi_akun'}
    assert {k:v for k,v in before.items() if k not in excluded}=={k:v for k,v in after.items() if k not in excluded}


async def test_migrasi_hanya_mewariskan_perusahaan_yang_ditetapkan_tanpa_mengubah_transaksi(pg,orang):
    import importlib.util,json
    from pathlib import Path
    from sqlalchemy import text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    x=orang
    async with pg() as db:
        for key in ('ruang_data_perusahaan','organisasi_perusahaan_lama'):
            await db.execute(text('INSERT INTO setelan_pabrik(kunci,nilai) VALUES (:k,:v) ON CONFLICT(kunci) DO UPDATE SET nilai=EXCLUDED.nilai'),dict(k=key,v=json.dumps(dict(company_id=x['cid'],ruang_id='d03cb088-c62b-4bce-9b6c-d095aee92749'))))
        await db.commit()
    before=await fakta(pg)
    spec=importlib.util.spec_from_file_location('produk_migrasi',Path(__file__).resolve().parents[2]/'migrations/versions/0133_produk_perusahaan.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    async with pg() as db:
        conn=await db.connection()
        def migrate(sync):
            for table in ('hmu_member_products','hmu_company_integrations','hmu_company_products'):
                sync.execute(text('DROP TABLE '+table))
            with Operations.context(MigrationContext.configure(sync)):migration.upgrade()
        await conn.run_sync(migrate);await db.commit()
        rows=list(await db.scalars(select(CP)))
        assert len(rows)==2 and all(r.company_id==x['cid'] and r.aktif and r.warisan for r in rows)
        assert await db.get(CP,(x['asing'],TERAFLOW)) is None
    assert bisnis(await fakta(pg))==bisnis(before)


async def test_anggota_perusahaan_lain_tidak_mewarisi_akses_hmu(pg,orang):
    x=orang
    async with pg() as db:
        user=User(nama='Admin perusahaan lain',role=P.ADMIN,status='aktif');db.add(user);await db.flush()
        db.add(KeanggotaanPerusahaan(company_id=x['asing'],user_id=user.id,aktif=True,peran=P.ADMIN));await db.commit()
        for code in (PADIFLOW,TERAFLOW):
            with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['cid'],produk=code,user_id=user.id)
        # ID pengguna sah dan produk HMU aktif tidak cukup untuk melintasi perusahaan.
        with pytest.raises(ProdukDitolak):await hak_lokal(db,produk=PADIFLOW,user_id=user.id,peran_lama=P.ADMIN)

        db.add(KeanggotaanPerusahaan(company_id=x['cid'],user_id=user.id,aktif=True,peran=P.OPERATOR));await db.commit()
        with pytest.raises(ProdukDitolak):await hak_pengguna(db,company_id=x['cid'],produk=PADIFLOW,user_id=user.id)
        db.add(UP(company_id=x['cid'],user_id=user.id,produk=PADIFLOW,aktif=True,peran=P.OPERATOR));await db.commit()
        assert (await hak_pengguna(db,company_id=x['cid'],produk=PADIFLOW,user_id=user.id)).peran==P.OPERATOR


@pytest.mark.parametrize('produk',[PADIFLOW,TERAFLOW])
async def test_direktori_dan_bantuan_tidak_mengambil_akun_perusahaan_lain(pg,orang,produk):
    from app.services import console_bantuan as bantuan
    x=orang
    async with pg() as db:
        (await db.get(CP,(x['cid'],PADIFLOW))).aktif=produk==PADIFLOW
        (await db.get(CP,(x['cid'],TERAFLOW))).aktif=produk==TERAFLOW
        user=User(nama='Pengguna perusahaan asing',role=P.OPERATOR,status='nonaktif');db.add(user);await db.flush()
        account=Akun(user_id=user.id,username='akun-perusahaan-asing',password_hash='tidak-dipakai',status='nonaktif',token_version=1)
        db.add_all([account,KeanggotaanPerusahaan(company_id=x['asing'],user_id=user.id,peran=P.OPERATOR,aktif=True)]);await db.commit();aid=account.id
    before=await fakta(pg)
    async with pg() as db:
        out=await mon.daftar_akun(db,company_id=x['cid'],cari='akun-perusahaan-asing')
        assert out['total']==0
        with pytest.raises(LookupError):await bantuan.diagnosis(db,cid=x['cid'],jenis='staf',aid=aid)
        with pytest.raises(LookupError):await bantuan.pratinjau(db,cid=x['cid'],jenis='staf',aid=aid,pelaku_id=x['root'],aksi='aktifkan_akun',alasan='Target dari perusahaan lain harus ditolak')
    assert await fakta(pg)==before


@pytest.fixture
async def profil_lama(pg,orang):
    from sqlalchemy import text
    async with pg() as db:
        # Skema penuh TeraFlow tersedia pada profil integrasi; profil PadiFlow
        # mempunyai stub kompatibilitas yang hanya dilengkapi selama uji ini.
        before=set(await db.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_name='timbangan_akun' AND table_schema='public'")))
        for name,ddl in [('akun_id','INTEGER'),('token_version','INTEGER NOT NULL DEFAULT 1'),('terakhir_login','TIMESTAMPTZ')]:
            if name not in before:await db.execute(text('ALTER TABLE timbangan_akun ADD COLUMN '+name+' '+ddl))
        pid=await db.scalar(text("INSERT INTO timbangan_akun(user_id,nama,username,role,status,password_hash,token_version) VALUES (:uid,'Operator uji','tf-audit-lama','PETUGAS','aktif','hash-uji-bukan-login',1) RETURNING id"),dict(uid=orang['uid']))
        await db.commit()
    try:yield pid
    finally:
        async with pg() as db:
            for name in ('akun_id','token_version','terakhir_login'):
                if name not in before:await db.execute(text('ALTER TABLE timbangan_akun DROP COLUMN '+name))
            await db.commit()


@pytest.mark.parametrize('aktif',[False,True])
async def test_diagnosis_profil_tf_lama_mengikuti_izin_produk_yang_sebenarnya(pg,orang,profil_lama,aktif):
    from app.services import console_bantuan as bantuan
    x=orang
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        db.add(UP(company_id=x['cid'],user_id=x['uid'],produk=TERAFLOW,aktif=aktif,peran=P.ADMIN));await db.commit()
        d=await bantuan.diagnosis(db,cid=x['cid'],jenis='timbangan_lama',aid=profil_lama)
        assert d['aplikasi'][0]['boleh']==aktif
        assert d['akun']['peran']==P.OPERATOR
        if aktif:assert d['aplikasi'][0]['peran_produk']==P.ADMIN


async def test_diagnosis_produk_yang_tidak_dipakai_bukan_peran_salah(pg,orang):
    from app.services import console_bantuan as bantuan
    x=orang
    async with pg() as db:
        (await db.get(CP,(x['cid'],PADIFLOW))).aktif=False;await db.commit()
        d=await bantuan.diagnosis(db,cid=x['cid'],jenis='staf',aid=x['aid'])
        pf=next(i for i in d['aplikasi'] if i['aplikasi']==PADIFLOW)
        assert pf['sebab']=='produk_nonaktif'
        assert next(i for i in d['aplikasi'] if i['aplikasi']==TERAFLOW)['boleh']


@pytest.mark.parametrize('produk',[PADIFLOW,TERAFLOW])
async def test_pemulihan_akun_bersama_menuju_produk_yang_bisa_dipakai(pg,orang,monkeypatch,produk):
    import httpx
    from app.main import app
    from app.config import settings
    from app.services import console_bantuan as bantuan
    from tests.pg.test_console_monitoring import action
    from bs4 import BeautifulSoup
    x=orang;monkeypatch.setattr(settings,'teraflow_web_url','https://teraflow.uji')
    async with pg() as db:
        for code in (PADIFLOW,TERAFLOW):(await db.get(CP,(x['cid'],code))).aktif=code==produk
        await db.commit()
    result,_=await action(pg,x,'tautan_sandi')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        page=await c.get('/pemulihan');csrf=BeautifulSoup(page.text,'html.parser').select_one('[data-csrf-pemulihan]')['value']
        r=await c.post('/pemulihan/simpan',headers={'X-CSRF-Token':csrf},json=dict(cap=result['cap'],sandi='baru-audit-produk-123',ulangi='baru-audit-produk-123'))
        assert r.status_code==200,r.text
        assert r.json()['tujuan']==('/masuk' if produk==PADIFLOW else 'https://teraflow.uji/timbangan/masuk')
    async with pg() as db:
        # Reset sandi tidak pernah menambah izin produk.
        for code in (PADIFLOW,TERAFLOW):assert bool((await db.get(CP,(x['cid'],code))).aktif)==(code==produk)


async def test_akun_tanpa_anggota_tidak_dianggap_milik_perusahaan_baru(pg,orang):
    x=orang
    async with pg() as db:
        for code in (PADIFLOW,TERAFLOW):(await db.get(CP,(x['cid'],code))).warisan=False
        u=User(nama='Belum ditetapkan',role=P.OPERATOR,status='aktif');db.add(u);await db.flush()
        a=Akun(user_id=u.id,username='belum-ditetapkan',password_hash='tidak-untuk-login',status='aktif',token_version=1);db.add(a);await db.commit()
        assert (await mon.daftar_akun(db,company_id=x['cid'],cari=a.username))['total']==0
        with pytest.raises(LookupError):await mon.akun(db,x['cid'],'staf',a.id)
        db.add(KeanggotaanPerusahaan(company_id=x['cid'],user_id=u.id,peran=P.OPERATOR,aktif=False));await db.commit()
        assert (await mon.daftar_akun(db,company_id=x['cid'],cari=a.username))['total']==1
        assert not (await mon.akun(db,x['cid'],'staf',a.id))['keanggotaan']['aktif']


async def test_cap_pemulihan_dan_pratinjau_tidak_bisa_memakai_konteks_perusahaan_lama(pg,orang):
    from app.services import console_bantuan as bantuan
    from tests.pg.test_console_monitoring import action
    x=orang;result,_=await action(pg,x,'tautan_sandi')
    async with pg() as db:
        plan=await bantuan.pratinjau(db,cid=x['cid'],jenis='staf',aid=x['off'],pelaku_id=x['root'],aksi='aktifkan_akun',alasan='Pemulihan harus memeriksa perusahaan terkini');await db.commit()
        for uid in (x['uid'],(await db.get(Akun,x['off'])).user_id):
            row=await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.user_id==uid,KeanggotaanPerusahaan.company_id==x['cid']))
            if row:row.company_id=x['asing']
            else:db.add(KeanggotaanPerusahaan(company_id=x['asing'],user_id=uid,peran=P.OPERATOR,aktif=True))
        await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        with pytest.raises(LookupError):await bantuan.pulihkan_sandi(db,cap=result['cap'],sandi='jangan-tersimpan-123',ulangi='jangan-tersimpan-123')
        with pytest.raises(LookupError):await bantuan.terapkan(db,cid=x['cid'],jenis='staf',aid=x['off'],pelaku_id=x['root'],plan_id=plan['id'])
    assert await fakta(pg)==before


async def test_tujuan_pemulihan_mengikuti_grant_dan_origin_terpercaya(pg,orang,monkeypatch):
    from app.services import console_bantuan as bantuan
    from app.config import settings
    x=orang;monkeypatch.setattr(settings,'teraflow_web_url','https://teraflow.uji')
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        db.add_all([UP(company_id=x['cid'],user_id=x['uid'],produk=PADIFLOW,aktif=False,peran=P.OPERATOR),UP(company_id=x['cid'],user_id=x['uid'],produk=TERAFLOW,aktif=True,peran=P.OPERATOR)]);await db.commit()
        a=await mon.akun(db,x['cid'],'staf',x['aid'])
        assert await bantuan.tujuan_masuk(db,a)=='https://teraflow.uji/timbangan/masuk'
        for url in ('http://tidak-aman.uji','https://nama:sandi@teraflow.uji','https://teraflow.uji/asing','https://teraflow.uji?tujuan=asing','https://teraflow.uji#rahasia','https://[tidak-valid','https://teraflow.uji:port-salah','https://@teraflow.uji'):
            monkeypatch.setattr(settings,'teraflow_web_url',url);assert await bantuan.tujuan_masuk(db,a) is None
        (await db.get(UP,(x['cid'],x['uid'],TERAFLOW))).aktif=False;await db.commit()
        assert await bantuan.tujuan_masuk(db,a) is None
        # Hak platform tidak bergantung pada aktivasi PadiFlow/TeraFlow.
        for code in (PADIFLOW,TERAFLOW):(await db.get(CP,(x['cid'],code))).aktif=False
        await db.commit();monkeypatch.setattr(settings,'console_website_url','https://console.uji')
        root=await db.scalar(select(Akun).where(Akun.user_id==x['root']))
        assert await bantuan.tujuan_masuk(db,await mon.akun(db,x['cid'],'staf',root.id))=='https://console.uji/console/masuk'


@pytest.mark.parametrize('produk',[PADIFLOW,TERAFLOW])
async def test_console_http_perusahaan_nonwarisan_hanya_satu_produk(pg,orang,monkeypatch,produk):
    import httpx
    from pydantic import SecretStr
    from app.main import app
    from app.config import settings
    from tests.pg.test_console_masuk_langsung import KEY,HEADERS
    from app.services import console_bantuan as bantuan
    from app.web.gerbang_masuk import bersihkan
    x=orang;bersihkan()
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    monkeypatch.setattr(settings,'console_login_secret',SecretStr(KEY))
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        for code in (PADIFLOW,TERAFLOW):
            row=await db.get(CP,(x['cid'],code));row.warisan=False;row.aktif=code==produk
            db.add(UP(company_id=x['cid'],user_id=x['uid'],produk=code,aktif=code==produk,peran=P.OPERATOR))
        (await db.get(CI,(x['cid'],'padiflow_teraflow'))).aktif=False;await db.commit()
    before=await fakta(pg)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        r=await c.post('/internal/console/masuk',headers=HEADERS,json=dict(username='root-monitor',sandi='sandi-uji-12345',jejak='c'*64));assert r.status_code==200,r.text
        h={'Authorization':'Bearer '+r.json()['token']};base=f"/internal/console/monitoring/perusahaan/{x['cid']}/pengguna/staf/{x['aid']}"
        d=await c.get(base,headers=h);assert d.status_code==200
        allowed=[a['aplikasi'] for a in d.json()['aplikasi'] if a['boleh']];assert allowed==[produk]
        out=await c.get('/internal/console/monitoring/pengguna',headers=h,params=dict(company_id=x['cid'],cari='operator-aktif'))
        assert out.status_code==200 and out.json()['total']==1
        p=await c.post(base+'/pratinjau',headers=h,json=dict(aksi='cabut_sesi',alasan='Uji pemulihan pada satu produk yang diaktifkan'))
        assert p.status_code==200
        assert (await c.post(base+'/terapkan',headers=h,json=dict(plan_id=p.json()['id'],konfirmasi=True))).status_code==200
        # Pemulihan sesi tidak memberi hak produk lainnya atau mengubah peran master.
        after=(await c.get(base,headers=h)).json()
        assert [a['aplikasi'] for a in after['aplikasi'] if a['boleh']]==[produk]
        assert (await c.get('/internal/console/saya',headers=h)).status_code==200
    after=await fakta(pg);excluded={'produksi_akun','hmu_console_sessions','hmu_support_plans','activity_logs'}
    assert {k:v for k,v in before.items() if k not in excluded}=={k:v for k,v in after.items() if k not in excluded}


async def test_diagnosis_legacy_membaca_status_pengguna_terbaru_meski_dicache(pg,orang,profil_lama):
    async with pg() as stale:
        assert (await mon.akun(stale,orang['cid'],'timbangan_lama',profil_lama))['aktif']
        async with pg() as db:
            (await db.get(User,orang['uid'])).status='nonaktif';await db.commit()
        assert not (await mon.akun(stale,orang['cid'],'timbangan_lama',profil_lama,kunci=True))['aktif']
