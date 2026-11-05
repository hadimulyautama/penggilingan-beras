"""Identitas tersimpan harus terbaca ulang tanpa restart dan tetap terisolasi."""
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace as N
import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy import text
from app.services.perusahaan import validasi,logo_png,simpan
from hmu_dokumen.perusahaan import Perusahaan,baca
from hmu_dokumen.document import PenyajiDokumen
from hmu_dokumen.tema import TemaPDF


def gambar():
    b=BytesIO();Image.new('RGB',(64,64),'green').save(b,format='PNG');return b.getvalue()

@pytest.mark.parametrize('data',[
    {'nama':'','alamat':'Jalan uji'},
    {'nama':'Uji','alamat':'Jalan uji','website':'javascript:alert(1)'},
    {'nama':'Uji','alamat':'Jalan uji','email':'email-salah'},
])
def test_tolak_data_tidak_sah(data):
    with pytest.raises(ValueError):validasi(data)

@pytest.mark.parametrize('raw',[b'bukan gambar',b'x'*(2*1024*1024+1)])
def test_logo_tidak_sah(raw):
    with pytest.raises(ValueError):logo_png(raw)

@pytest.mark.asyncio
async def test_simpan_baca_ulang_dan_logo_tetap_tersimpan(monkeypatch):
    from app.services import perusahaan as service
    audit=[]
    async def log(db,**kw):audit.append(kw)
    monkeypatch.setattr(service,'log_activity',log)
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as c:
        await c.execute(text('CREATE TABLE setelan_pabrik (kunci VARCHAR(64) PRIMARY KEY, nilai TEXT NOT NULL, diubah_oleh INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)'))
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    data=dict(nama='PT Contoh Baru',alamat='Jalan Uji 1',telepon='0812345678',email='uji@example.com',website='https://example.com')
    async with sessions() as db:
        await simpan(db,data,logo=gambar(),user=N(id=1))
    async with sessions() as db:
        pertama=await baca(db)
        assert pertama.nama==data['nama'] and pertama.logo
        await simpan(db,dict(data,nama='PT Nama Diubah'),user=N(id=1))
    async with sessions() as db:
        kedua=await baca(db)
        assert kedua.nama=='PT Nama Diubah' and kedua.logo==pertama.logo
        await simpan(db,data,logo_bawaan=True,user=N(id=1))
        assert not (await baca(db)).logo
    assert 'sha256:' in audit[0]['new_value'] and pertama.logo not in audit[0]['new_value']
    await engine.dispose()


def test_kop_panjang_logo_dan_tema_berubah_di_seluruh_halaman():
    from reportlab.platypus import PageBreak
    company=Perusahaan(nama='PT Contoh Perusahaan',alamat='Jalan Contoh Panjang '*12,
        telepon='0800000',email='contoh@example.com',website='https://example.com',logo=logo_png(gambar()))
    theme=replace(TemaPDF(),font='Courier',font_tebal='Courier-Bold',utama='#663399')
    view=PenyajiDokumen(tema_pdf=theme,perusahaan=company)
    reader=PdfReader(BytesIO(view.pdf([view.p('Halaman pertama'),PageBreak(),view.p('Halaman kedua')],judul='Contoh',referensi='REF-UJI')))
    assert len(reader.pages)==2
    assert reader.metadata.author==company.nama
    for n,page in enumerate(reader.pages,1):
        t=' '.join(page.extract_text().split())
        assert company.nama in t and company.website in t and f'{n} / 2' in t
        assert len(page.images)==1
        assert 'Courier' in str(page['/Resources']['/Font'].get_object()) or any('Courier' in str(f.get_object()) for f in page['/Resources']['/Font'].values())

@pytest.mark.asyncio
async def test_identitas_pdf_tidak_bocor_ke_panggilan_berikutnya(monkeypatch):
    from app.web import pdf_dokumen as mod
    class Sesi:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(mod,'SessionLocal',Sesi)
    async def baca_baru(db):return Perusahaan(nama='Identitas baru')
    monkeypatch.setattr(mod,'baca',baca_baru)
    def gagal(data):
        assert mod.PenyajiDokumen().perusahaan.nama=='Identitas baru'
        raise ValueError('uji')
    with pytest.raises(ValueError):await mod.buat_pdf_terkini(gagal,{})
    assert mod.PenyajiDokumen().perusahaan.nama!='Identitas baru'
