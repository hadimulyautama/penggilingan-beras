"""Setiap sumber beras dan kemasan membawa pemiliknya sendiri ke formulir."""
from html import unescape
from pathlib import Path
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select
from app.database import now_local
from app.models import User, FinishedGoodsStock, ProductSku
from app.penggilingan.gudang2.models import PolishingOutputLog
from app.penggilingan.inventory.finished_goods import catat_packing
from app.services import barang_keluar as bk
from hmu_identitas.peran import SUPERADMIN, ADMIN, OPERATOR
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


async def test_tabel_kemasan_curah_dan_tombol_per_sumber_tanpa_rincian_barang_keluar(pg,sosoh_jasa):
    async with pg() as db:
        user=await db.get(User,sosoh_jasa['user'])
        user.role=SUPERADMIN
        await db.commit()
        for kode,ukuran,jumlah in [(sosoh_jasa['kode_pabrik'],25,4),
                                   (sosoh_jasa['kode_pabrik'],50,3),
                                   (sosoh_jasa['kode_jasa'],25,4)]:
            await catat_packing(db,user=user,kode_pol=kode,kategori='beras_putih',grade='medium',
                                material_kode='biasa',ukuran=ukuran,jumlah_karung=jumlah)
        sku=await db.scalar(select(ProductSku).where(ProductSku.kategori=='beras_putih'))
        std=await db.scalar(select(FinishedGoodsStock.rice_quality_standard_id))
        kode_keluar=[]
        for owner in [None,sosoh_jasa['jasa_id']]:
            rec=await bk.buat_perintah(db,user=user,jasa_id=owner,
                pelanggan_id=sosoh_jasa['pelanggan_id'],
                baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=sku.id,
                                        std_id=std,jumlah_karung=1)])
            await bk.muat_semua(db,user=user,rec_id=rec.rec.id)
            await bk.verifikasi(db,user=user,rec_id=rec.rec.id)
            kode_keluar.append(rec.rec.kode)
        # Keempat hasil samping mempunyai tabel; bekatul tidak punya alur silo.
        from app.models import PolishingProcess
        pid=await db.scalar(select(PolishingProcess.id).where(
            PolishingProcess.kode_proses==sosoh_jasa['kode_pabrik']))
        jasa_pid=await db.scalar(select(PolishingProcess.id).where(
            PolishingProcess.kode_proses==sosoh_jasa['kode_jasa']))
        for jenis in ['broken','menir','reject','bekatul']:
            for process_id in [pid,jasa_pid]:
                db.add(PolishingOutputLog(polishing_process_id=process_id,jenis=jenis,berat_kg=125,
                                         waktu_update=now_local(),input_by=user.id))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        menu=(await c.get('/api/actions/menu')).json()
        Path('/tmp/hmu-kemasan-menu.json').write_text(json.dumps(menu))
        Path('/tmp/hmu-kemasan-jenis.json').write_text(json.dumps(
            (await c.get('/api/actions/beras-jenis-silo')).json()))
        for nama,path,owner,n in [
            ('pabrik','/stok-produk/detail?jenis=medium','pabrik',3),
            ('jasa',f'/stok-produk-jasa/detail?jenis=medium&pelanggan_id={sosoh_jasa["pelanggan_id"]}',str(sosoh_jasa['jasa_id']),2)]:
            r=await c.get(path)
            assert r.status_code==200
            assert 'aria-label="Produk kemasan dan curah"' in r.text
            assert r.text.count('data-masuk-silo=')==n
            assert 'Sudah keluar' in r.text and '25 kg' in r.text
            assert all(kode not in r.text for kode in kode_keluar)
            assert 'pengiriman lainnya' not in r.text and 'Sudah keluar ·' not in r.text
            scope='pabrik' if owner=='pabrik' else 'jasa'
            Path('/tmp/hmu-kemasan-sumber-'+nama+'.json').write_text(json.dumps(
                (await c.get('/api/actions/beras-sumber-tersedia',params={'induk':'medium|'+scope})).json()))
            for href in re.findall(r'href="([^"]+)" data-masuk-silo=',r.text):
                q=parse_qs(urlsplit(unescape(href)).query)
                assert q['nilai']==['medium|'+('pabrik' if owner=='pabrik' else 'jasa')]
                assert q['sumber_stok'][0].endswith('|'+owner)
                assert urlsplit(unescape(href)).path==path.split('?')[0]
                d=await c.get(unescape(href))
                assert 'data-sumber-stok="'+q['sumber_stok'][0]+'"' in d.text
                Path('/tmp/hmu-kemasan-form-'+nama+'-'+q['sumber_stok'][0].split('|')[0].replace(':','-')+'.html').write_text(d.text)
            Path('/tmp/hmu-kemasan-'+nama+'.html').write_text(r.text)
        for jenis in ['broken','menir','reject','bekatul']:
            r=await c.get('/stok-produk/detail?jenis='+jenis)
            assert r.status_code==200 and 'data-bentuk-stok=' in r.text
            assert r.text.count('data-masuk-silo=')==(0 if jenis=='bekatul' else 2)
            if jenis=='broken':assert 'nilai=pemilik%7Cpabrik' in r.text
            Path('/tmp/hmu-kemasan-'+jenis+'.html').write_text(r.text)
            j=await c.get(f'/stok-produk-jasa/detail?jenis={jenis}&pelanggan_id={sosoh_jasa["pelanggan_id"]}')
            assert j.status_code==200
            assert j.text.count('data-masuk-silo=')==(0 if jenis=='bekatul' else 2)
            if jenis=='broken':assert f'nilai=pemilik%7C{sosoh_jasa["jasa_id"]}' in j.text
            Path('/tmp/hmu-kemasan-jasa-'+jenis+'.html').write_text(j.text)
    async with await _klien(pg,peran=ADMIN) as c:
        r=await c.get('/stok-produk/detail?jenis=medium')
        assert 'data-masuk-silo=' not in r.text


