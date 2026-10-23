"""Detail pendinginan lintas status, durasi, sumber, dokumen dan izin asli."""
import io
import json
import os
from pathlib import Path
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from tests.pg.test_detail_pengeringan_tab import dryer_tab, pengeringan, dryer_pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pendingin(pg, dryer_tab):
    from app.models import User
    from app.penggilingan.gudang1.services.drying import finish_drying
    async with pg() as db:
        await finish_drying(db,user=await db.get(User,dryer_tab['user']),kode_lot=dryer_tab['kode'],kadar_air_akhir=18)
    return dryer_tab


@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_tiga_status_tab_sumber_laporan_dan_akses(pg,pendingin,peran):
    from app.models import User, SiloStorage
    from app.penggilingan.gudang1.services import drying as dr
    from app.penggilingan.gudang1.services.silo import masuk_silo
    from pypdf import PdfReader
    from app.web import csrf
    from app.web.lihat_sebagai import NAMA_KUKI
    kode, ident = pendingin['kode'], pendingin['id']
    aktif='/proses-aktif/pendinginan/'+kode
    riwayat='/riwayat-pengeringan/'+str(ident)
    async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
        c.headers[csrf.NAMA_HEADER]=cap_formulir(c)
        for status in ['Sedang didinginkan','Sudah dingin','Sudah di silo']:
            url=aktif if status=='Sedang didinginkan' else riwayat
            for tab in ['ringkasan','bahan','pengukuran','riwayat']:
                h=await c.get(url+'?tab_detail='+tab)
                assert h.status_code==200
                assert h.text.count('role="tab"')==4 and f'aria-labelledby="tab-{tab}" >' in h.text
                for teks in [status,'10.000 kg','16,0%','18,0%',pendingin['batch'],pendingin['tambahan'],
                             'TK-DR-TAB','B 4321 UJI','Titik 4','Putaran pendinginan','Catatan pendinginan','Total jeda pengeringan']:
                    assert teks in h.text,teks
                assert 'buka=kadar_air' not in h.text and 'buka=selesai_pengeringan' not in h.text
                assert '<progress' not in h.text
                if status=='Sedang didinginkan':
                    assert 'buka=selesai_pendinginan' in h.text and 'Lihat / bagikan laporan PDF' not in h.text
                elif status=='Sudah dingin':
                    assert 'buka=pindah_silo' in h.text and 'buka=mulai_pendinginan_ulang' in h.text
                    assert 'Masih di ' in h.text and 'Lihat / bagikan laporan PDF' in h.text
                else:
                    assert 'Sudah dipindah ke Silo A' in h.text
                    assert 'buka=pindah_silo' not in h.text and 'buka=mulai_pendinginan_ulang' not in h.text
            if status=='Sedang didinginkan':
                assert (await c.get(riwayat+'/laporan')).status_code==404
                assert (await c.get(riwayat+'/laporan.pdf')).status_code==404
                if os.environ.get('UJI_POTRET_PENDINGINAN') and peran=='admin':
                    Path('/tmp/pendinginan-khusus-session.json').write_text(json.dumps({'url':aktif,'history':riwayat,'id':ident,'kode':kode,'cookies':dict(c.cookies)}))
                    return
                assert (await c.post('/api/actions/selesai-pendinginan',json={'kode_lot':kode})).status_code==200
                async with pg() as db:
                    assert await db.scalar(select(func.count()).select_from(SiloStorage))==0
                assert (await c.get(aktif)).url.path==riwayat
                alias=await c.get(aktif+'?tab_detail=bahan&halaman_ukur=2')
                assert alias.url.path==riwayat and 'aria-labelledby="tab-bahan" >' in alias.text
                assert alias.url.params['halaman_ukur']=='2'
            elif status=='Sudah dingin':
                viewer=await c.get(riwayat+'/laporan')
                pdf=await c.get(riwayat+'/laporan.pdf')
                unduh=await c.get(riwayat+'/laporan.pdf?unduh=1')
                assert viewer.status_code==pdf.status_code==unduh.status_code==200
                assert 'Bagikan PDF' in viewer.text and 'attachment' in unduh.headers['content-disposition']
                teks='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
                for kata in [kode,'Pengukuran','Pendinginan',pendingin['batch']]:
                    assert kata.lower() in teks.lower(),kata
                # Pernyataan berulang tetap didukung dan tidak memindahkan stok.
                assert (await c.post('/api/actions/selesai-pendinginan',json={'kode_lot':kode})).status_code==200
                assert (await c.post('/api/actions/pindah-silo',json={'kode_lot':kode,'silo':'A'})).status_code==200
            else:
                assert (await c.post('/api/actions/mulai-pendinginan-ulang',json={'kode_lot':kode})).status_code==400
                assert (await c.post('/api/actions/selesai-pendinginan',json={'kode_lot':kode})).status_code==400
                assert (await c.post('/api/actions/pindah-silo',json={'kode_lot':kode,'silo':'A'})).status_code==400
                async with pg() as db:
                    assert await db.scalar(select(func.count()).select_from(SiloStorage))==1
        c.cookies.set(NAMA_KUKI,'operator:g2')
        for path in [aktif,riwayat,riwayat+'/laporan',riwayat+'/laporan.pdf']:
            assert (await c.get(path)).status_code==403
        assert (await c.post('/api/actions/selesai-pendinginan',json={'kode_lot':kode})).status_code==403


