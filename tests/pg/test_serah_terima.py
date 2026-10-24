"""Serah terima memakai QC/pengeluaran sah dan scope pelanggan di server."""
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text
from app.database import now_local
from app.models import (User,PurchaseBatch,PkPurchaseBatch,OutgoingRecord,OutgoingItem,
                        ProductSku,Brand,PackageSize,PackagingMaterial,RiceQualityStandard)
from tests.pg.test_portal_pelanggan import portal,client,qc
from tests.pg.test_jasa_ketaatan import _tiket
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def handover(pg,portal):
    async with pg() as db:
        u=User(nama='Petugas Serah Terima',role='admin',status='aktif');db.add(u);await db.flush()
        tids=[];batches=[]
        for i,(p,j) in enumerate(zip(portal.owners,portal.orders)):
            tid=await _tiket(db,kode='T-ST-'+str(i),berat=5000,pelanggan_id=p.id,jasa_id=j.id,jenis='GABAH_BASAH')
            batch=PurchaseBatch(kode_batch='GB-ST-'+str(i),jasa_id=j.id,berat_total_kg=5000,
                kondisi_gabah='basah',tanggal_pembelian=date.today(),waktu_pembelian=now_local(),
                input_by=u.id,status_batch='baru',sumber_berat='timbangan',timbangan_transaksi_id=tid)
            db.add(batch);await db.flush();tids.append(tid);batches.append(batch.id)
        pk_tid=await _tiket(db,kode='T-ST-PK',berat=5000,pelanggan_id=portal.owners[0].id,jasa_id=portal.orders[0].id,jenis='BERAS_PK')
        pk=PkPurchaseBatch(kode_batch='PK-ST-A',jasa_id=portal.orders[0].id,berat_total_kg=5000,
            tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=u.id,status_batch='diterima',sumber_berat='timbangan',timbangan_transaksi_id=pk_tid)
        db.add(pk)
        material=await db.scalar(select(PackagingMaterial).order_by(PackagingMaterial.id));size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==25))
        brand=Brand(nama='Merek Pelanggan ST',aktif=True);db.add(brand);await db.flush()
        sku=ProductSku(kategori='beras_putih',brand_id=brand.id,packaging_material_id=material.id,package_size_id=size.id);db.add(sku);await db.flush()
        quality=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.kode=='medium'))
        outs=[]
        for i,j in enumerate(portal.orders):
            keluar_tid=await _tiket(db,kode='T-ST-OUT-'+str(i),berat=1000,pelanggan_id=portal.owners[i].id,jasa_id=j.id,jenis='BERAS_PK',nopol='AD ST '+str(i))
            await db.execute(sql_text("UPDATE timbangan_transaksi SET arah='KELUAR',nama_sopir='Sopir Contoh',timbang1_kg=5000,timbang2_kg=6020,timbang2_waktu=:at,netto_timbangan_kg=1020,total_tara_kg=20,berat_barang_kg=1000 WHERE id=:id"),{'at':now_local(),'id':keluar_tid})
            r=OutgoingRecord(kode='OUT-ST-'+str(i),tanggal=date.today(),waktu=now_local(),input_by=u.id,
                nama_pembeli=portal.owners[i].nama_pelanggan,pelanggan_id=portal.owners[i].id,jasa_id=j.id,
                status='dimuat',no_polisi='AD ST '+str(i),timbangan_transaksi_id=keluar_tid,dimuat_oleh=u.id,waktu_muat=now_local())
            db.add(r);await db.flush();outs.append(r.id)
            db.add(OutgoingItem(outgoing_record_id=r.id,item_type='finished_goods',product_sku_id=sku.id,rice_quality_standard_id=quality.id,
                jasa_id=j.id,jumlah_karung_perintah=100,berat_perintah_kg=5000,jumlah_karung=40,berat_kg=1000))
        await db.commit()
        return SimpleNamespace(portal=portal,user=u.id,tids=tids,batches=batches,pk_tid=pk_tid,outs=outs)


