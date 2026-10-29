"""PDF memakai catatan sah dan QC lengkap; seluruh data hanya database uji."""
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import os

import pytest
import pytest_asyncio
from pypdf import PdfReader
from sqlalchemy import select,text,delete

from app.database import now_local
from app.models import (PkPurchaseQcLog,PkPurchaseBatch,PkPurchaseVerification,
                        PurchaseBatch,PurchaseBatchQc,PurchaseBatchQcSample,User)
from app.services.mutu_pk import penilaian_dari_log
from tests.pg.test_masuk_detail_timbang import contoh,catat,sidik  # noqa: F401
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_portal_pelanggan import portal,client as portal_client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401

pytestmark=pytest.mark.asyncio


def isi(response):
    assert response.status_code==200,response.text[:500] if response.status_code!=200 else ''
    assert response.headers['content-type']=='application/pdf'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert 'no-store' in response.headers['cache-control']
    pdf=PdfReader(BytesIO(response.content))
    assert pdf.metadata.title=='Laporan Penerimaan Barang'
    assert all(abs(float(p.mediabox.width)-595.276)<.1 and abs(float(p.mediabox.height)-841.89)<.1 for p in pdf.pages)
    return pdf,'\n'.join(p.extract_text() for p in pdf.pages)


def bukti(nama,data):
    if folder:=os.environ.get('BUKTI_PDF_PENERIMAAN'):
        p=Path(folder);p.mkdir(parents=True,exist_ok=True);(p/nama).write_bytes(data)


@pytest_asyncio.fixture
async def penerimaan(pg,contoh):
    async with pg() as db:
        b=await catat(db,contoh,'BERAS_PK',berat=14000,status='diterima')
        aid=await db.scalar(text("INSERT INTO timbangan_akun(username,nama,role,password_hash,status) VALUES ('pdf-timbang','Petugas timbang PDF','PETUGAS','uji','aktif') RETURNING id"))
        await db.execute(text("""UPDATE timbangan_transaksi SET status_tiket='SELESAI',
            timbang1_kg=22200,timbang2_kg=8000,timbang2_waktu=NOW(),
            timbang1_petugas_id=:a,timbang2_petugas_id=:a,
            berat_bermuatan_kg=22200,berat_kosong_kg=8000,
            netto_timbangan_kg=14200,total_tara_kg=16,tara_lain_kg=1,
            berat_barang_kg=14184,berat_acuan_kg=14000,selisih_kg=184,
            selisih_persen=1.314,status_kontrol='DALAM_BATAS',nama_sopir='Sopir pengujian PDF'
            WHERE id=:t"""),dict(a=aid,t=contoh['tid']))
        await db.execute(text("""INSERT INTO timbangan_muatan(transaksi_id,urutan,jenis_kode,nomor_acuan,jumlah_karung,tara_per_karung_kg,berat_acuan_kg)
            VALUES(:t,1,'BERAS_PK','ACUAN-UJI-PDF',200,.075,14000)"""),dict(t=contoh['tid']))
        for i in range(5):
            db.add(PkPurchaseQcLog(pk_purchase_batch_id=b.id,kadar_air=12.6+i*.2,
                broken_persen=17+i*2,susut_persen=5+i,
                butir_kuning=['bersih','sedikit','sedang','banyak','parah'][i],
                gabah='bersih',merang='bersih',catatan_lab=f'Catatan asli putaran {i+1}',
                waktu=now_local()-timedelta(minutes=5-i),input_by=contoh['uid']))
        await db.commit()
        return {**contoh,'bid':b.id,'kode':b.kode_batch,'petugas_timbang':aid}


