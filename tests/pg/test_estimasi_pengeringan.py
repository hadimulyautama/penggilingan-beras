from datetime import timedelta
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,text

from app.database import now_local
from app.models import DryingLot,DryingLotBatch,DryingMoistureLog,PurchaseBatch,SiloStorage
from app.services.estimasi_pengeringan import untuk_silo_banyak
from app.services import berjalan
from hmu_core.proses_db import ProsesTerpadu
from tests.pg.test_gabung_jasa import dunia
from tests.pg.test_portal_transit import _akun
from tests.pg.test_portal_pelanggan import client
from tests.pg.test_riwayat_pengeringan import _klien

pytestmark=pytest.mark.asyncio


async def buat(pg,d,*,huruf='A',jasa=None,kode='PGR-UJI-A',kg=30251.5):
    mulai=now_local()-timedelta(hours=15)
    async with pg() as db:
        lot=DryingLot(kode_lot=kode,jasa_id=jasa or d['jasa1'],dryer_id=d['dryer'],
            status='selesai',created_by=d['user'],waktu_mulai_pengeringan=mulai,
            waktu_selesai_pengeringan=mulai+timedelta(hours=13),
            waktu_selesai_pendinginan=mulai+timedelta(hours=14))
        db.add(lot);await db.flush()
        batch=PurchaseBatch(kode_batch='GB-'+kode,jasa_id=lot.jasa_id,berat_total_kg=kg,
            kondisi_gabah='basah',tanggal_pembelian=mulai.date(),waktu_pembelian=mulai,
            input_by=d['user'],flag_unverified=False,sumber_berat='timbangan',status_batch='di_silo')
        db.add(batch);await db.flush()
        storage=SiloStorage(silo_id=d['silo'][huruf],drying_lot_id=lot.id,tipe_masuk='dari_pengeringan',
            jasa_id=lot.jasa_id,status='terisi',tanggal_masuk=mulai+timedelta(hours=14),input_by=d['user'])
        db.add_all([DryingLotBatch(drying_lot_id=lot.id,purchase_batch_id=batch.id),storage])
        for minute,machine,manual in [(35,25.4,24.55),(100,None,10),(780,14.7,None),(900,9,9)]:
            db.add(DryingMoistureLog(drying_lot_id=lot.id,waktu_update=mulai+timedelta(minutes=minute),
                kadar_air_indikator=machine,kadar_air_tes_manual=manual,input_by=d['user']))
        db.add(ProsesTerpadu(aplikasi='produksi',tabel_sumber='drying_lots',id_sumber=str(lot.id),
            kode=kode,jenis='pengeringan',status='selesai',jenis_pemilik='jasa',id_pemilik=lot.jasa_id,
            waktu_mulai=mulai,waktu_selesai=lot.waktu_selesai_pengeringan,
            referensi_asal=[batch.kode_batch],metadata_domain={'kadar_air_akhir':14.7}))
        await db.commit()
        return lot.id,storage.id,batch.id


async def sidik(pg):
    async with pg() as db:
        return {n:await db.scalar(text(f"SELECT md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY id),'')) FROM {n} t"))
                for n in ['purchase_batches','drying_lots','drying_moisture_logs','silo_storage','activity_logs','proses_terpadu']}


async def test_dua_bobot_satu_sumber_di_produksi_portal_izin_dan_tidak_menulis(pg,dunia,tmp_path):
    await buat(pg,dunia)
    await buat(pg,dunia,huruf='B',jasa=dunia['jasa3'],kode='PGR-RAHASIA-B',kg=5000)
    account=await _akun(pg,dunia)
    # Akun uji dibentuk sebelum sidik; seluruh GET berikutnya harus baca saja.
    staff=await _klien(pg,peran='superadmin')
    before=await sidik(pg)
    async with staff as c:
        page=await c.get('/pekerjaan')
        assert page.status_code==200
        soup=BeautifulSoup(page.text,'html.parser')
        (tmp_path/'produksi.html').write_text(page.text)
        assert 'Bobot gabah basah masuk' in soup.get_text()
        assert '30.251,50 kg' in soup.get_text() and '26.456,76 kg' in soup.get_text()
        assert soup.select('.bobot-pengeringan')
        for widget in soup.select('.bobot-pengeringan'):
            card=widget.find_parent('details')
            if card:
                assert len(card.select('.bobot-pengeringan'))==1
                assert widget.find_parent('summary')
                assert card.select('.anak__baris')  # Expand retains original sources.
                assert card.select('.pilihan__satu')  # Operational entry points retained.

    async with client(account) as c:
        for path in ['/pelanggan/jasa-saya','/pelanggan/pekerjaan?tab=tindakan']:
            page=await c.get(path);assert page.status_code==200
            soup=BeautifulSoup(page.text,'html.parser');body=soup.get_text(' ',strip=True)
            assert 'Berat gabah saat masuk' in body and 'Perkiraan setelah kering' in body
            assert '30.251,5 kg' in body and '26.456,76 kg' in body
            assert 'PGR-RAHASIA-B' not in body and '4.372' not in body
            assert not soup.select('[data-post],[data-aksi],form[action*="mulai_giling"]')
            # Dua bobot selalu di luar rincian yang tersembunyi.
            for metric in soup.select('.bobot-pengeringan,.pelanggan-bobot-proses'):
                for detail in metric.find_parents('details'):
                    summary=detail.find('summary',recursive=False)
                    assert detail.has_attr('open') or (summary and metric in summary.descendants)
            if path=='/pelanggan/jasa-saya':(tmp_path/'portal.html').write_text(page.text)
    assert await sidik(pg)==before


