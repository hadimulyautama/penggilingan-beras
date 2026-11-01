"""Rincian pelanggan mempertahankan penerimaan/keluar aktual dan batas pemilik."""
import json
import os
from pathlib import Path
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select,text
from app.database import now_local
from app.models import PurchaseBatch,PkPurchaseBatch,OutgoingRecord,OutgoingItem,KirimanKeluar
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_jasa_ketaatan import _tiket

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def transaksi(pg,portal):
    masuk={};keluar={}
    async with pg() as db:
        for code,model,kind in [('GB-QC-KERING',PurchaseBatch,'GABAH_KERING'),('PKB-QC-DETAIL',PkPurchaseBatch,'BERAS_PK')]:
            tid=await _tiket(db,kode='TB-DETAIL-'+kind,berat=9750.25,
                pelanggan_id=portal.owners[0].id,jasa_id=portal.orders[0].id,jenis=kind,nopol='AD 2345 MILIK')
            batch=await db.scalar(select(model).where(model.kode_batch==code));batch.timbangan_transaksi_id=tid
            await db.execute(text("UPDATE timbangan_transaksi SET nama_sopir='Sopir Uji',timbang2_kg=30000,timbang2_waktu=NOW(),berat_bermuatan_kg=30000,berat_kosong_kg=20000,total_tara_kg=249.75 WHERE id=:id"),{'id':tid})
            masuk[kind]=tid
        tid=await _tiket(db,kode='TB-DETAIL-BELUM-DIUKUR',berat=None,
            pelanggan_id=portal.owners[0].id,jasa_id=portal.orders[0].id,jenis='GABAH_BASAH')
        db.add(PurchaseBatch(kode_batch='GB-DETAIL-KOSONG',jasa_id=portal.orders[0].id,
            kondisi_gabah='basah',berat_total_kg=None,timbangan_transaksi_id=tid,
            tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=1,
            status_batch='baru',sumber_berat='menunggu',flag_unverified=False))
        masuk['belum-diukur']=tid
        for status,kg in [('perintah',0),('dimuat',120.25),('selesai',120.25),('batal',0),('lama',120.25)]:
            selesai=status in ('selesai','lama')
            rec=OutgoingRecord(kode='OUT-DETAIL-'+status.upper(),jasa_id=portal.orders[0].id,
                pelanggan_id=portal.owners[0].id,nama_pembeli=portal.owners[0].nama_pelanggan,
                tanggal=now_local().date(),waktu=now_local(),waktu_perintah=now_local(),diperintah_oleh=1,
                waktu_muat=now_local() if kg else None,dimuat_oleh=1 if kg else None,
                waktu_verifikasi=now_local() if selesai else None,
                diverifikasi_oleh=1 if selesai else None,
                input_by=1,status='selesai' if selesai else status,no_polisi='AD 2345 MILIK',nama_ekspedisi='Angkutan Uji',
                catatan_perintah='Catatan asli: QC 12 karung, jangan diubah.',
                sebab_batal='Pelanggan mengubah jadwal.' if status=='batal' else None)
            db.add(rec);await db.flush()
            db.add(OutgoingItem(outgoing_record_id=rec.id,item_type='pk_g2',
                jasa_id=portal.orders[0].id,berat_kg=kg,berat_perintah_kg=150.5))
            if selesai:
                tid=await _tiket(db,kode='TK-DETAIL-'+status,berat=121.25 if status=='lama' else kg,
                    pelanggan_id=portal.owners[0].id,jasa_id=portal.orders[0].id,jenis='BERAS_PK')
                rec.timbangan_transaksi_id=tid
                await db.execute(text("UPDATE timbangan_transaksi SET arah='KELUAR',timbang2_kg=20121.75,timbang2_waktu=NOW(),total_tara_kg=1.5,berat_barang_kg=:berat WHERE id=:id"),{'id':tid,'berat':None if status=='lama' else kg})
            keluar[status]=rec.id
        trip=KirimanKeluar(no_polisi='AD 9999 GABUNG');db.add(trip);await db.flush()
        for i,kg in [(0,200.5),(1,98765.25)]:
            rec=OutgoingRecord(kode='OUT-DETAIL-GABUNG-'+str(i),pelanggan_id=portal.owners[i].id,
                kiriman_id=trip.id,nama_pembeli=portal.owners[i].nama_pelanggan,
                tanggal=now_local().date(),waktu=now_local(),input_by=1,status='selesai')
            db.add(rec);await db.flush()
            db.add(OutgoingItem(outgoing_record_id=rec.id,item_type='pk_g2',jasa_id=portal.orders[i].id,berat_kg=kg))
            keluar['gabung' if i==0 else 'asing']=rec.id
        await db.commit()
    return dict(masuk=masuk,keluar=keluar)


