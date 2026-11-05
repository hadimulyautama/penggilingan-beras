"""Formulir nyata, penyimpanan uji terisolasi, dan PDF terbaru tanpa restart."""
from types import SimpleNamespace as N
from io import BytesIO
import pytest
from fastapi import FastAPI
from httpx import AsyncClient,ASGITransport
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from tests.test_perusahaan_dokumen import gambar

@pytest.mark.asyncio
async def test_simpan_formulir_dan_pdf_memakai_data_baru(monkeypatch):
    from app.web import perusahaan as web,pdf_dokumen
    from app.services import perusahaan as service
    from app.web.perusahaan import butuh_perusahaan
    from app.web.rekap_jasa import buat_pdf
    from tests.test_pdf_rekap_jasa import contoh
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as c:
        await c.execute(text('CREATE TABLE setelan_pabrik (kunci VARCHAR(64) PRIMARY KEY, nilai TEXT NOT NULL, diubah_oleh INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)'))
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(web,'SessionLocal',sessions);monkeypatch.setattr(pdf_dokumen,'SessionLocal',sessions)
    async def audit(*args,**kwargs):pass
    monkeypatch.setattr(service,'log_activity',audit)
    app=FastAPI();app.include_router(web.router)
    app.dependency_overrides[butuh_perusahaan]=lambda:N(user=N(id=1))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as client:
        r=await client.get('/pengaturan/perusahaan');assert r.status_code==200 and 'multipart/form-data' in r.text
        data=dict(nama='PT Perusahaan Baru',alamat='Jalan Baru 123',telepon='080000',email='baru@example.com',website='https://example.com')
        r=await client.post('/pengaturan/perusahaan',data=data,files={'logo':('logo.png',gambar(),'image/png')})
        assert r.status_code==303
        r=await client.get('/pengaturan/perusahaan');assert 'PT Perusahaan Baru' in r.text and 'data:image/png;base64,' in r.text
        raw=await pdf_dokumen.buat_pdf_terkini(buat_pdf,contoh())
        t=' '.join(PdfReader(BytesIO(raw)).pages[0].extract_text().split())
        for v in data.values():assert v in t
        r=await client.post('/pengaturan/perusahaan',data=dict(data,nama=''),files={'logo':('gagal.txt',b'bukan gambar','text/plain')})
        assert r.status_code==422
        r=await client.get('/pengaturan/perusahaan');assert 'PT Perusahaan Baru' in r.text
    await engine.dispose()

@pytest.mark.asyncio
async def test_pengaturan_perusahaan_memerlukan_login():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as client:
        r=await client.get('/pengaturan/perusahaan')
        assert r.status_code in (303,401)

@pytest.mark.asyncio
@pytest.mark.parametrize('metode',['GET','POST'])
@pytest.mark.parametrize('peran',['admin','operator'])
async def test_non_super_ditolak_meski_tanpa_super_aktif(monkeypatch,metode,peran):
    from app.web import perusahaan as web,security
    from hmu_identitas import peran as P
    app=FastAPI();app.include_router(web.router)
    app.dependency_overrides[security.butuh_akun]=lambda:N(is_super=P.super_saja(peran))
    def jangan_buka_db():raise AssertionError('Izin harus ditolak sebelum membaca atau menulis data perusahaan')
    monkeypatch.setattr(web,'SessionLocal',jangan_buka_db)
    async def tanpa_super():raise AssertionError('Halaman perusahaan tidak memakai pintu darurat')
    monkeypatch.setattr(security,'ada_superadmin',tanpa_super)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as client:
        response=await client.request(metode,'/pengaturan/perusahaan')
        assert response.status_code==403

@pytest.mark.parametrize('boleh',[False,True])
def test_menu_perusahaan_hanya_terlihat_super(boleh):
    from pathlib import Path
    from jinja2 import Environment,DictLoader
    source=(Path(__file__).parents[1]/'app/web/templates/pengaturan_fasilitas.html').read_text()
    env=Environment(loader=DictLoader({'pengaturan.html':'{% block isi %}{% endblock %}', 'uji':source}))
    html=env.get_template('uji').render(BAGIAN='',blok_kelola=True,blok_perusahaan=boleh)
    assert ('/pengaturan/perusahaan' in html)==boleh
    assert '/pengaturan/fasilitas' in html