async def test_beras_b_kemasan_dapat_dipilih_dan_hanya_mengurangi_sumber_yang_dipilih(pg,sosoh_jasa):
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.models import PolishingProcess,Silo,Warehouse
    async with pg() as db:
        user=await db.get(User,sosoh_jasa['user']);user.role=SUPERADMIN
        pid=await db.scalar(select(PolishingProcess.id).where(
            PolishingProcess.kode_proses==sosoh_jasa['kode_pabrik']))
        db.add(PolishingOutputLog(polishing_process_id=pid,jenis='beras_b',berat_kg=1000,
                                 waktu_update=now_local(),input_by=user.id))
        await db.commit()
        await catat_packing(db,user=user,kode_pol=sosoh_jasa['kode_pabrik'],kategori='beras_b',
                            grade=None,material_kode='biasa',ukuran=25,jumlah_karung=4)
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))
        db.add(Silo(nama_silo='Silo Beras Uji',warehouse_id=wid,jenis_isi='beras'))
        await db.commit()
        sku=await db.scalar(select(ProductSku).where(ProductSku.kategori=='beras_b'))
    async with await _klien(pg,peran=SUPERADMIN) as c:
        opsi=(await c.get('/api/actions/beras-sumber-tersedia?induk=beras_b%7Cpabrik')).json()
        assert any(o['value']==f'sku:{sku.id}|pabrik' for o in opsi)
    async with pg() as db:
        await masukkan_beras_ke_silo(db,user=await db.get(User,sosoh_jasa['user']),jenis='beras_b',
                                    sumber_stok=f'sku:{sku.id}',nama_silo='Beras Uji',berat_kg=25)
        stok=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.product_sku_id==sku.id))
        assert stok.jumlah_karung==3 and stok.berat_total_kg==75
