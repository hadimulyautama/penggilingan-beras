"""Daftar produk menuju detail dengan angka dan pemilik yang tetap sama."""
from pathlib import Path
import re

import pytest
from sqlalchemy import select
from app.database import now_local
from app.models import Jasa, Pelanggan, User
from app.penggilingan.gudang2.models import PolishingProcess, PolishingOutputLog
from hmu_identitas.peran import SUPERADMIN, OPERATOR
from tests.pg.test_stok_produk_jasa import sosoh_jasa, _packing
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


async def test_baris_produk_membuka_detail_dan_kemasan_tetap_terpisah_per_pemilik(pg,sosoh_jasa):
    await _packing(pg,sosoh_jasa,kode_pol=sosoh_jasa['kode_pabrik'],karung=40)
    await _packing(pg,sosoh_jasa,kode_pol=sosoh_jasa['kode_jasa'],karung=20)
    async with pg() as db:
        # Kedatangan kedua pelanggan yang sama tetap satu detail pelanggan.
        j=Jasa(kode='JAS-2610-002',pelanggan_id=sosoh_jasa['pelanggan_id'],status='berjalan')
        db.add(j);await db.flush()
        p=PolishingProcess(kode_proses='POL-KEDATANGAN-2',status='selesai',
            waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=sosoh_jasa['user'],jasa_id=j.id)
        db.add(p);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='medium',berat_kg=500,
                                 waktu_update=now_local(),input_by=sosoh_jasa['user']))
        # Hasil samping juga mempunyai detail.
        asal=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==sosoh_jasa['kode_pabrik']))
        db.add(PolishingOutputLog(polishing_process_id=asal.id,jenis='broken',berat_kg=125,
                                 waktu_update=now_local(),input_by=sosoh_jasa['user']))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        for nama,path,pemilik,angka,kode in [
            ('pabrik','/stok-produk','Pabrik','9.000',sosoh_jasa['kode_pabrik']),
            ('jasa','/stok-produk-jasa','Bu Sri','5.500',sosoh_jasa['kode_jasa']),
        ]:
            daftar=await c.get(path)
            assert daftar.status_code==200
            url=re.search(r'href="([^"]+/detail\?[^"]*jenis=medium)"',daftar.text)[1].replace('&amp;','&')
            assert daftar.text.count('jenis=medium"')==1
            assert 'stok-produk-baris__detail' not in daftar.text
            r=await c.get(url)
            assert r.status_code==200
            for s in [pemilik,angka,kode,'Ringkasan stok','Perkiraan asal stok (FIFO)','Asal stok dan produk kemasan']:
                assert s in r.text
            assert ('20' if nama=='jasa' else '40') in r.text
            if nama=='jasa':
                assert 'POL-KEDATANGAN-2' in r.text
                assert sosoh_jasa['kode_pabrik'] not in r.text
            else:
                assert sosoh_jasa['kode_jasa'] not in r.text and 'Bu Sri' not in r.text
            Path('/tmp/hmu-produk-'+nama+'-daftar.html').write_text(daftar.text)
            Path('/tmp/hmu-produk-'+nama+'-detail.html').write_text(r.text)
        r=await c.get('/stok-produk/detail?jenis=broken')
        assert r.status_code==200 and '2 karung × 50 kg' in r.text
        assert '25' in r.text
        Path('/tmp/hmu-produk-broken-detail.html').write_text(r.text)
        for path in ['/stok-produk/detail','/stok-produk/detail?jenis=tidak-ada',
                     '/stok-produk-jasa/detail?jenis=medium',
                     '/stok-produk-jasa/detail?jenis=medium&pelanggan_id=999999',
                     f'/stok-produk-jasa/detail?jenis=tidak-ada&pelanggan_id={sosoh_jasa["pelanggan_id"]}']:
            assert (await c.get(path)).status_code==404


async def test_halaman_detail_mengikuti_akses_gudang_daftar(pg,sosoh_jasa):
    for gudang,status in [('Gudang 1',403),('Gudang 2',200)]:
        async with await _klien(pg,peran=OPERATOR,gudang=gudang) as c:
            for path in ['/stok-produk/detail?jenis=medium',
                         f'/stok-produk-jasa/detail?jenis=medium&pelanggan_id={sosoh_jasa["pelanggan_id"]}']:
                r=await c.get(path)
                assert r.status_code==status
                if status==200:
                    assert 'Pindah kepemilikan' not in r.text
