"""Laporan periode membaca kueri sungguhan, termasuk pembatalan dan PDF."""
from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import text
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio
D=date(2026,11,11)

async def test_semua_tahap_kueri_dan_pdf_kosong(pg):
    from app.services.laporan_periode import TAHAP, ambil
    from app.web.pdf_periode import buat_pdf
    async with pg() as db:
        for kode in TAHAP:
            data=await ambil(db,kode,D,D)
            assert data['rincian']==[]
            assert data['ringkasan'][0]['nilai']=='0'
            assert buat_pdf(data).startswith(b'%PDF-')

async def test_cermin_batal_dan_batas_tanggal(pg,pemakai,pemasok):
    from app.models import PurchaseBatch
    from app.services.laporan_periode import ambil
    zona=ZoneInfo('Asia/Jakarta')
    async with pg() as db:
        for i,tgl in enumerate([date(2026,11,10),D,D,date(2026,11,12)],1):
            db.add(PurchaseBatch(kode_batch=f'GB-PER-{i}',supplier_id=pemasok.id,
                 berat_total_kg=1000*i,kondisi_gabah='kering',tanggal_pembelian=tgl,
                 waktu_pembelian=datetime.combine(tgl,datetime.min.time(),zona),
                 input_by=pemakai.id,status_batch='di_silo',
                 dibatalkan_pada=datetime.now(zona) if i==3 else None))
        await db.commit()
        data=await ambil(db,'gabah_masuk',D,D)
        assert [r['kode'] for r in data['rincian']]==['GB-PER-2']
        assert data['ringkasan'][1]['nilai']=='2.000'

@pytest.mark.parametrize('peran,gudang',[('superadmin',None),('admin',None),('operator','Gudang 1'),('operator','Gudang 2')])
async def test_laporan_pdf_dan_rentang_per_peran(pg,peran,gudang):
    async with await _klien(pg,peran=peran,gudang=gudang) as c:
        r=await c.get('/laporan')
        assert r.status_code==200 and 'href="/laporan/gabah_masuk"' in r.text
        assert '<dialog class="lembar lembar--laporan"' not in r.text
        params=dict(periode='khusus',dari='2026-11-11',sampai='2026-11-11')
        detail=await c.get('/laporan/gabah_masuk',params=params)
        assert detail.status_code==200
        from bs4 import BeautifulSoup
        import json
        halaman=BeautifulSoup(detail.text,'html.parser')
        assert halaman.select_one('[data-laporan-detail]')
        assert halaman.select_one('select[name=periode] option[selected]')['value']=='khusus'
        assert halaman.select_one('.desktop-back')['href']=='/laporan'
        pdf_url=halaman.select_one('.lp-pdf-utama')['href']
        assert 'periode=khusus' in pdf_url and 'dari=2026-11-11' in pdf_url
        r=await c.get('/api/laporan/tahap_gabah_masuk',params=params)
        assert json.loads(halaman.select_one('#laporan-data').string)==r.json()['data']
        assert r.status_code==200 and r.json()['data']['rincian']==[]
        r=await c.get('/laporan-periode/gabah_masuk.pdf',params=params)
        assert r.status_code==200 and r.content.startswith(b'%PDF-')
        assert r.headers['content-type']=='application/pdf'
        assert 'inline;' in r.headers['content-disposition']
        r=await c.get('/laporan-periode/gabah_masuk.pdf',params={**params,'unduh':'true'})
        assert 'attachment;' in r.headers['content-disposition']
        for path in ('/api/laporan/tahap_gabah_masuk','/laporan-periode/gabah_masuk.pdf','/laporan/gabah_masuk'):
            assert (await c.get(path,params={'periode':'khusus'})).status_code==422
            assert (await c.get(path,params={**params,'sampai':'2026-11-01'})).status_code==422
        assert (await c.get('/laporan-periode/tidak-dikenal.pdf')).status_code==404
        assert (await c.get('/laporan/tidak-dikenal')).status_code==404
        assert (await c.get('/laporan/gabah_masuk?periode=asing')).status_code==422

async def test_pdf_tanpa_sesi_ditolak(pg):
    import httpx
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        r=await c.get('/laporan-periode/gabah_masuk.pdf')
        assert r.status_code in (303,401)

@pytest.mark.parametrize('nota,barang,netto,timbang2,expected_nota,expected_timbang,mengikuti',[
    (10000,9950,10000,5000,'10.000','9.950',False),
    (None,9950,10000,5000,'9.950','9.950',True),
    (0,0,10000,5000,'10.000','10.000',True),
    (10000,0,0,None,'10.000','Belum tercatat',False),
    (None,None,None,None,'Belum tercatat','Belum tercatat',False),
])
async def test_nota_dan_timbangan_terpisah(pg,pemakai,pemasok,nota,barang,netto,timbang2,expected_nota,expected_timbang,mengikuti):
    from app.models import PurchaseBatch
    from app.services.laporan_periode import ambil
    from app.database import now_local
    async with pg() as db:
        tid=await db.scalar(text('''INSERT INTO timbangan_transaksi
            (kode,tanggal,arah,jenis_kode,cara_timbang,supplier_id,nomor_polisi,timbang1_kg,timbang1_waktu,
             status_tiket,status_transaksi,timbang2_kg,berat_acuan_kg,berat_barang_kg,netto_timbangan_kg)
             VALUES ('TB-PER',:tgl,'MASUK','GABAH_KERING','DUA_KALI',:sid,'B 1 PER',15000,NOW(),
                     'TERBUKA','AKTIF',:dua,:nota,:barang,:netto) RETURNING id'''),
             dict(tgl=D,sid=pemasok.id,dua=timbang2,nota=nota or 0,barang=barang or 0,netto=netto or 0))
        db.add(PurchaseBatch(kode_batch='GB-NOTA-PER',supplier_id=pemasok.id,berat_total_kg=10000,
             kondisi_gabah='kering',tanggal_pembelian=D,waktu_pembelian=now_local(),input_by=pemakai.id,
             status_batch='di_silo',timbangan_transaksi_id=tid))
        await db.commit()
        data=await ambil(db,'gabah_masuk',D,D)
        r=data['rincian'][0]
        assert r['nota']==expected_nota and r['timbangan']==expected_timbang
        assert (r['sumber_nota']=='Mengikuti timbangan')==mengikuti
        if mengikuti:
            assert r['selisih']=='0'

async def test_katalog_hanya_laporan_periode_dan_kode_lama_dihapus(pg):
    import re
    from app.services.laporan_periode import TAHAP
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/laporan')
        assert r.status_code==200
        assert set(re.findall(r'data-laporan="([^"]+)"',r.text))=={'tahap_'+k for k in TAHAP}
        assert 'href="/serah-terima"' not in r.text
        for kode in ['pending_verifikasi','produksi','jam_kedatangan','pembelian_gabah','supplier','rekap_bulanan','musiman']:
            assert (await c.get('/api/laporan/'+kode)).status_code==404
