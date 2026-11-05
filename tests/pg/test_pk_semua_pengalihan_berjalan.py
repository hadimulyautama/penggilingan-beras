"""Semua pemilik tampil secara default; hasil PK tercatat boleh dialihkan."""
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
import asyncio

from bs4 import BeautifulSoup
import pytest
from sqlalchemy import delete, select

from app.database import now_local
from app.models import (User, MillingProcess, MillingProgressLog,
    MillingProcessSource, PurchaseBatch, Silo, SiloStorage)
from app.penggilingan.gudang1.services import milling as m
from app.services import pk_kepemilikan as pk, pk_persediaan as persediaan
from hmu_identitas import peran as P
from tests.pg.test_pk_kepemilikan import world, initial
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.test_tiket_antrean_produksi import _klien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def live(pg, world):
    w = world
    async with pg() as db:
        now = now_local()
        silo = await db.scalar(select(Silo).where(Silo.warehouse_id == w['warehouses'][0]).limit(1))
        b = PurchaseBatch(kode_batch='GB-JASA-AKTIF', jasa_id=w['jasa'],
            kondisi_gabah='kering', berat_total_kg=10000, sumber_berat='manual',
            tanggal_pembelian=now.date(), waktu_pembelian=now, input_by=w['user'], status_batch='digiling')
        db.add(b)
        await db.flush()
        storage = SiloStorage(silo_id=silo.id, purchase_batch_id=b.id, tipe_masuk='langsung_kering',
            jasa_id=w['jasa'], tanggal_masuk=now, input_by=w['user'], status='kosong')
        proc = MillingProcess(kode_proses='LOT-JASA-AKTIF', warehouse_id=w['warehouses'][0],
            silo_id=silo.id, jasa_id=w['jasa'], berat_gabah_masuk_kg=10000, bobot_masuk_final=True,
            status='proses', waktu_mulai=now-timedelta(minutes=1), created_by=w['user'])
        db.add_all([storage, proc])
        await db.flush()
        db.add(MillingProcessSource(milling_process_id=proc.id, silo_storage_id=storage.id,
            purchase_batch_id=b.id, berat_kg=10000, berat_akhir_kg=0, berat_terpakai_kg=10000))
        db.add(MillingProgressLog(milling_process_id=proc.id, berat_kumulatif_kg=5000,
            waktu_update=now, input_by=w['user']))
        await db.commit()
        return {**w, 'proc':proc.id, 'code':proc.kode_proses,
                'live_sources':['giling:'+str(proc.id)]}


@pytest.mark.parametrize('role,gudang_index', [(P.ADMIN,None),(P.SUPERADMIN,None),(P.OPERATOR,0),(P.OPERATOR,1)])
async def test_default_semua_pemilik_filter_tetap_bekerja_dan_get_tidak_menulis(pg, live, role, gudang_index):
    w = live
    wid = w['warehouses'][gudang_index] if gudang_index is not None else None
    async with await _klien(pg, role=role, gudang_id=wid) as c:
        async with pg() as db:before = await sidik(db)
        r = await c.get('/stok')
        assert r.status_code == 200, r.text[:300]
        soup = BeautifulSoup(r.text,'html.parser')
        assert soup.select_one('#sk-filter [name=pemilik] option[selected]')['value']=='semua'
        assert 'LOT-PK-001' in r.text
        if gudang_index==1:assert w['code'] not in r.text and 'Pemilik jasa PK' not in r.text
        else:assert w['code'] in r.text and 'Pemilik jasa PK' in r.text
        assert 'Semua kepemilikan' in soup.select_one('.sk-cakupan').get_text()
        assert soup.select_one('#sk-filter [name=gudang] option[selected]')['value']==''
        reset = soup.find('a',string='Atur ulang filter')['href']
        assert parse_qs(urlsplit(reset).query)['pemilik']==['semua']
        for link in soup.select('.sk-tab a[href]'):
            if 'tab=bahan' not in link['href']:assert 'pemilik=semua' not in link['href']
        pabrik = await c.get('/stok?pemilik=pabrik')
        jasa = await c.get('/stok?pemilik=jasa')
        assert pabrik.status_code==jasa.status_code==200
        assert w['code'] not in pabrik.text and 'LOT-PK-001' in pabrik.text
        assert ('LOT-PK-001' not in jasa.text)
        assert (w['code'] in jasa.text)==(gudang_index!=1)
        g1 = await c.get('/stok?gudang=g1')
        g2 = await c.get('/stok?gudang=g2')
        assert g1.status_code==g2.status_code==200
        assert (w['code'] in g1.text)==(gudang_index!=1)
        # Selepan mempertahankan cakupan gudang lamanya; perubahan ini hanya
        # membuka seluruh pemilik pada gudang yang boleh dibaca.
        if gudang_index != 0:assert w['code'] not in g2.text
        async with pg() as db:assert await sidik(db)==before


async def test_hasil_lot_aktif_muncul_di_pilihan_dan_tombol_detail(pg, live):
    w = live
    async with pg() as db:
        before=await sidik(db)
        choices=await pk.pilihan(db,user=await db.get(User,w['user']))
        source=next(s for s in choices['sumber'] if s['sumber']==w['live_sources'][0])
        assert source['owner']==w['jasa'] and Decimal(source['tersedia'])==5000
        assert await sidik(db)==before
    async with await _klien(pg,role=P.ADMIN) as c:
        r=await c.get('/stok/pk/detail',params={'gudang':'g1','kode':w['code'],'jasa':'1'})
        assert r.status_code==200,r.text[:300]
        assert BeautifulSoup(r.text,'html.parser').find('a',string='Alihkan ke pabrik')


