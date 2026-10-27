"""998 kg tidak boleh menjadi 1.000 kg karena 20 karung berlabel 50 kg."""
import asyncio

import pytest
from sqlalchemy import func, select, update
from app.database import now_local
from app.models import (ActivityLog, BerasKeSilo, FinishedGoodsStock, Jasa, Pelanggan,
                        PolishingOutputLog, User)
from app.penggilingan.gudang2 import service as g2
from app.penggilingan.inventory import finished_goods as fg
from app.services.rencana_beras_silo import rincian
from app.services.undo import undo_last
from tests.pg.test_masukkan_beras_silo import sosoh, _kemas_grade
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio


async def pembelian(pg,g,*,jasa=False,berat=998,karung=20):
    await _kemas_grade(pg,g,grade='medium',jumlah_karung=karung,ukuran=50)
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock))
        row.source_type='timbangan';row.source_id=98765
        row.berat_total_kg=berat;row.kemasan_mengurangi_stok=False
        if jasa:
            pel=Pelanggan(nama_pelanggan='Pemilik beras 998 kg');db.add(pel);await db.flush()
            j=Jasa(kode='JAS-UJI-998',pelanggan_id=pel.id);db.add(j);await db.flush();row.jasa_id=j.id
        await db.commit()
        return dict(id=row.id,sku=row.product_sku_id,owner=row.jasa_id)


@pytest.mark.parametrize('jasa',[False,True])
async def test_http_1000_ditolak_998_masuk_dan_undo_tetap_998(pg,sosoh,jasa):
    s=await pembelian(pg,sosoh,jasa=jasa)
    jenis='medium|'+('jasa' if jasa else 'pabrik')
    source=f"sku:{s['sku']}|{s['owner'] if jasa else 'pabrik'}"
    async with await _klien(pg,sosoh['user'],'beras-998',mode='admin') as c:
        opts=(await c.get('/api/actions/beras-sumber-tersedia',params={'induk':jenis})).json()
        label=next(o['label'] for o in opts if o['value']==source)
        assert '998 kg' in label and '1.000 kg' not in label
        before=await c.get('/api/actions/rincian-beras-silo',params=dict(jenis=jenis,sumber_stok=source,berat_kg=1000,silo='C'))
        assert before.status_code==200
        assert before.json()['saldo_kg']==998 and before.json()['rencana'] is None
        req=dict(jenis=jenis,sumber_stok=source,berat_kg=1000,silo='C')
        bad=await c.post('/api/actions/masukkan-beras-silo',json=req,headers={'X-CSRF-Token':cap_formulir(c)})
        assert bad.status_code==400 and '998' in bad.text
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0
            row=await db.get(FinishedGoodsStock,s['id'])
            assert row.jumlah_karung==20 and float(row.berat_total_kg)==998
        preview=(await c.get('/api/actions/rincian-beras-silo',params=req|{'berat_kg':998})).json()
        assert preview['rencana']['karung']==20 and preview['rencana']['sisa_kg']==0
        ok=await c.post('/api/actions/masukkan-beras-silo',json=req|{'berat_kg':998},headers={'X-CSRF-Token':cap_formulir(c)})
        assert ok.status_code==200,ok.text
        assert ok.json()['rincian_beras']['kg']==998
        assert ok.json()['rincian_beras']['setelah']['saldo_kg']==0
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==998
        move=await db.scalar(select(BerasKeSilo))
        assert float(move.berat_kg)==998 and move.jasa_id==s['owner']
        assert move.source_type=='timbangan' and move.polishing_process_id is None
        log=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='beras_masuk_silo'))
        await undo_last(db,actor=await db.get(User,sosoh['user']),cakupan=None,log_id=log.id)
        row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_type=='timbangan'))
        assert row.jumlah_karung==20 and float(row.berat_total_kg)==998 and row.jasa_id==s['owner']


async def test_parsial_10_karung_dari_998_adalah_499_bukan_500(pg,sosoh):
    s=await pembelian(pg,sosoh)
    async with pg() as db:
        u=await db.get(User,sosoh['user'])
        with pytest.raises(g2.Gudang2Error):
            await g2.masukkan_beras_ke_silo(db,user=u,jenis='medium',sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=500)
        await db.rollback()
        for _ in range(2):
            await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',
                sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=499)
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg)))==998


async def test_fifo_beberapa_batch_memakai_berat_nyata_masing_masing(pg,sosoh):
    s=await pembelian(pg,sosoh,berat=499,karung=10)
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,s['id'])
        db.add(FinishedGoodsStock(product_sku_id=row.product_sku_id,rice_quality_standard_id=row.rice_quality_standard_id,
            source_type='timbangan',source_id=98766,jumlah_karung=10,berat_total_kg=505,
            warehouse_id=row.warehouse_id,waktu=now_local(),input_by=row.input_by,kemasan_mengurangi_stok=False))
        await db.commit()
        p=await rincian(db,'medium|pabrik',f"sku:{s['sku']}|pabrik",1004,'C')
        assert p['saldo_kg']==1004 and [x['kg'] for x in p['rencana']['fifo']]==[499,505]
        await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',
            sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=1004)
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg)))==1004