async def test_pdf_endpoint_satu_halaman_lengkap_dan_tidak_menulis(pg,penerimaan):
    x=penerimaan
    async with await _klien(pg,peran='superadmin') as c:
        async with pg() as db:
            awal=await sidik(db)
            nilai=penilaian_dari_log(await db.scalars(select(PkPurchaseQcLog)))
        halaman=await c.get(f'/barang-masuk/{x["tid"]}')
        assert halaman.status_code==200 and f'/barang-masuk/{x["tid"]}/laporan.pdf' in halaman.text
        assert 'Unduh PDF' in halaman.text
        assert 'Bagikan PDF' in halaman.text and 'Lihat PDF' in halaman.text
        assert f'data-penerimaan-share="/barang-masuk/{x["tid"]}/laporan.pdf"' in halaman.text
        bukti('detail-penerimaan.html',halaman.content)
        r=await c.get(f'/barang-masuk/{x["tid"]}/laporan.pdf')
        pdf,teks=isi(r)
        assert len(pdf.pages)==1
        for kata in ('Supplier Uji','Supplier:','14.000,00 kg','14.200,00 kg','14.184,00 kg',
                     '200 karung','0,075 kg/karung','Rata-rata','13,0%','21,0%','7,0%',
                     'Petugas timbang PDF','Penerima Uji','Penyerah/sopir','Penerima','1 / 1',
                     f"{nilai['nilai']:.2f}".replace('.',','),nilai['kelas']):assert kata in teks,kata
        assert teks.count('Supplier Uji')==1
        assert 'Gudang' not in teks and 'Milik pabrik' not in teks and 'harga' not in teks.lower()
        for n in range(1,6):assert f'Catatan asli putaran {n}' in teks
        async with pg() as db:assert await sidik(db)==awal
        bukti('pk-lima-putaran.pdf',r.content)


async def test_pratinjau_inline_tetap_pdf_dan_tidak_menulis(pg,penerimaan):
    async with await _klien(pg,peran='superadmin') as c:
        async with pg() as db:awal=await sidik(db)
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf?unduh=0')
        assert r.status_code==200 and r.headers['content-type']=='application/pdf'
        assert r.headers['content-disposition'].startswith('inline;')
        assert PdfReader(BytesIO(r.content)).metadata.title=='Laporan Penerimaan Barang'
        async with pg() as db:assert await sidik(db)==awal


@pytest.mark.parametrize('kind',['GABAH_BASAH','GABAH_KERING','BERAS_MASUK','BROKEN_MASUK'])
async def test_jenis_lain_gabah_dua_bacaan_dan_tanpa_qc_palsu(pg,contoh,kind):
    async with pg() as db:
        b=await catat(db,contoh,kind,berat=0)
        await db.commit()
        if kind.startswith('GABAH'):
            from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
            for ka in (0,12):
                await catat_qc_gabah(db,user=await db.get(User,contoh['uid']),kode_batch=b.kode_batch,
                    kadar_air_1=ka,kadar_air_2=ka+2,biji_hijau='sedikit',densiti='padat',
                    **(dict(lamur=False,jumlah_sak_lamur=0) if kind=='GABAH_BASAH' else {}))
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf');pdf,teks=isi(r)
        assert '0,00 kg' in teks and 'BELUM FINAL' in teks
        if kind.startswith('GABAH'):
            assert 'KA 1' in teks and 'KA 2' in teks and '7,00%' in teks and '4 pembacaan' in teks
            assert 'Biji hijau' in teks and 'Densiti' in teks
            assert ('Lamur / sak' in teks)==(kind=='GABAH_BASAH')
        else:assert 'QC penerimaan jenis barang ini belum tersedia' in teks and 'Nilai kualitas:' not in teks
        bukti(kind.lower()+'.pdf',r.content)


@pytest.mark.parametrize('role,gudang,lihat,allowed',[
    ('superadmin',None,None,True),('admin',None,None,True),
    ('operator','Gudang 1',None,False),('operator','Gudang 2',None,True),
    ('superadmin',None,'operator:g1',False),('superadmin',None,'operator:g2',True),
])
async def test_url_langsung_tetap_mengikuti_izin_detail(pg,penerimaan,role,gudang,lihat,allowed):
    from tests.pg.formulir import cap_formulir
    async with await _klien(pg,peran=role,gudang=gudang) as c:
        if lihat:
            assert (await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)},follow_redirects=False)).status_code==303
        for suf in ('','/laporan.pdf'):
            assert (await c.get(f'/barang-masuk/{penerimaan["tid"]}'+suf)).status_code==(200 if allowed else 403)