async def test_alih_hasil_aktif_tambahan_hasil_milik_asal_dan_finalisasi_tetap_bekerja(pg, live):
    w=live
    case={**w,'sources':w['live_sources'],'warehouses':[w['warehouses'][0]]}
    async with pg() as db:
        user=await db.get(User,w['user'])
        result,_=await initial(db,case,amount=1000,dari=w['jasa'],ke=None)
        assert (await db.get(MillingProcess,w['proc'])).status=='proses'
        await m.log_progress(db,user=user,kode_proses=w['code'],berat_kumulatif=7000)
        source=(await persediaan.baca(db))[w['live_sources'][0]]
        assert source.bebas(w['jasa'])==6000 and source.bebas(None)==1000
        assert source.stok.fisik_kg==7000
        before=await sidik(db)
        with pytest.raises(m.MillingError,match='pengalihan|pemilik'):
            await m.log_progress(db,user=user,kode_proses=w['code'],berat_kumulatif=900)
        assert await sidik(db)==before
        await m.log_progress(db,user=user,kode_proses=w['code'],berat_kumulatif=6500)
        await m.finish_milling(db,user=user,kode_proses=w['code'],berat_akhir=6500)
        await m.verify_milling_output(db,user=user,kode_proses=w['code'],berat_output=6500)
        source=(await persediaan.baca(db))[w['live_sources'][0]]
        assert source.bebas(w['jasa'])==5500 and source.bebas(None)==1000
        assert source.stok.fisik_kg==6500
        with pytest.raises(m.MillingError,match='riwayat pengalihan'):
            await m.verify_milling_output(db,user=user,kode_proses=w['code'],berat_output=6400)


@pytest.mark.parametrize('index',[0,1])
async def test_sumber_lama_tanpa_kolom_gudang_tetap_terbaca(pg, world, index):
    from app.models import PkGudang2Intake
    w=world
    async with pg() as db:
        key=w['sources'][index]
        ident=int(key.split(':')[1])
        row=await db.get(MillingProcess if index==0 else PkGudang2Intake,ident)
        row.warehouse_id=None
        await db.commit()
        before=await sidik(db)
        source=(await persediaan.baca(db))[key]
        assert source.stok.gudang.id==w['warehouses'][index]
        assert source.bebas(None)==1000
        choices=await pk.pilihan(db,user=await db.get(User,w['user']))
        assert any(s['sumber']==key for s in choices['sumber'])
        assert await sidik(db)==before


async def test_belum_ada_hasil_tidak_menjadi_sumber_pengalihan(pg, live):
    w=live
    async with pg() as db:
        await db.execute(delete(MillingProgressLog).where(MillingProgressLog.milling_process_id==w['proc']))
        await db.commit()
        choices=await pk.pilihan(db,user=await db.get(User,w['user']))
        assert not any(s['sumber']==w['live_sources'][0] for s in choices['sumber'])


async def test_pengalihan_dan_pengurangan_hasil_serentak_tidak_menghabiskan_bagian_yang_sama(pg, live):
    w=live
    case={**w,'sources':w['live_sources'],'warehouses':[w['warehouses'][0]]}
    async def alih():
        async with pg() as db:
            try:
                await initial(db,case,amount=4500,dari=w['jasa'],ke=None)
                return 'ok'
            except (pk.umum.InventoryError,persediaan.PersediaanError):
                await db.rollback()
                return 'ditahan'
    async def koreksi():
        async with pg() as db:
            try:
                await m.log_progress(db,user=await db.get(User,w['user']),
                    kode_proses=w['code'],berat_kumulatif=4000)
                return 'ok'
            except m.MillingError:
                await db.rollback()
                return 'ditahan'
    assert sorted(await asyncio.gather(alih(),koreksi()))==['ditahan','ok']
    async with pg() as db:
        source=(await persediaan.baca(db))[w['live_sources'][0]]
        assert not source.masalah
        assert source.stok.fisik_kg in (4000,5000)
        assert source.bebas(w['jasa'])>=0 and source.bebas(None)>=0


async def test_gudang_lama_pengeluaran_dan_alokasi_tetap_mengurangi_sumber_yang_benar(pg, world):
    from app.models import OutgoingRecord, OutgoingItem, PkGudang2Intake
    from app.penggilingan.inventory.models import OUT_PERINTAH
    w=world
    async with pg() as db:
        it=await db.get(PkGudang2Intake,int(w['sources'][1].split(':')[1]))
        it.warehouse_id=None
        now=now_local()
        for kode,status,kg,perintah in [('OUT-LAMA-PK','selesai',100,100),('OUT-ALOKASI-PK',OUT_PERINTAH,0,300)]:
            rec=OutgoingRecord(kode=kode,warehouse_id=None,tanggal=now.date(),waktu=now,input_by=w['user'],status=status)
            db.add(rec)
            await db.flush()
            db.add(OutgoingItem(outgoing_record_id=rec.id,item_type='pk_g2',jasa_id=None,
                               berat_kg=kg,berat_perintah_kg=perintah))
        await db.commit()
        before=await sidik(db)
        sources=await persediaan.baca(db)
        assert sources[w['sources'][1]].stok.fisik_kg==900
        assert sources[w['sources'][1]].bebas(None)==600
        assert sources[w['sources'][2]].bebas(None)==1000
        assert await sidik(db)==before
