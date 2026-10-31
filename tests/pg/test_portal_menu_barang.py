"""Menu pelanggan membedakan riwayat proses, penerimaan dan pengambilan jasa."""
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select
from app.database import now_local
from app.models import DryingLot,PurchaseBatch,PkPurchaseBatch,OutgoingRecord,OutgoingItem
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401

pytestmark=pytest.mark.asyncio


async def test_batch_tanpa_pemeriksaan_mutu_tetap_bisa_dibuka(pg,portal):
    from app.models import PurchaseBatchQc,PurchaseBatchQcSample
    from sqlalchemy import delete
    async with pg() as db:
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-QC-KERING'))
        header=await db.scalar(select(PurchaseBatchQc).where(PurchaseBatchQc.purchase_batch_id==batch.id))
        await db.execute(delete(PurchaseBatchQcSample).where(PurchaseBatchQcSample.purchase_batch_qc_id==header.id))
        await db.delete(header);await db.commit()
    async with client(portal.accounts[0]) as c:
        page=await c.get('/pelanggan/riwayat-qc/gabah-kering/GB-QC-KERING')
        assert page.status_code==200 and 'GB-QC-KERING' in page.text
        assert 'Belum ada hasil pemeriksaan mutu' in page.text and '10.000 kg' in page.text
    async with client(portal.accounts[1]) as c:
        assert (await c.get('/pelanggan/riwayat-qc/gabah-kering/GB-QC-KERING')).status_code==404


async def test_riwayat_proses_hanya_selesai_dan_filter_tetap_milik_pelanggan(pg,portal):
    async with pg() as db:
        dry=await db.get(DryingLot,portal.process[0]['pengeringan'])
        dry.waktu_selesai_pendinginan=None
        await db.commit()
    async with client(portal.accounts[0]) as c:
        page=await c.get('/pelanggan/riwayat-proses')
        assert page.status_code==200
        body=BeautifulSoup(page.text,'html.parser').main.get_text()
        assert 'LOT-QC-DETAIL' in body and 'POL-PORTAL-0' in body and 'Selesai ' in body
        assert 'TRF-PORTAL-0' in body
        assert 'PGR-PORTAL-0' not in body and 'LOT-RAHASIA-B' not in body
        filtered=await c.get('/pelanggan/riwayat-proses?jenis=giling')
        body=BeautifulSoup(filtered.text,'html.parser').main.get_text()
        assert 'LOT-QC-DETAIL' in body and 'POL-PORTAL-0' not in body
        assert (await c.get('/pelanggan/riwayat-proses?pelanggan_id='+str(portal.owners[1].id))).status_code==404


async def test_barang_masuk_menu_sendiri_tanpa_penolakan_dan_pk_belum_diterima(pg,portal):
    async with pg() as db:
        rejected=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-QC-BASAH'))
        rejected.status_batch='ditolak'
        db.add(PkPurchaseBatch(kode_batch='PKB-BELUM-DITERIMA',jasa_id=portal.orders[0].id,
            berat_total_kg=None,tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),
            input_by=1,status_batch='baru',sumber_berat='menunggu'))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        for path in ('/pelanggan/barang-masuk','/pelanggan/barang-masuk?status=belum'):
            page=await c.get(path);assert page.status_code==200
            s=BeautifulSoup(page.text,'html.parser')
            assert s.select_one('.portal-sidebar [aria-current=page]').get_text(strip=True)=='Barang masuk'
            body=s.main.get_text()
            assert 'GB-QC-KERING' in body and 'PKB-QC-DETAIL' in body
            assert 'GB-QC-BASAH' not in body and 'PKB-BELUM-DITERIMA' not in body
            assert 'Belum diterima' not in body and 'Sudah diterima' in body


async def test_pengambilan_bukan_penjualan_dan_rencana_bukan_jumlah_aktual(pg,portal):
    async with pg() as db:
        for code,status,jid,kg in [('OUT-JASA-SELESAI','selesai',portal.orders[0].id,120),
            ('OUT-JASA-RENCANA','perintah',portal.orders[0].id,0),
            ('OUT-JUAL-ORANG-SAMA','selesai',None,999)]:
            r=OutgoingRecord(kode=code,pelanggan_id=portal.owners[0].id,tanggal=now_local().date(),
                waktu=now_local(),input_by=1,status=status)
            db.add(r);await db.flush()
            db.add(OutgoingItem(outgoing_record_id=r.id,item_type='pk_g2',jasa_id=jid,
                berat_kg=kg,berat_perintah_kg=500))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        page=await c.get('/pelanggan/barang-keluar');assert page.status_code==200
        s=BeautifulSoup(page.text,'html.parser')
        assert s.select_one('.portal-sidebar [aria-current=page]').get_text(strip=True)=='Pengambilan barang'
        body=s.main.get_text()
        assert 'OUT-JASA-SELESAI' in body and '120 kg' in body and 'Pengambilan selesai' in body
        assert 'OUT-JASA-RENCANA' in body and 'Menunggu dimuat' in body
        assert 'OUT-JUAL-ORANG-SAMA' not in body and '999' not in body and '500 kg' not in body
