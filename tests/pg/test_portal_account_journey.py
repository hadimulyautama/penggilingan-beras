"""Real logins from a Super Admin's contact selection to a customer's scoped reads."""
from io import BytesIO

import httpx
import pytest
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select,func

from app.main import app
from app.models import Pelanggan,ProduksiAkun,User
from app.models.portal import PortalAccount
from app.web import security
from app.web.portal.security import COOKIE
from tests.pg.test_kelola_akun_http import _super
from tests.pg.test_portal_pelanggan import portal,token  # noqa: F401 (fixtures)
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401 (fixture)
from tests.pg.formulir import cap_formulir


def browser_client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji')


@pytest.mark.asyncio
@pytest.mark.parametrize('selected',[0,1])
async def test_contact_create_login_and_customer_boundary(pg,portal,selected):
    await _super(pg,username='journey-super',sandi='journey-super-pass')
    async with pg() as db:
        for index,owner in enumerate(portal.owners[:2]):
            row=await db.get(Pelanggan,owner.id);row.kledo_contact_id=90101+index
        db.add_all([Pelanggan(nama_pelanggan=f'Awal Kontak {i:02}',kledo_contact_id=90200+i,status='aktif') for i in range(35)])
        await db.commit()
        before_users=await db.scalar(select(func.count()).select_from(User))
        before_staff=await db.scalar(select(func.count()).select_from(ProduksiAkun))
    owner,foreign=portal.owners[selected],portal.owners[1-selected]
    username=f'journey-customer-{selected}'
    password='journey-customer-pass'

    # No forged or pre-issued Super Admin session: log in using the real form.
    async with browser_client() as admin:
        await admin.get('/masuk')
        result=await admin.post('/masuk',data={'username':'journey-super','sandi':'journey-super-pass','_csrf':cap_formulir(admin)})
        assert result.status_code==303 and security.NAMA_COOKIE in admin.cookies
        assert (await admin.get('/pengguna/pelanggan')).status_code==200
        first=(await admin.get('/pengguna/pelanggan/kontak')).json()
        assert len(first['items'])==20 and first['more']
        assert not any(x['value'].endswith(':'+str(owner.id)) for x in first['items'])
        matches=(await admin.get('/pengguna/pelanggan/kontak',params={'q':owner.nama_pelanggan})).json()['items']
        assert len(matches)==1
        choice=matches[0]['value']
        assert choice==f'{90101+selected}:{owner.id}'
        result=await admin.post('/pengguna/pelanggan/buat',data={
            'kontak':choice,'username':username,'sandi':password,'konfirmasi':password,
            'pelanggan_id':foreign.id,'peran':'superadmin','_csrf':cap_formulir(admin)})
        assert result.status_code==303 and result.headers['location'].endswith('?ok=dibuat')
    async with pg() as db:
        created=await db.scalar(select(PortalAccount).where(PortalAccount.username==username))
        assert created and created.active and created.pelanggan_id==owner.id
        assert await db.scalar(select(func.count()).select_from(User))==before_users
        assert await db.scalar(select(func.count()).select_from(ProduksiAkun))==before_staff

    # The new customer's password must work in a fresh browser without staff cookies.
    async with browser_client() as customer:
        login=await customer.get('/pelanggan/masuk')
        result=await customer.post('/pelanggan/masuk',data={'username':username,'sandi':password,'_csrf':token(login)})
        assert result.status_code==303 and result.headers['location']=='/pelanggan'
        assert COOKIE in customer.cookies and security.NAMA_COOKIE not in customer.cookies
        home=await customer.get('/pelanggan')
        assert home.status_code==200 and owner.nama_pelanggan in home.text
        forbidden=[foreign.nama_pelanggan,'Kabar rahasia B' if selected==0 else 'Hasil milik A',
                   'LOT-RAHASIA-B' if selected==0 else 'LOT-QC-DETAIL','Rahasia seluruh pabrik']
        for path in ['pekerjaan','stok','stok?tab=produk','stok?tab=karung','barang-masuk',
                     'barang-keluar','retur','riwayat-giling','riwayat-pengeringan',
                     'riwayat-sosoh','riwayat-transfer','riwayat-qc/gabah-basah',
                     'riwayat-qc/gabah-kering','riwayat-qc/pk-luar','riwayat-qc/pk-hasil-giling',
                     'laporan','kabar','audit']:
            result=await customer.get('/pelanggan/'+path)
            assert result.status_code==200,path
            assert all(value not in result.text for value in forbidden),path
            soup=BeautifulSoup(result.text,'html.parser')
            assert not soup.select('[data-post],[hx-post],[data-aksi],dialog'),path
        assert all(value not in home.text for value in forbidden)
        for kind in ['giling','pengeringan','sosoh','transfer']:
            own_id=portal.process[selected][kind]
            foreign_id=portal.process[1-selected][kind]
            assert (await customer.get(f'/pelanggan/riwayat-{kind}/{own_id}')).status_code==200
            for suffix in ['', '/laporan', '/laporan.pdf', '/laporan.pdf?unduh=1']:
                assert (await customer.get(f'/pelanggan/riwayat-{kind}/{foreign_id}{suffix}')).status_code==404
            if kind!='transfer':
                pdf=await customer.get(f'/pelanggan/riwayat-{kind}/{own_id}/laporan.pdf')
                assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
                content='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
                assert all(value not in content for value in forbidden)
        for path in [f'/pelanggan/jasa/pelanggan/{foreign.id}',
                     f'/pelanggan/stok?pelanggan_id={foreign.id}',
                     f'/pelanggan/stok?pelanggan_id={owner.id}&pelanggan_id={foreign.id}']:
            assert (await customer.get(path)).status_code==404
        for path in ['/','/pengaturan','/pengguna','/pengguna/pelanggan',
                     '/pengguna/pelanggan/kontak','/stok','/riwayat-giling','/api/actions']:
            result=await customer.get(path)
            assert result.status_code in (303,401,403,404),path
            if result.status_code==303:assert result.headers['location'].startswith('/masuk')
        # Even renaming the customer cookie cannot grant an internal session.
        portal_token=next(c.value for c in customer.cookies.jar if c.name==COOKIE)
        async with browser_client() as forged:
            forged.cookies.set(security.NAMA_COOKIE,portal_token)
            assert (await forged.get('/pengaturan')).status_code==303

    async with browser_client() as internal:
        await internal.get('/masuk')
        await internal.post('/masuk',data={'username':username,'sandi':password,'_csrf':cap_formulir(internal)})
        assert security.NAMA_COOKIE not in internal.cookies
        assert (await internal.get('/pengaturan')).status_code==303
