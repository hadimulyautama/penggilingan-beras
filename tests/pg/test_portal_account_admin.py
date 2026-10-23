"""Super Admin selects verified Kledo customers; credentials never grant staff access."""
import httpx
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select,func
from app.main import app
from app.models import Pelanggan,User,ProduksiAkun,ActivityLog
from app.models.portal import PortalAccount
from app.web import security
from app.web.portal.security import COOKIE,issue
from tests.pg.test_kelola_akun_http import _super,_token,_klien
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def people(pg):
    sid=await _super(pg)
    async with pg() as db:
        rows=[Pelanggan(nama_pelanggan='Kontak Sama',kledo_contact_id=601,status='aktif'),
              Pelanggan(nama_pelanggan='Kontak Sama',kledo_contact_id=602,status='aktif'),
              Pelanggan(nama_pelanggan='Lokal tanpa Kledo',status='aktif'),
              Pelanggan(nama_pelanggan='Kontak Nonaktif',kledo_contact_id=603,status='nonaktif')]
        db.add_all(rows);await db.commit()
    return sid,rows


def form(pid=1,kid=601,username='pelanggan-uji',sandi='portal12345'):
    return dict(kontak=f'{kid}:{pid}',username=username,sandi=sandi,konfirmasi=sandi)


async def create(c,data):
    return await c.post('/pengguna/pelanggan/buat',data={**data,'_csrf':cap_formulir(c)})


async def test_super_creates_portal_only_identity_and_never_echoes_password(pg,people):
    sid,customers=people
    async with _klien(await _token(pg,sid)) as c:
        r=await c.get('/pengguna');assert '/pengguna/pelanggan' in r.text
        r=await c.get('/pengguna/pelanggan');assert r.status_code==200
        soup=BeautifulSoup(r.text,'html.parser');options=soup.select('[name=kontak] option')
        assert {x.get('value') for x in options}=={'','601:'+str(customers[0].id),'602:'+str(customers[1].id)}
        r=await create(c,{**form(customers[1].id,602),'peran':'superadmin'})
        assert r.status_code==303 and 'portal12345' not in r.text
        page=await c.get(r.headers['location']);assert 'pelanggan-uji' in page.text and 'portal12345' not in page.text
    async with pg() as db:
        account=await db.scalar(select(PortalAccount));assert account.pelanggan_id==customers[1].id
        assert security.cek_sandi('portal12345',account.password_hash)
        assert await db.scalar(select(func.count()).select_from(User))==1
        assert await db.scalar(select(func.count()).select_from(ProduksiAkun))==1
        logs=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='portal_accounts'))).all()
        assert len(logs)==1 and logs[0].changed_by is not None
        assert 'portal12345' not in str(logs[0].new_value) and 'scrypt$' not in str(logs[0].new_value)


@pytest.mark.parametrize('bad',['unlinked','inactive','wrong_kledo','huge','short','confirm','staff_username'])
async def test_invalid_contact_and_credentials_are_not_saved(pg,people,bad):
    sid,p=people;data=form(p[0].id,601)
    if bad=='unlinked':data['kontak']=f'604:{p[2].id}'
    if bad=='inactive':data['kontak']=f'603:{p[3].id}'
    if bad=='wrong_kledo':data['kontak']=f'602:{p[0].id}'
    if bad=='huge':data['kontak']='601:9999999999999999999999'
    if bad=='short':data.update(sandi='123',konfirmasi='123')
    if bad=='confirm':data['konfirmasi']='does-not-match'
    if bad=='staff_username':data['username']='bos'
    async with _klien(await _token(pg,sid)) as c:
        r=await create(c,data);assert r.status_code==422,(bad,r.text[:100])
        assert data['sandi'] not in r.text or data['sandi']=='123'
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(PortalAccount))==0