async def test_borongan_lot_tidak_tercampur_dan_saldo_asli_tetap(pg,dunia,hitung_kueri):
    lid,storage,bid=await buat(pg,dunia)
    await buat(pg,dunia,huruf='B',jasa=dunia['jasa3'],kode='PGR-UJI-B',kg=5000)
    async with pg() as db:
        async with hitung_kueri() as n:values=await untuk_silo_banyak(db,list(dunia['silo'].values()))
        assert n.jumlah==5
        assert values[dunia['silo']['A']][0]['kering']=='26.456,76 kg'
        assert values[dunia['silo']['B']][0]['kering']=='4.372,80 kg'
        from app.penggilingan.gudang1.services.silo import _lot_bobot,_row_bobot
        assert (await _lot_bobot(db,lid)).kg==30251.5
        row=await db.get(SiloStorage,storage);row.dikemas_kg=500;await db.commit()
        values=await untuk_silo_banyak(db,[dunia['silo']['A']])
        assert values[dunia['silo']['A']][0]['historis']
        assert (await _row_bobot(db,row)).kg==29751.5
        batch=await db.get(PurchaseBatch,bid);assert batch.berat_total_kg==Decimal('30251.50')
        process=await db.scalar(select(ProsesTerpadu).where(ProsesTerpadu.id_sumber==str(lid)))
        process.referensi_asal=['BATCH-LAIN'];await db.commit()
        assert (await untuk_silo_banyak(db,[dunia['silo']['A']]))[dunia['silo']['A']][0]['kering'] is None
        process.referensi_asal=[batch.kode_batch]
        batch.retur_supplier_keluar_kg=100;await db.commit()
        value=(await untuk_silo_banyak(db,[dunia['silo']['A']]))[dunia['silo']['A']][0]
        assert value['basah']=='30.251,50 kg' and value['kering'] is None


@pytest.mark.parametrize('role,warehouse,view,visible',[
    ('admin',None,None,True),('operator','Gudang 1','operator:g1',True),
    ('operator','Gudang 2','operator:g2',False),
    ('superadmin',None,'operator:g2',False),
])
async def test_peran_efektif_tetap_membatasi_kartu(pg,dunia,role,warehouse,view,visible):
    await buat(pg,dunia)
    async with await _klien(pg,peran=role,gudang=warehouse,lihat=view) as c:
        if view:c.cookies.set('produksi_lihat',view)
        response=await c.get('/pekerjaan')
        assert response.status_code==200
        soup=BeautifulSoup(response.text,'html.parser')
        assert bool(soup.select('.bobot-pengeringan'))==visible


@pytest.mark.parametrize('tahap',['pendinginan','dingin','silo','masih-drying'])
async def test_beranda_barang_dua_bobot_langsung_setelah_drying_selesai(pg,dunia,tmp_path,tahap):
    from sqlalchemy import delete
    from app.web.portal.scope import load_scope
    from app.web.portal.security import CustomerReader
    from app.web.portal.barang import baca
    from app.services import jasa_pelanggan
    lid,storage,bid=await buat(pg,dunia)
    await buat(pg,dunia,huruf='B',jasa=dunia['jasa3'],kode='PGR-RAHASIA-B',kg=5000)
    async with pg() as db:
        lot=await db.get(DryingLot,lid)
        if tahap!='silo':
            await db.execute(delete(SiloStorage).where(SiloStorage.id==storage))
            batch=await db.get(PurchaseBatch,bid);batch.status_batch='diproses'
            if tahap in ('pendinginan','masih-drying'):lot.waktu_selesai_pendinginan=None
            if tahap=='masih-drying':
                lot.status='proses';lot.waktu_selesai_pengeringan=None
            await db.commit()
    account=await _akun(pg,dunia)
    before=await sidik(pg)
    async with client(account) as c:
        for path,nama in [('/pelanggan/','beranda'),('/pelanggan/barang-saya','barang')]:
            page=await c.get(path);assert page.status_code==200
            soup=BeautifulSoup(page.text,'html.parser')
            assert 'PGR-RAHASIA-B' not in page.text
            metrics=soup.select('.pelanggan-bobot-drying .bobot-pengeringan')
            if tahap=='masih-drying':
                assert not metrics and '26.456,76 kg' not in page.text
            else:
                assert len(metrics)==1
                body=metrics[0].get_text(' ',strip=True)
                assert '30.251,50 kg' in body and '26.456,76 kg' in body
                assert 'Bobot gabah basah masuk' in body and 'Estimasi bobot gabah kering' in body
                assert not metrics[0].find_parent('details')
                # Wet receipt is not presented as measured dry stock in collapsed heading.
                assert '30.251' not in soup.select_one('#komoditas-gabah>summary').get_text()
                assert not soup.select('[data-post],[data-aksi]')
            (tmp_path/f'{nama}-{tahap}.html').write_text(page.text)
    assert await sidik(pg)==before
    scope=await load_scope(CustomerReader(1,dunia['catur'],'Catur'))
    async with pg() as db:
        d=await jasa_pelanggan.pelanggan(db,dunia['catur'],rinci=False,read_scope=scope)
        groups=await baca(db,scope,d)
        assert groups[0]['kg']==Decimal('30251.50')  # Existing ledger reader is unchanged.
        assert (await db.get(PurchaseBatch,bid)).berat_total_kg==Decimal('30251.50')
