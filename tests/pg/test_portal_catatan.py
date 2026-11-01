"""Katalog konsisten, pencarian sebelum paginasi dan dokumen tetap native."""
from datetime import timedelta
from pathlib import Path
import json
import os
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select
from app.database import now_local
from app.models import MillingProcess,MillingProgressLog
from app.web.portal.security import CustomerReader
from app.web.portal.scope import load_scope
from app.services.serah_terima import daftar as bukti_native
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_portal_transaksi_detail import transaksi  # noqa: F401

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def catatan(pg,portal,transaksi):
    async with pg() as db:
        asal=await db.get(MillingProcess,portal.process[0]['giling'])
        db.add(MillingProgressLog(milling_process_id=asal.id,berat_kumulatif_kg=6500,
            waktu_update=now_local(),input_by=1))
        for n in range(28):
            db.add(MillingProcess(kode_proses=f'LOT-CATATAN-{n:02}',jasa_id=portal.orders[0].id,
                silo_id=asal.silo_id,status='selesai',waktu_mulai=now_local()-timedelta(days=n+2),
                waktu_selesai=now_local()-timedelta(days=n+1),created_by=1))
        db.add(MillingProcess(kode_proses='LOT-CATATAN-RAHASIA',jasa_id=portal.orders[1].id,
            silo_id=asal.silo_id,status='selesai',waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=1))
        await db.commit()
    return transaksi


def soup(r):
    assert r.status_code==200,r.text[:200]
    s=BeautifulSoup(r.text,'html.parser')
    assert len(s.select('main h1'))==1
    assert not s.select('main [data-post],main [data-aksi],main dialog,main form[method=post]')
    return s


async def test_daftar_pencarian_paginasi_urut_tanggal_dan_batas_pemilik(pg,portal,catatan):
    async with client(portal.accounts[0]) as c:
        for path,jenis in [('/pelanggan/riwayat-proses','giling'),('/pelanggan/laporan','proses')]:
            query=f'?jenis={jenis}&q=catatan'
            first=soup(await c.get(path+query));nextlink=first.select_one('nav.pelanggan-halaman-catatan a')
            assert nextlink and 'jenis='+jenis in nextlink['href'] and 'q=catatan' in nextlink['href']
            second=soup(await c.get(nextlink['href']))
            a=first.select('article.pelanggan-catatan-baris');b=second.select('article.pelanggan-catatan-baris')
            assert len(a)==25 and len(b)==3
            codes=[r.select_one('.pelanggan-kode').get_text(strip=True) for r in a+b]
            assert codes==[f'LOT-CATATAN-{n:02}' for n in range(28)]
            assert all(len(r.select('a[href]'))==1 for r in a+b)
            assert '28 ' in first.select_one('main [role=status]').get_text()
            empty=soup(await c.get(path+f'?jenis={jenis}&q=tidakada'))
            assert not empty.select('article.pelanggan-catatan-baris')
            assert empty.select_one('input[name=q]')['value']=='tidakada' and empty.select_one('a[href="'+path+'"]')
            assert not soup(await c.get(path+'?q=RAHASIA')).select('article.pelanggan-catatan-baris')
            bad=soup(await c.get(path+query+'&halaman=999'))
            assert len(bad.select('article.pelanggan-catatan-baris'))==3
        legacy=soup(await c.get('/pelanggan/serah-terima'))
        assert legacy.h1.get_text()=='Dokumen' and legacy.select_one('main form')['action']=='/pelanggan/laporan'
    async with client(portal.accounts[1]) as c:
        r=soup(await c.get('/pelanggan/riwayat-proses?q=RAHASIA'))
        assert 'LOT-CATATAN-RAHASIA' in r.main.get_text()
    async with client(portal.accounts[2]) as c:
        for path in ('riwayat-proses','laporan'):
            s=soup(await c.get('/pelanggan/'+path))
            assert not s.select('article.pelanggan-catatan-baris') and 'Belum ada catatan' in s.main.get_text()


async def test_katalog_bukti_sesuai_native_dan_pembaca_satu_judul_satu_kembali(pg,portal,catatan):
    from app.services.jasa import rekap_barang_jasa
    from app.services.jasa_pelanggan import kg_rinci
    scope=await load_scope(CustomerReader(portal.accounts[0].id,portal.owners[0].id,portal.owners[0].nama_pelanggan))
    async with pg() as db:
        native=await bukti_native(db,scope=scope)
        rekap=await rekap_barang_jasa(db,portal.orders[0].id)
    assert native
    out=Path(os.environ['BUKTI_PORTAL_CATATAN']) if os.environ.get('BUKTI_PORTAL_CATATAN') else None
    if out:out.mkdir(parents=True,exist_ok=True)
    async with client(portal.accounts[0]) as c:
        for jenis in ('masuk','pengambilan'):
            s=soup(await c.get('/pelanggan/laporan?jenis='+jenis))
            cards=s.select('article.pelanggan-catatan-baris')
            expected=[r for r in native if (r['jenis']=='Penerimaan')==(jenis=='masuk')]
            assert {r.select_one('.pelanggan-kode').get_text(strip=True) for r in cards}=={r['nomor'] for r in expected}
            for card in cards:
                href=card.select_one('a')['href'];doc=soup(await c.get(href))
                assert doc.h1.get_text() in ('Bukti barang masuk','Bukti pengambilan')
                assert len(doc.select('main a.rekap-back'))==1 and doc.select_one('a.rekap-back')['href']=='/pelanggan/laporan'
                assert not any(a.get_text(strip=True)=='Baca PDF' for a in doc.main.select('a'))
                assert len(doc.select('.rekap-actions a'))==1
                pdf=await c.get(href+'.pdf?unduh=1');assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
                if out:(out/(jenis+'-detail.html')).write_text(str(doc))
        for path in [f'/pelanggan/jasa/{portal.orders[0].id}/nota',f'/pelanggan/riwayat-giling/{portal.process[0]["giling"]}/laporan']:
            d=soup(await c.get(path))
            backs=[a for a in d.main.select('a') if a.get_text(strip=True).startswith('← Kembali')]
            assert len(backs)==1 and backs[0]['href']=='/pelanggan/laporan'
            if path.endswith('/nota'):
                assert kg_rinci(rekap['masuk_kg']) in d.main.get_text()
                assert kg_rinci(rekap['kembali_kg']) in d.main.get_text()
            if d.select_one('iframe'):
                pdf=await c.get(d.select_one('iframe')['src']);assert pdf.status_code==200
        report=soup(await c.get('/pelanggan/laporan?jenis=proses&q=LOT-QC-DETAIL'))
        link=report.select_one('article a')
        assert link and link['href'].endswith('/laporan.pdf') and 'Buka PDF' in link.get_text()
        pdf=await c.get(link['href']);assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
        pending=soup(await c.get(f'/pelanggan/barang-masuk/{catatan["masuk"]["belum-diukur"]}/serah-terima'))
        assert 'Dokumen akan tersedia setelah pemeriksaan mutu selesai.' in pending.main.get_text()
        assert 'QC' not in pending.main.get_text() and not pending.select('.rekap-actions a')
        if out:
            for name,path in [('riwayat','/pelanggan/riwayat-proses'),('dokumen','/pelanggan/laporan')]:
                (out/(name+'.html')).write_text((await c.get(path)).text)
            (out/'paths.json').write_text(json.dumps(dict(rekap=f'/pelanggan/jasa/{portal.orders[0].id}/nota',
                laporan=f'/pelanggan/riwayat-giling/{portal.process[0]["giling"]}/laporan',transaksi=catatan)))