async def test_admin_denied_even_when_no_superadmin_exists(pg,people):
    sid,p=people
    async with pg() as db:
        a=await db.get(ProduksiAkun,sid);u=await db.get(User,a.user_id);u.role='admin';await db.commit()
    async with _klien(await _token(pg,sid)) as c:
        for path in ['/pengguna/pelanggan','/pengguna/pelanggan/1']:
            assert (await c.get(path)).status_code==403
        assert (await create(c,form(p[0].id,601))).status_code==403
        for path in ['/pengguna/pelanggan/1','/pengguna/pelanggan/1/status']:
            assert (await c.post(path,data={'_csrf':cap_formulir(c),'username':'other','aktif':'1'})).status_code==403


async def test_customer_login_cannot_login_as_staff_or_manage_accounts(pg,people):
    sid,p=people
    async with _klien(await _token(pg,sid)) as c:
        assert (await create(c,form(p[0].id,601))).status_code==303
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        r=await c.get('/masuk');r=await c.post('/masuk',data={'username':'pelanggan-uji','sandi':'portal12345','_csrf':cap_formulir(c)})
        assert not any(x.name==security.NAMA_COOKIE for x in c.cookies.jar)
        r=await c.get('/pelanggan/masuk');token=BeautifulSoup(r.text,'html.parser').select_one('[name=_csrf]')['value']
        r=await c.post('/pelanggan/masuk',data={'username':'pelanggan-uji','sandi':'portal12345','_csrf':token});assert r.status_code==303
        assert (await c.get('/pelanggan')).status_code==200
        for path in ['/pengguna','/pengguna/pelanggan','/api/actions','/pengaturan']:
            r=await c.get(path);assert r.status_code in (303,401,403,404)
        # Even with a valid staff-CSRF cap for an anonymous session, no staff identity is granted.
        r=await c.post('/pengguna/pelanggan/buat',data={**form(p[1].id,602,'attack'),'_csrf':cap_formulir(c)})
        assert r.status_code in (303,401,403)
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(PortalAccount))==1


async def test_password_change_disable_and_enable_revoke_sessions_and_keep_owner(pg,people):
    sid,p=people
    async with _klien(await _token(pg,sid)) as c:
        assert (await create(c,form(p[0].id,601))).status_code==303
        async with pg() as db:a=await db.scalar(select(PortalAccount));aid=a.id;old=issue(a)
        r=await c.post(f'/pengguna/pelanggan/{aid}',data={'username':'pelanggan-baru','sandi':'new-password','konfirmasi':'new-password','pelanggan_id':p[1].id,'_csrf':cap_formulir(c)})
        assert r.status_code==303
        async with pg() as db:
            a=await db.get(PortalAccount,aid);assert a.pelanggan_id==p[0].id and a.token_version==2
            assert security.cek_sandi('new-password',a.password_hash);new=issue(a)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={COOKIE:old}) as x:
            assert (await x.get('/pelanggan/stok')).status_code==401
        for active in ['0','0','1']:
            assert (await c.post(f'/pengguna/pelanggan/{aid}/status',data={'aktif':active,'_csrf':cap_formulir(c)})).status_code==303
        async with pg() as db:a=await db.get(PortalAccount,aid);assert a.active and a.token_version==4
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={COOKIE:new}) as x:
            assert (await x.get('/pelanggan/stok')).status_code==401


async def test_csrf_duplicate_contact_and_duplicate_username_are_guarded(pg,people):
    sid,p=people
    async with _klien(await _token(pg,sid)) as c:
        assert (await c.post('/pengguna/pelanggan/buat',data=form(p[0].id,601))).status_code==403
        assert (await create(c,form(p[0].id,601))).status_code==303
        assert (await create(c,form(p[1].id,602))).status_code==422
        async with pg() as db:
            db.add(Pelanggan(nama_pelanggan='Kontak ambigu',kledo_contact_id=602,status='aktif'));await db.commit()
        assert (await create(c,form(p[1].id,602,'another-account'))).status_code==422
