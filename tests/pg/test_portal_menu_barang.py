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


async def test_daftar_masuk_memakai_baris_produksi_dan_bobot_penerimaan_asli(pg,portal):
    from sqlalchemy import text
    from app.services.barang_masuk import riwayat
    async with pg() as db:
        tid=await db.scalar(text("""INSERT INTO timbangan_transaksi
            (kode,tanggal,arah,jenis_kode,cara_timbang,pelanggan_id,jasa,jasa_id,
             nomor_polisi,timbang1_kg,timbang1_waktu,status_tiket,status_transaksi)
            VALUES ('TB-PORTAL-DAFTAR',CURRENT_DATE,'MASUK','GABAH_KERING','DUA_KALI',
             :p,true,:j,'AD 2468 LIST',15000,NOW(),'SELESAI','AKTIF') RETURNING id"""),
            {'p':portal.owners[0].id,'j':portal.orders[0].id})
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-QC-KERING'))
        batch.timbangan_transaksi_id=tid;await db.commit()
        native=(await riwayat(db,g1=True,g2=True,tid=tid,jasa_ids={portal.orders[0].id}))[0]
        assert native['berat_diterima']==10000
    async with client(portal.accounts[0]) as c:
        page=await c.get('/pelanggan/barang-masuk?cari=2468')
        assert page.status_code==200
        s=BeautifulSoup(page.text,'html.parser');rows=s.select('.masuk-daftar .masuk-baris')
        assert len(rows)==1
        row=rows[0]
        assert row.select_one('.masuk-identitas small').get_text()=='TB-PORTAL-DAFTAR'
        assert row.select_one('.masuk-armada').get_text()=='AD 2468 LIST'
        assert row.select_one('.masuk-bobot').get_text(strip=True)=='10.000 kg'
        assert row['href']==f'/pelanggan/barang-masuk/{tid}'
        assert 'SELESAI' not in row.get_text() and 'Sudah diterima' in row.get_text()
        pk=BeautifulSoup((await c.get('/pelanggan/barang-masuk?jenis=pk')).text,'html.parser')
        assert len(pk.select('.masuk-baris'))==1 and 'PKB-QC-DETAIL' in pk.main.get_text()
    async with client(portal.accounts[1]) as c:
        assert 'TB-PORTAL-DAFTAR' not in (await c.get('/pelanggan/barang-masuk')).text


async def test_daftar_masuk_paginasi_tetap_memuat_catatan_lama(pg,portal):
    async with pg() as db:
        for n in range(26):
            db.add(PurchaseBatch(kode_batch=f'GB-DAFTAR-LAMA-{n:02}',jasa_id=portal.orders[0].id,
                kondisi_gabah='kering',berat_total_kg=None if n==0 else 100,
                tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=1,
                status_batch='baru',sumber_berat='menunggu' if n==0 else 'manual'))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        a=BeautifulSoup((await c.get('/pelanggan/barang-masuk')).text,'html.parser')
        b=BeautifulSoup((await c.get('/pelanggan/barang-masuk?halaman=2')).text,'html.parser')
        assert len(a.select('.masuk-baris'))==25 and len(b.select('.masuk-baris'))==4
        codes=[r.select_one('.masuk-identitas small').get_text() for s in (a,b) for r in s.select('.masuk-baris')]
        assert len(set(codes))==29 and 'GB-DAFTAR-LAMA-00' in codes
        row=next(r for s in (a,b) for r in s.select('.masuk-baris') if 'GB-DAFTAR-LAMA-00' in r.get_text())
        assert 'Belum diukur' in row.select_one('.masuk-bobot').get_text() and '0 kg' not in row.get_text()


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