def periksa(r):
    assert r.status_code==200,r.text[:200]
    s=BeautifulSoup(r.text,'html.parser');body=s.main.get_text(' ',strip=True)
    assert len(s.select('main h1'))==1
    assert len([a for a in s.select('main a') if a.get_text(strip=True).startswith('← Kembali')])==1
    assert not s.select('main [data-post],main [data-aksi],main dialog,main form[method=post]')
    assert all(x not in body for x in ('Rahasia Pelanggan B','98765','Tidak ada tindakan tersedia','Pihak pada tiket:','Pemilik catatan:','Rincian perintah','Snapshot','kompatibilitas'))
    here=r.request.url.path
    assert not [a for a in s.select('main a[href]') if a.get('role')!='tab' and a['href'].split('?')[0]==here]
    return s


async def test_detail_penerimaan_angka_asli_tab_mutu_dokumen_dan_berat_kosong(pg,portal,transaksi):
    async with client(portal.accounts[0]) as c:
        for kind,tid in transaksi['masuk'].items():
            for tab in ('ringkasan','tiket','qc','riwayat'):
                r=await c.get(f'/pelanggan/barang-masuk/{tid}?tab_detail={tab}');s=periksa(r)
                assert len(s.select('[role=tab]'))==4
                assert not s.select('#bagikan-pdf,.penerimaan-pemilik,.penerimaan-tindakan')
                assert len(s.select(f'a[href="/pelanggan/barang-masuk/{tid}/laporan.pdf?unduh=0"]'))==1
                assert len(s.select(f'a[href="/pelanggan/barang-masuk/{tid}/serah-terima"]'))==1
                weight=s.select_one('.penerimaan-bobot strong').get_text(strip=True)
                if kind=='belum-diukur':assert weight=='Belum diukur'
                else:
                    assert weight in ('10.000 kg','12.000 kg')
                    assert '9.750,25 kg' in s.main.get_text() and '249,75 kg' in s.main.get_text()
                    assert 'Contoh catatan laboratorium' in s.main.get_text() if kind=='BERAS_PK' else 'Kadar air' in s.main.get_text()
            pdf=await c.get(f'/pelanggan/barang-masuk/{tid}/laporan.pdf?unduh=0')
            assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
    async with client(portal.accounts[1]) as c:
        for tid in transaksi['masuk'].values():
            assert (await c.get(f'/pelanggan/barang-masuk/{tid}')).status_code==404
            assert (await c.get(f'/pelanggan/barang-masuk/{tid}/laporan.pdf')).status_code==404


async def test_pengambilan_aktif_selesai_batal_gabungan_tetap_angka_dan_catatan_asli(pg,portal,transaksi):
    out=Path(os.environ['BUKTI_PORTAL_TRANSAKSI']) if os.environ.get('BUKTI_PORTAL_TRANSAKSI') else None
    if out:out.mkdir(parents=True,exist_ok=True)
    async with client(portal.accounts[0]) as c:
        for status,oid in transaksi['keluar'].items():
            if status=='asing':continue
            for tab in ('ringkasan','barang','tiket','riwayat'):
                r=await c.get(f'/pelanggan/barang-keluar/{oid}?tab_detail={tab}');s=periksa(r)
                if out:(out/f'{status}-{tab}.html').write_text(r.text)
                assert s.select_one('main h1').get_text()=='Pengambilan barang'
                assert not s.select('.pengiriman-tab')
                if status in ('perintah','dimuat'):
                    assert len(s.select('[role=tab]'))==4
                    assert not any(h.get_text(strip=True)=='Tindakan saat ini' for h in s.select('h2'))
                if status in ('perintah','dimuat','selesai','batal'):
                    assert 'Catatan asli: QC 12 karung, jangan diubah.' in s.main.get_text()
                    assert '150,5' in s.main.get_text()
                if status=='dimuat':assert '120,25' in s.select_one('.kirim-detail__total').get_text()
                elif status=='selesai':assert s.select_one('.rk-number').get_text(strip=True)=='120,25 kg'
                elif status=='lama':
                    assert 'Berat bersih (catatan lama)' in s.main.get_text() and '121,25 kg' in s.main.get_text()
                    assert '1,5 kg' in s.main.get_text()
                elif status=='gabung':assert s.select_one('.rk-number').get_text(strip=True)=='200,5 kg'
                if status=='batal':assert 'Pelanggan mengubah jadwal.' in s.main.get_text()
            # Tautan lama tidak membuka kembali panel operator yang membingungkan.
            if status=='selesai':periksa(await c.get(f'/pelanggan/barang-keluar/{oid}?rincian_perintah=1'))
        assert (await c.get('/pelanggan/barang-keluar/'+str(transaksi['keluar']['asing']))).status_code==404
        if out:(out/'paths.json').write_text(json.dumps(transaksi))