async def test_ulang_pagination_waktu_riwayat_dan_konteks(pg,pendingin):
    from app.models import User, DryingLot
    from app.penggilingan.gudang1.services import drying as dr
    kode,ident=pendingin['kode'],pendingin['id']
    async with pg() as db:
        u=await db.get(User,pendingin['user'])
        await dr.finish_cooling(db,user=u,kode_lot=kode)
        await dr.mulai_pendinginan_ulang(db,user=u,kode_lot=kode)
        for n in range(21):
            await dr.log_cooling(db,user=u,kode_lot=kode,catatan=f'Pemeriksaan putaran ulang {n}')
        lot=await db.get(DryingLot,ident)
        assert lot.waktu_selesai_pendinginan is None
    async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
        url='/proses-aktif/pendinginan/'+kode
        riwayat='/riwayat-pengeringan/'+str(ident)
        r=await c.get(riwayat)
        assert r.url.path==url
        for page in [1,2]:
            h=await c.get(url+f'?halaman_dingin={page}')
            assert 'aria-labelledby="tab-riwayat" >' in h.text
            assert 'Putaran 2' in h.text and 'Putaran 1' in h.text
            assert '2 putaran' in h.text and 'buka=pindah_silo' not in h.text
            assert '16,0%' in h.text and '18,0%' in h.text
        assert (await c.get(riwayat+'/laporan.pdf')).status_code==404
        b=await c.get(url+'?buka=selesai_pendinginan&nilai='+kode+'&kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan')
        assert 'data-buka="selesai_pendinginan"' in b.text and 'kembali_kerja=' in b.text


async def test_durasi_terakhir_beku_tidak_dikurangi_jeda_dan_legacy(pg,pendingin,monkeypatch):
    from app.database import now_local
    from app.models import User, DryingLot, DryingMoistureLog
    from app.services import berjalan, proses_aktif, detail_pendinginan
    from app.penggilingan.gudang1.services import drying as dr
    from sqlalchemy import delete
    async with pg() as db:
        u=await db.get(User,pendingin['user'])
        await dr.finish_cooling(db,user=u,kode_lot=pendingin['kode'])
        lot=await db.get(DryingLot,pendingin['id'])
        t=now_local()-timedelta(hours=4)
        lot.waktu_mulai_pengeringan=t-timedelta(hours=6)
        lot.waktu_selesai_pengeringan=t
        lot.waktu_mulai_pendinginan=t
        lot.waktu_selesai_pendinginan=t+timedelta(hours=2)
        await db.commit()
        kartu=berjalan.Baris(kode=lot.kode_lot,isi='Riwayat',keadaan='selesai',fase='dryer')
        d=await proses_aktif.rincian(db,jenis='pendinginan',model=lot,kartu=kartu,params={})
        # Rekap jeda lama tetap informasi terpisah, tidak memotong pendinginan.
        d['fakta'].append(('Total jeda pengeringan','1 jam'))
        monkeypatch.setattr(detail_pendinginan,'now_local',lambda: t+timedelta(days=1))
        await detail_pendinginan.lengkapi(db,lot=lot,detail=d)
        assert d['lama_pendinginan']=='2 jam 0 menit'
        assert ('Lama pendinginan','2 jam 0 menit') in d['fakta']
        assert d['putaran'][-1]['lama']=='2 jam 0 menit'
        assert ('Sejak pernyataan dingin','22 jam 0 menit') in d['waktu_pendinginan']
        # Tidak mengarang durasi atau pengukuran nol pada data warisan tak lengkap.
        lot.waktu_mulai_pendinginan=None
        lot.waktu_selesai_pengeringan=None
        await db.execute(delete(DryingMoistureLog))
        await db.commit()
        d=await proses_aktif.rincian(db,jenis='pendinginan',model=lot,kartu=kartu,params={})
        await detail_pendinginan.lengkapi(db,lot=lot,detail=d)
        assert d['lama_pendinginan']=='Belum dapat dihitung'
        assert d['tes']=='Belum diukur' and d['mesin']=='Belum diukur'


async def test_rincian_warisan_tanggal_pembelian_dan_presisi_batch(pg,pendingin):
    from app.models import PurchaseBatch, User
    from app.penggilingan.gudang1.services import drying as dr
    async with pg() as db:
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==pendingin['batch']))
        batch.berat_total_kg=8000.12
        batch.tanggal_pembelian=batch.tanggal_pembelian-timedelta(days=2)
        tanggal=batch.tanggal_pembelian.strftime('%d/%m/%Y')
        await db.commit()
        await dr.finish_cooling(db,user=await db.get(User,pendingin['user']),kode_lot=pendingin['kode'])
    async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
        r=await c.get('/riwayat-pengeringan/'+str(pendingin['id'])+'?tab_detail=bahan')
        assert r.status_code==200
        assert '8.000,12 kg' in r.text and 'Tanggal pembelian '+tanggal in r.text