async def catat(pg,h,n=5):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    async with pg() as db:
        u=await db.get(User,h.user)
        for _ in range(n):
            batch=await db.get(PurchaseBatch,h.batches[0])
            wet=batch.kondisi_gabah=='basah'
            await catat_qc_gabah(db,user=u,kode_batch='GB-ST-0',kadar_air_1=24,kadar_air_2=25,
                biji_hijau='sedikit',densiti='padat',lamur=False if wet else None,jumlah_sak_lamur=0 if wet else None)


def pdf_text(r):
    assert r.status_code==200,r.text[:200] if r.status_code!=200 else ''
    reader=PdfReader(BytesIO(r.content))
    return '\n'.join(p.extract_text() for p in reader.pages),reader.metadata.title


@pytest.mark.parametrize('kondisi',['basah','kering'])
async def test_penerimaan_tidak_ada_pdf_sebelum_qc_lengkap_lalu_layar_pdf_sama(pg,handover,kondisi):
    h=handover;path=f'/pelanggan/barang-masuk/{h.tids[0]}/serah-terima'
    if kondisi=='kering':
        async with pg() as db:
            b=await db.get(PurchaseBatch,h.batches[0]);b.kondisi_gabah='kering'
            await db.execute(sql_text("UPDATE timbangan_transaksi SET jenis_kode='GABAH_KERING' WHERE id=:id"),{'id':h.tids[0]});await db.commit()
    async with client(h.portal.accounts[0]) as c:
        assert (await c.get(path+'.pdf')).status_code==409
        await catat(pg,h,4)
        assert (await c.get(path+'.pdf')).status_code==409
        await catat(pg,h,1)
        r=await c.get(path);assert r.status_code==200
        soup=BeautifulSoup(r.text,'html.parser');assert soup.find('h1').get_text()=='Serah Terima Penerimaan'
        pdf=await c.get(path+'.pdf');text,title=pdf_text(pdf)
        assert 'Serah Terima Penerimaan' in title and 'STP-T-ST-0' in title
        for value in ['GB-ST-0','5.000 kg','24%','25%','Petugas Serah Terima','5/5 pemeriksaan','Pengesahan serah terima']:
            assert value in text and value in soup.get_text(' ',strip=True),value
        assert text.count('Pemeriksaan ')==5
        assert 'Rahasia Pelanggan B' not in text
        assert (await c.get(path+'.pdf?unduh=1')).headers['content-disposition'].startswith('attachment;')
        report=await c.get('/pelanggan/laporan');assert 'STP-T-ST-0' in report.text
        out=Path('output/serah-terima');out.mkdir(parents=True,exist_ok=True);(out/'penerimaan.pdf').write_bytes(pdf.content)
    async with await _klien(pg,peran='admin') as c:
        assert pdf_text(await c.get(path.removeprefix('/pelanggan')+'.pdf'))[0]==text


async def test_tutup_qc_lebih_awal_memakai_alur_resmi(pg,handover):
    from app.penggilingan.gudang1.services.qc_gabah import tutup_qc_gabah
    h=handover;await catat(pg,h,2)
    async with pg() as db:
        u=await db.get(User,h.user)
        await tutup_qc_gabah(db,user=u,kode_batch='GB-ST-0',alasan='Muatan sudah habis dibongkar')
    async with client(h.portal.accounts[0]) as c:
        text,_=pdf_text(await c.get(f'/pelanggan/barang-masuk/{h.tids[0]}/serah-terima.pdf'))
        assert 'Ditutup' in text and '2/5 pemeriksaan' in text
        assert 'Muatan sudah habis dibongkar' in text
        assert '5/5 pemeriksaan' not in text


async def test_pk_menunggu_enam_komponen_qc(pg,handover):
    from app.penggilingan.gudang2.service import log_pk_qc
    h=handover;path=f'/pelanggan/barang-masuk/{h.pk_tid}/serah-terima.pdf'
    async with pg() as db:
        u=await db.get(User,h.user)
        await log_pk_qc(db,user=u,kode='PK-ST-A',kadar_air=14,broken=15,butir_kuning='bersih',gabah='sedikit',merang='bersih')
    async with client(h.portal.accounts[0]) as c:assert (await c.get(path)).status_code==409
    async with pg() as db:
        u=await db.get(User,h.user)
        await log_pk_qc(db,user=u,kode='PK-ST-A',kadar_air=14,broken=15,penyusutan_persen=12,butir_kuning='bersih',gabah='sedikit',merang='bersih')
    async with client(h.portal.accounts[0]) as c:
        text,_=pdf_text(await c.get(path));assert 'PK-ST-A' in text and 'Susut uji' in text and '12%' in text