async def test_banyak_putaran_catatan_panjang_pagination_tidak_memotong(pg,penerimaan):
    async with pg() as db:
        for i in range(205):
            db.add(PkPurchaseQcLog(pk_purchase_batch_id=penerimaan['bid'],kadar_air=0 if i==0 else None,
                broken_persen=1,susut_persen=None,merang=None,gabah=None,butir_kuning=None,
                catatan_lab=f'LAB-PANJANG-{i:03} '+('Pengamatan rinci; ' * 11),
                waktu=now_local()+timedelta(seconds=i),input_by=penerimaan['uid'] if i%2 else None))
        await db.commit()
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf?halaman=1&putaran=1')
        pdf,teks=isi(r);assert len(pdf.pages)>2
        for i in range(205):assert f'LAB-PANJANG-{i:03}' in teks
        for n,p in enumerate(pdf.pages,1):
            assert 'Laporan Penerimaan Barang' in p.extract_text()
            assert 'TB-MASUK-UJI' in p.extract_text() and f'{n} / {len(pdf.pages)}' in p.extract_text()
        assert 'Kadar air: 6' in ' '.join(teks.split())  # lima isian sah + nol, bukan 210 isian.
        bukti('pk-banyak-putaran.pdf',r.content)


async def test_satu_putaran_kosong_dan_historis_tanpa_rincian(pg,penerimaan):
    async with pg() as db:
        await db.execute(delete(PkPurchaseQcLog))
        db.add(PkPurchaseQcLog(pk_purchase_batch_id=penerimaan['bid'],kadar_air=0,
            waktu=now_local(),input_by=penerimaan['uid']))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        _,teks=isi(await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf'))
        assert '0,0%' in teks and 'Belum dinilai' in teks
        async with pg() as db:
            await db.execute(delete(PkPurchaseQcLog))
            db.add(PkPurchaseVerification(pk_purchase_batch_id=penerimaan['bid'],kadar_air=14,
                penyusutan_persen=2,butir_kuning='sedikit',catatan_lab='LAB-HISTORIS-UJI'))
            await db.commit()
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf');_,teks=isi(r)
        assert 'LAB-HISTORIS-UJI' in teks and 'rincian putaran' in teks and 'tidak tersedia' in teks
        assert 'jumlah pengukuran asli' in teks.lower()
        bukti('pk-historis.pdf',r.content)


@pytest.mark.parametrize('status,transaksi,alasan',[
    ('TERBUKA','AKTIF',''),('DITUTUP_PAKSA','AKTIF','Kendaraan tidak kembali'),
    ('SELESAI','BATAL','Koreksi tiket operasional'),
])
async def test_status_tiket_belum_final_dan_alasan_tetap_jelas(pg,penerimaan,status,transaksi,alasan):
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET status_tiket=:s,status_transaksi=:t,tutup_paksa_alasan=:a,void_alasan=:a WHERE id=:id'),dict(s=status,t=transaksi,a=alasan,id=penerimaan['tid']))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf');_,teks=isi(r)
        assert 'BELUM FINAL' in teks
        if alasan:assert alasan in teks


