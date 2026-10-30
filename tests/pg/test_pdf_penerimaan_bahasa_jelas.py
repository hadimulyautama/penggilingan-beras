"""Desain baru memakai data nyata layanan pada database uji, bukan angka mockup."""
from datetime import timedelta
import pytest
from sqlalchemy import select,text,delete
from app.database import now_local
from app.models import PkPurchaseBatch,PkPurchaseQcLog,Pelanggan,Jasa,User
from tests.pg.test_masuk_detail_timbang import contoh,catat  # noqa: F401
from tests.pg.test_pdf_penerimaan import penerimaan,isi,bukti  # noqa: F401
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize('jasa',[False,True])
async def test_desain_jasa_dan_supplier_dari_penerimaan_sebenarnya(pg,penerimaan,jasa):
    nama='Supplier Uji'
    if jasa:
        async with pg() as db:
            pel=Pelanggan(nama_pelanggan='Pemilik penerimaan uji');db.add(pel);await db.flush()
            order=Jasa(kode='JAS-PDF-BAHASA-UJI',pelanggan_id=pel.id);db.add(order);await db.flush()
            b=await db.get(PkPurchaseBatch,penerimaan['bid']);b.jasa_id=order.id;b.supplier_id=None
            await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,jasa_id=:j,supplier_id=NULL WHERE id=:t'),dict(p=pel.id,j=order.id,t=penerimaan['tid']))
            await db.commit();nama=pel.nama_pelanggan
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf');pdf,teks=isi(r);flat=' '.join(teks.split())
        bukti('hasil-jasa.pdf' if jasa else 'hasil-supplier.pdf',r.content)
        assert len(pdf.pages)==1
        assert ('Pemilik barang:' if jasa else 'Supplier:') in flat and flat.count(nama)==1
        for value in ['PK (beras pecah kulit)','BERAT BARANG DITERIMA','Butir patah','Kandungan gabah','Susut uji','persentase penyusutan/bekatul','Kesimpulan:',
                      '5 pemeriksaan QC','rata-rata kadar air 13,0%','Potongan berat karung/kemasan: 15,00 kg','potongan lain: 1,00 kg; total: 16,00 kg',
                      'Lebih berat 184,00 kg (1,31%) dari nota; masih dalam batas kontrol.']:
            assert value in flat,value
        for value in ['RANCANGAN','DATA CONTOH','Gudang','Milik pabrik','Broken','Nilai kualitas:']:
            assert value not in teks


async def test_tanggal_dan_pencatat_berbeda_tetap_jelas(pg,penerimaan):
    t=now_local();awal=t-timedelta(days=2);kedua=t-timedelta(days=1)
    async with pg() as db:
        orang=User(nama='Pemeriksa lintas hari',role='operator',status='aktif');db.add(orang);await db.flush()
        logs=(await db.scalars(select(PkPurchaseQcLog).order_by(PkPurchaseQcLog.id))).all()
        logs[0].input_by=orang.id;logs[0].waktu=awal
        await db.execute(text('UPDATE timbangan_transaksi SET timbang1_waktu=:a,timbang2_waktu=:b WHERE id=:i'),dict(a=awal,b=kedua,i=penerimaan['tid']))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf');_,teks=isi(r);flat=' '.join(teks.split())
        assert awal.strftime('%d/%m/%Y') in flat and kedua.strftime('%d/%m/%Y') in flat and t.strftime('%d/%m/%Y') in flat
        assert 'Pemeriksa lintas hari' in flat and 'Penerima Uji' in flat
        bukti('lintas-tanggal-pencatat.pdf',r.content)


@pytest.mark.parametrize('n',[1,5,10,20,50])
async def test_kapasitas_putaran_sah_tanpa_pemotongan(pg,penerimaan,n):
    async with pg() as db:
        await db.execute(delete(PkPurchaseQcLog))
        for i in range(n):
            db.add(PkPurchaseQcLog(pk_purchase_batch_id=penerimaan['bid'],kadar_air=13+i/10,
                broken_persen=20,susut_persen=10,butir_kuning='bersih',gabah='bersih',merang='bersih',
                catatan_lab=f'LAB-ASLI-{i+1:03}',waktu=now_local()+timedelta(seconds=i),input_by=penerimaan['uid']))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf?putaran=1&halaman=1');pdf,teks=isi(r)
        assert f'memiliki {n} pemeriksaan QC' in ' '.join(teks.split())
        for i in range(n):assert f'LAB-ASLI-{i+1:03}' in teks
        if n<=5:assert len(pdf.pages)==1
        if len(pdf.pages)>1:
            for page in pdf.pages:assert 'MELEBIHI SATU HALAMAN' in page.extract_text()
        bukti(f'kapasitas-{n:03}-putaran.pdf',r.content)


async def test_banyak_catatan_penerimaan_yang_didukung_skema_beras(pg,contoh):
    async with pg() as db:
        for i in range(8):await catat(db,contoh,'BERAS_MASUK',berat=100+i,suffix=str(i))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf');pdf,teks=isi(r)
        assert len(pdf.pages)==1
        assert 'BERAT BARANG DITERIMA 828,00 kg' in ' '.join(teks.split())
        for i in range(1,9):assert f'BJ #{i}' in teks
        assert 'QC penerimaan jenis barang ini belum tersedia' in teks
        bukti('delapan-catatan-beras.pdf',r.content)
