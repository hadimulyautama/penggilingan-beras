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