async def test_penolakan_tidak_menjadi_bobot_diterima(pg,penerimaan):
    from app.models import PkRejection
    async with pg() as db:
        b=await db.get(PkPurchaseBatch,penerimaan['bid']);b.status_batch='ditolak'
        db.add(PkRejection(kode='REJ-PDF-UJI',pk_purchase_batch_id=b.id,berat_kg=14000,
            alasan='PK ditolak sesuai pemeriksaan nyata',tanggal=now_local().date(),waktu=now_local(),created_by=penerimaan['uid']))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        _,teks=isi(await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf'))
        assert 'DITOLAK' in teks and 'PK ditolak sesuai pemeriksaan nyata' in teks
        assert 'Diterima: Tidak diterima' in teks


async def test_partai_kecil_seluruh_titik_dan_bukan_bruto_tara_palsu(pg,contoh):
    async with pg() as db:
        await catat(db,contoh,'GABAH_KERING',berat=600)
        await db.execute(text('CREATE TABLE timbangan_penimbangan (id SERIAL PRIMARY KEY,transaksi_id INTEGER,urutan INTEGER,berat_kg NUMERIC(12,2),waktu TIMESTAMPTZ,catatan TEXT,petugas_id INTEGER)'))
        await db.execute(text("UPDATE timbangan_transaksi SET cara_timbang='PARTAI',status_tiket='SELESAI',netto_timbangan_kg=600,berat_barang_kg=600 WHERE id=:i"),dict(i=contoh['tid']))
        for n in range(1,4):
            await db.execute(text('INSERT INTO timbangan_penimbangan(transaksi_id,urutan,berat_kg,waktu,catatan) VALUES(:t,:n,:b,NOW(),:c)'),dict(t=contoh['tid'],n=n,b=n*100,c=f'CATATAN-PARTAI-{n}'))
        await db.commit()
    try:
        async with await _klien(pg,peran='admin') as c:
            r=await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf');_,teks=isi(r)
            assert 'Partai kecil' in teks and '600,00 kg' in teks
            assert 'Bruto kendaraan' not in teks and 'Tara kendaraan' not in teks
            for n in range(1,4):assert f'CATATAN-PARTAI-{n}' in teks
            bukti('partai-kecil.pdf',r.content)
    finally:
        async with pg() as db:
            await db.execute(text('DROP TABLE timbangan_penimbangan'));await db.commit()


async def test_bobot_diterima_bukan_saldo_dan_tara_tidak_dibaca_dari_master_baru(pg,penerimaan):
    async with await _klien(pg,peran='admin') as c:
        _,awal=isi(await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf'))
        async with pg() as db:
            b=await db.get(PkPurchaseBatch,penerimaan['bid']);b.status_batch='disosoh'
            await db.execute(text("UPDATE timbangan_jenis SET tara_bawaan_kg=88 WHERE kode='BERAS_PK'"))
            await db.commit()
        _,akhir=isi(await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf'))
        for teks in (awal,akhir):
            assert 'Diterima: 14.000,00 kg' in teks and '0,075 kg/karung' in teks
            assert '14.184,00 kg' in teks and '88,00 kg' not in teks


async def test_penerimaan_terpecah(pg,contoh):
    async with pg() as db:
        await catat(db,contoh,'BERAS_MASUK',berat=100,suffix='A')
        b=await catat(db,contoh,'BERAS_MASUK',berat=50.25,suffix='B')
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        _,teks=isi(await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf'))
        assert '150,25 kg' in teks and 'BJ #1' in teks and 'BJ #2' in teks


async def test_nilai_belum_diketahui_tidak_dianggap_nol(pg,contoh):
    async with pg() as db:
        await catat(db,contoh,'GABAH_BASAH',berat=None,sumber='menunggu')
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        _,teks=isi(await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf'))
        assert 'Diterima: Belum diukur' in teks and 'Belum tercatat' in teks
        assert 'Diterima: 0,00 kg' not in teks


async def test_portal_unduh_sendiri_url_asing_ditolak_dan_tidak_ada_perubahan(pg,portal):
    from tests.pg.test_tiket_antrean_produksi import _tiket
    async with pg() as db:
        tids=[]
        for i in range(2):
            tid=await _tiket(db,'TB-PDF-PORTAL-'+str(i),'GABAH_KERING',pihak=portal.owners[i].nama_pelanggan)
            await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,jasa_id=:j WHERE id=:t'),dict(p=portal.owners[i].id,j=portal.orders[i].id,t=tid))
            db.add(PurchaseBatch(kode_batch='GB-PDF-PORTAL-'+str(i),jasa_id=portal.orders[i].id,
                berat_total_kg=1000,kondisi_gabah='kering',tanggal_pembelian=now_local().date(),
                waktu_pembelian=now_local(),input_by=1,status_batch='baru',sumber_berat='timbangan',timbangan_transaksi_id=tid))
            tids.append(tid)
        await db.commit()
    async with portal_client(portal.accounts[0]) as c:
        async with pg() as db:awal=await sidik(db)
        page=await c.get(f'/pelanggan/barang-masuk/{tids[0]}')
        assert f'/pelanggan/barang-masuk/{tids[0]}/laporan.pdf' in page.text
        assert f'data-penerimaan-share="/pelanggan/barang-masuk/{tids[0]}/laporan.pdf"' in page.text
        assert '/static/pdf-penerimaan.js?' in page.text
        pdf,teks=isi(await c.get(f'/pelanggan/barang-masuk/{tids[0]}/laporan.pdf'))
        assert 'Pelanggan/pemilik:' in teks and portal.owners[0].nama_pelanggan in teks
        assert portal.owners[1].nama_pelanggan not in teks
        assert (await c.get(f'/pelanggan/barang-masuk/{tids[1]}/laporan.pdf')).status_code==404
        assert (await c.get(f'/pelanggan/barang-masuk/{tids[0]}/laporan.pdf?pelanggan_id={portal.owners[1].id}')).status_code==404
        inline=await c.get(f'/pelanggan/barang-masuk/{tids[0]}/laporan.pdf?unduh=0')
        assert inline.status_code==200 and inline.headers['content-disposition'].startswith('inline;')
        assert (await c.get(f'/pelanggan/barang-masuk/{tids[1]}/laporan.pdf?unduh=0')).status_code==404
        async with pg() as db:assert await sidik(db)==awal


async def test_unduh_tanpa_sesi_dan_id_tidak_sah(pg,penerimaan):
    from httpx import AsyncClient,ASGITransport
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as c:
        assert (await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf')).status_code==303
        assert (await c.get(f'/pelanggan/barang-masuk/{penerimaan["tid"]}/laporan.pdf')).status_code==401
    async with await _klien(pg,peran='admin') as c:
        assert (await c.get('/barang-masuk/999999/laporan.pdf')).status_code==404


async def test_portal_tidak_menerbitkan_dokumen_seluruh_tiket_berpemilik_campuran(pg,portal):
    from tests.pg.test_tiket_antrean_produksi import _tiket
    async with pg() as db:
        tid=await _tiket(db,'TB-PDF-CAMPUR','BERAS_MASUK',pihak=portal.owners[0].nama_pelanggan)
        await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,jasa_id=:j WHERE id=:t'),
            dict(p=portal.owners[0].id,j=portal.orders[0].id,t=tid))
        for i in range(2):
            b=await catat(db,dict(tid=tid,uid=1),'BERAS_MASUK',berat=100+i,suffix=str(i))
            b.jasa_id=portal.orders[i].id
        await db.commit()
    async with portal_client(portal.accounts[0]) as c:
        async with pg() as db:awal=await sidik(db)
        r=await c.get(f'/pelanggan/barang-masuk/{tid}/laporan.pdf')
        assert r.status_code==404
        assert portal.owners[1].nama_pelanggan not in r.text
        async with pg() as db:assert await sidik(db)==awal


async def test_belum_diterima_tidak_dianggap_ditolak(pg,contoh):
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf');_,teks=isi(r)
        assert 'BELUM FINAL' in teks and 'Diterima: Belum diterima' in teks
        assert 'Belum ada batch penerimaan' in teks and 'DITOLAK' not in teks


async def test_gabah_historis_mempertahankan_parameter_asli(pg,contoh):
    async with pg() as db:
        b=await catat(db,contoh,'GABAH_KERING',berat=100)
        b.kadar_air_awal_persen=14.25
        db.add(PurchaseBatchQc(purchase_batch_id=b.id,biji_hijau='banyak',densiti='empuk',input_by=contoh['uid']))
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r=await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf');_,teks=isi(r)
        for kata in ('Kadar air awal','14,25%','banyak','empuk','Rincian pengukuran asli tidak tersedia'):assert kata in teks
        assert 'KA 1' not in teks and 'KA 2' not in teks
        bukti('gabah-historis.pdf',r.content)


async def test_identitas_setiap_pemilik_jelas_tanpa_pengulangan(pg,contoh):
    from app.models import Pelanggan,Jasa
    async with pg() as db:
        for i in range(2):
            pel=Pelanggan(nama_pelanggan=f'Pemilik dokumen {i}')
            db.add(pel);await db.flush()
            jasa=Jasa(kode=f'JAS-DOK-{i}',pelanggan_id=pel.id)
            db.add(jasa);await db.flush()
            b=await catat(db,contoh,'BERAS_MASUK',berat=100+i,suffix=str(i));b.jasa_id=jasa.id
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        _,teks=isi(await c.get(f'/barang-masuk/{contoh["tid"]}/laporan.pdf'))
        for i in range(2):
            assert teks.count(f'Pemilik dokumen {i}')==1
            assert f'JAS-DOK-{i}' in teks
        assert '201,00 kg' in teks


async def test_nama_panjang_dan_catatan_diperlakukan_sebagai_teks(pg,penerimaan):
    from app.models import Supplier
    async with pg() as db:
        supplier=await db.get(Supplier,penerimaan['sid']);supplier.nama_supplier='Nama supplier panjang dengan beberapa cabang dan alamat korespondensi <uji> & asli'
        log=await db.scalar(select(PkPurchaseQcLog).order_by(PkPurchaseQcLog.id))
        log.catatan_lab='Isi <b>asli & utuh</b> '+('Pemeriksaan panjang. '*10)
        await db.commit()
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf');_,teks=isi(r)
        flat=' '.join(teks.split())
        assert '<b>asli & utuh</b>' in flat and '<uji> & asli' in flat
        bukti('nama-dan-catatan-panjang.pdf',r.content)


async def test_kapasitas_desain_dua_batch_lima_putaran_di_penyaji(pg,penerimaan):
    # Uji kapasitas layout saja. Skema lama PK tetap satu batch aktif per
    # tiket, tidak diubah demi data contoh desain dua batch.
    from copy import deepcopy
    from app.services import barang_masuk
    from app.services.laporan_penerimaan import baca
    from app.web.pdf_penerimaan import buat_pdf
    async with pg() as db:
        rows=await barang_masuk.riwayat(db,g1=True,g2=True,tid=penerimaan['tid'])
        t=await barang_masuk.tiket_riwayat(db,penerimaan['tid'])
        d=await baca(db,t,'pk',rows[0]['catatan'],pembuat='Pembuat uji layout')
    kedua=deepcopy(d['catatan'][0]);kedua['kode']='BATCH-LAYOUT-KEDUA';kedua['berat']=100
    d['catatan'].append(kedua)
    d['berat']=14100  # Nilai fixture layout, bukan perhitungan layanan baru.
    d['qc'].append(dict(kode=kedua['kode'],jenis='pk',status='Belum diperiksa',putaran=[],rata=None))
    data=buat_pdf(d);pdf=PdfReader(BytesIO(data))
    assert len(pdf.pages)==1
    teks=pdf.pages[0].extract_text();assert 'BATCH-LAYOUT-KEDUA' in teks and 'Belum diperiksa' in teks
    bukti('uji-layout-dua-batch.pdf',data)