async def test_jalur_lama_juga_tidak_menambah_berat(pg,sosoh):
    s=await pembelian(pg,sosoh)
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,s['id']);row.source_type='polishing';row.source_id=sosoh['proc_id']
        await db.execute(update(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==sosoh['proc_id']).values(berat_kg=998))
        await db.commit()
        with pytest.raises(g2.Gudang2Error):
            await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',
                kode_pol=sosoh['kode_pol'],nama_silo='C',berat_kg=1000)
        await db.rollback()
        await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',
            kode_pol=sosoh['kode_pol'],nama_silo='C',berat_kg=998)
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg)))==998


async def test_dua_operator_tidak_memakai_stok_998_dua_kali(pg,sosoh):
    s=await pembelian(pg,sosoh)
    async def kirim():
        async with pg() as db:
            return await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',
                sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=998)
    result=await asyncio.gather(kirim(),kirim(),return_exceptions=True)
    assert sum(isinstance(x,g2.Gudang2Error) for x in result)==1,result
    async with pg() as db:
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg)))==998


async def test_berat_pecahan_karung_terakhir_menutup_total_batch(pg,sosoh):
    s=await pembelian(pg,sosoh,berat=149.99,karung=3)
    async with pg() as db:
        for kg in (50,99.99):
            await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',
                sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=kg)
        assert float(await db.scalar(select(func.sum(BerasKeSilo.berat_kg))))==149.99


@pytest.mark.parametrize('kg_keluar',[499,500])
async def test_pengeluaran_mengurangi_karung_dan_batas_berat_nyata(pg,sosoh,kg_keluar):
    from app.models import OutgoingRecord, OutgoingItem
    s=await pembelian(pg,sosoh)
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,s['id'])
        out=OutgoingRecord(kode='OUT-UJI-998',tanggal=now_local().date(),waktu=now_local(),
                           input_by=sosoh['user'],status='selesai')
        db.add(out);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=out.id,item_type='finished_goods',
            product_sku_id=row.product_sku_id,rice_quality_standard_id=row.rice_quality_standard_id,
            jumlah_karung=10,berat_kg=kg_keluar))
        await db.commit()
        p=await rincian(db,'medium|pabrik',f"sku:{s['sku']}|pabrik",499,'C')
        assert p['karung']==10 and p['saldo_kg']==998-kg_keluar
        if kg_keluar==500:
            # Selisih bobot pengiriman lama tidak menjadi tambahan isi silo.
            assert p['rencana'] is None
            with pytest.raises(g2.Gudang2Error,match='berat nyata'):
                await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),
                    jenis='medium',sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=499)
        else:
            assert p['rencana']['karung']==10
            await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),
                jenis='medium',sumber_stok=f"sku:{s['sku']}",nama_silo='C',berat_kg=499)
            stock=await fg.hitung_stok_finished_goods(db,s['sku'],row.rice_quality_standard_id)
            assert stock=={'karung':0,'kg':0}


async def test_penerimaan_tiket_menyimpan_998_dan_pemindahan_tidak_membulatkan(pg,sosoh,monkeypatch):
    from app.penggilingan.gudang1.services import timbang_link
    async def lock(*args,**kwargs):return None
    async def tiket(*args,**kwargs):
        return dict(id=98765,kode='TKT-UJI-998',arah='MASUK',jenis_kode='BERAS_MASUK',jasa=False)
    async def bobot(*args,**kwargs):return 998,False,'timbangan'
    monkeypatch.setattr(timbang_link,'kunci_tiket_untuk_ditaut',lock)
    monkeypatch.setattr(timbang_link,'ambil_tiket',tiket)
    monkeypatch.setattr(timbang_link,'bobot_awal_dari_tiket',bobot)
    async with await _klien(pg,sosoh['user'],'tiket-beras-998',mode='admin') as c:
        r=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':98765},
                       headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        async with pg() as db:
            row=await db.scalar(select(FinishedGoodsStock))
            assert row.jumlah_karung==20 and float(row.berat_total_kg)==998
            source=f'sku:{row.product_sku_id}|pabrik'
        req=dict(jenis='medium|pabrik',sumber_stok=source,berat_kg=1000,silo='C')
        bad=await c.post('/api/actions/masukkan-beras-silo',json=req,headers={'X-CSRF-Token':cap_formulir(c)})
        assert bad.status_code==400
        good=await c.post('/api/actions/masukkan-beras-silo',json=req|{'berat_kg':998},headers={'X-CSRF-Token':cap_formulir(c)})
        assert good.status_code==200,good.text
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==998