async def test_pengeluaran_setelah_verifikasi_memakai_aktual_merek_kemasan_bukan_perintah(pg,handover):
    h=handover;path=f'/pelanggan/barang-keluar/{h.outs[0]}/serah-terima'
    async with client(h.portal.accounts[0]) as c:
        assert (await c.get(path+'.pdf')).status_code==409
        async with pg() as db:
            from app.services.barang_keluar import verifikasi
            u=await db.get(User,h.user);r=await db.get(OutgoingRecord,h.outs[0])
            await verifikasi(db,user=u,rec_id=r.id,timbangan_transaksi_id=r.timbangan_transaksi_id)
        r=await c.get(path);assert r.status_code==200
        pdf=await c.get(path+'.pdf');text,title=pdf_text(pdf)
        assert 'Serah Terima Pengeluaran' in title
        for v in ['OUT-ST-0','STK-OUT-ST-0','Merek Pelanggan ST','1.000 kg','40','Petugas Serah Terima']:
            assert v in text and v in BeautifulSoup(r.text,'html.parser').get_text(' ',strip=True)
        assert '5.000 kg' not in text and '100' not in text
        out=Path('output/serah-terima');out.mkdir(parents=True,exist_ok=True);(out/'pengeluaran.pdf').write_bytes(pdf.content)
        async with pg() as db:
            r=await db.get(OutgoingRecord,h.outs[0]);r.status='batal';await db.commit()
        assert (await c.get(path+'.pdf')).status_code==409
        assert 'STK-OUT-ST-0' not in (await c.get('/pelanggan/serah-terima')).text


async def test_scope_tiket_pdf_dan_pengeluaran_lintas_pelanggan_ditolak(pg,handover):
    h=handover
    async with client(h.portal.accounts[0]) as c:
        for kind,ident in [('barang-masuk',h.tids[1]),('barang-keluar',h.outs[1])]:
            for suffix in ['', '.pdf']:
                assert (await c.get(f'/pelanggan/{kind}/{ident}/serah-terima'+suffix)).status_code==404
        assert (await c.get(f'/pelanggan/barang-masuk/{h.tids[0]}/serah-terima?pelanggan_id={h.portal.owners[1].id}')).status_code==404
        assert (await c.get('/serah-terima')).status_code==303
        # Header tiket milik A tidak mengesahkan batch milik B.
        async with pg() as db:
            b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PK-ST-A'));b.jasa_id=h.portal.orders[1].id;b.timbangan_transaksi_id=h.tids[0];await db.commit()
        assert (await c.get(f'/pelanggan/barang-masuk/{h.tids[0]}/serah-terima')).status_code==404
    async with client() as c:
        assert (await c.get('/pelanggan/serah-terima')).status_code==401
    async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
        assert (await c.get(f'/barang-keluar/{h.outs[0]}/serah-terima')).status_code==403


async def test_kedua_dokumen_di_laporan_bersama_dan_seluruh_get_tidak_menulis(pg,handover):
    from app.models import (ProduksiAkun,Jasa,FinishedGoodsStock,ByproductStock,
                            PurchaseBatchQc,PurchaseBatchQcSample,ActivityLog)
    from app.web import security
    from app.models.portal import PortalAccount
    h=handover;await catat(pg,h,5)
    async with pg() as db:
        from app.services.barang_keluar import verifikasi
        u=await db.get(User,h.user);r=await db.get(OutgoingRecord,h.outs[0])
        await verifikasi(db,user=u,rec_id=r.id,timbangan_transaksi_id=r.timbangan_transaksi_id)
        account=ProduksiAkun(user_id=h.user,username='serah-admin-uji',password_hash=security.hash_sandi('rahasia123'),status='aktif',mode_perangkat='pribadi')
        db.add(account);await db.commit()
    models=[Jasa,PurchaseBatch,PkPurchaseBatch,OutgoingRecord,OutgoingItem,FinishedGoodsStock,ByproductStock,PurchaseBatchQc,PurchaseBatchQcSample,ActivityLog,PortalAccount]
    async def snapshot():
        async with pg() as db:
            return {m.__tablename__:[tuple(r) for r in (await db.execute(select(*m.__table__.columns).order_by(m.id))).all()] for m in models}
    before=await snapshot()
    async with client(h.portal.accounts[0]) as c:
        for p in ['/pelanggan/serah-terima','/pelanggan/laporan']:
            r=await c.get(p);assert r.status_code==200
            assert 'STP-T-ST-0' in r.text and 'STK-OUT-ST-0' in r.text
            assert 'T-ST-1' not in r.text and 'OUT-ST-1' not in r.text
        for kind,ident in [('barang-masuk',h.tids[0]),('barang-keluar',h.outs[0])]:
            path=f'/{kind}/{ident}/serah-terima'
            portal_page=await c.get('/pelanggan'+path)
            assert not BeautifulSoup(portal_page.text,'html.parser').select('.rekap-jasa button,.rekap-jasa form')
            pdf=await c.get('/pelanggan'+path+'.pdf');text_pdf,_=pdf_text(pdf)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=__import__('app.main',fromlist=['app']).app),base_url='http://uji') as staff:
                staff.cookies.set(security.NAMA_COOKIE,security.buat_token(account))
                native=await staff.get(path);assert native.status_code==200
                assert BeautifulSoup(native.text,'html.parser').select_one('.rekap-jasa').get_text(' ',strip=True)==BeautifulSoup(portal_page.text,'html.parser').select_one('.rekap-jasa').get_text(' ',strip=True)
                assert pdf_text(await staff.get(path+'.pdf'))[0]==text_pdf
    assert await snapshot()==before
    import json
    out=Path('output/serah-terima');out.mkdir(parents=True,exist_ok=True)
    (out/'browser-fixture.json').write_text(json.dumps({'penerimaan':h.tids[0],'pengeluaran':h.outs[0]}))


async def test_nomor_dokumen_dan_pesanan_asal_tetap_saat_digabung(pg,handover):
    from app.models import Jasa
    from app.services.jasa import gabung_jasa
    h=handover;await catat(pg,h,5)
    async with pg() as db:
        j=Jasa(kode='JAS-ST-GABUNG',pelanggan_id=h.portal.owners[0].id,status='berjalan')
        db.add(j);await db.flush()
        u=await db.get(User,h.user)
        await gabung_jasa(db,user=u,dari_id=h.portal.orders[0].id,ke_id=j.id)
        await db.commit()
    async with client(h.portal.accounts[0]) as c:
        text,_=pdf_text(await c.get(f'/pelanggan/barang-masuk/{h.tids[0]}/serah-terima.pdf'))
        assert 'STP-T-ST-0' in text
        assert 'JAS-ST-GABUNG' in text and h.portal.orders[0].kode in text
        # Label dapat membungkus baris di kolom PDF yang sempit.
        normalized=' '.join(text.split())
        assert 'Pesanan pada tiket' in normalized and 'Pesanan barang saat ini' in normalized


async def test_identitas_pelanggan_pada_tiket_keluar_tetap_diperiksa(pg,handover):
    h=handover
    async with pg() as db:
        rec=await db.get(OutgoingRecord,h.outs[0]);tid=rec.timbangan_transaksi_id
        await db.execute(sql_text('UPDATE timbangan_transaksi SET pelanggan_id=:pid WHERE id=:tid'),{'pid':h.portal.owners[1].id,'tid':tid});await db.commit()
    async with client(h.portal.accounts[0]) as c:
        assert (await c.get(f'/pelanggan/barang-keluar/{h.outs[0]}/serah-terima')).status_code==404
        assert (await c.get(f'/pelanggan/barang-keluar/{h.outs[0]}/serah-terima.pdf')).status_code==404
    # Tiket lama tanpa ID kontak tetap diikat oleh seluruh item milik akun.
    async with pg() as db:
        await db.execute(sql_text('UPDATE timbangan_transaksi SET pelanggan_id=NULL WHERE id=:tid'),{'tid':tid});await db.commit()
    async with client(h.portal.accounts[0]) as c:
        assert (await c.get(f'/pelanggan/barang-keluar/{h.outs[0]}/serah-terima')).status_code==200
