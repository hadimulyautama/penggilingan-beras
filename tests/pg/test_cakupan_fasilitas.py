from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.models import (Warehouse,User,Dryer,LiniProduksi,JenisProsesProduksi,
    PurchaseBatch,ByproductStock,DryingLot,Silo,SiloStorage)
from app.database import now_local
from app.services.cakupan_fasilitas import batas,lokasi
from tests.pg.test_fasilitas import dunia
from tests.pg.test_tiket_antrean_produksi import _tiket,_klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

async def dryer_g2(pg,u,wh):
    async with pg() as db:
        jid=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode=='pengeringan'))
        d=Dryer(nama='Dryer G2 khusus uji',warehouse_id=wh.id,kapasitas_kg=30000,status='aktif');db.add(d);await db.flush()
        l=LiniProduksi(kode='dryer-g2-uji',nama=d.nama,warehouse_id=wh.id,jenis_proses_id=jid,dryer_id=d.id,aktif=True,versi=1);db.add(l);await db.commit();return d.id

@pytest.mark.parametrize('kind',['GABAH_BASAH','GABAH_KERING'])
async def test_pilihan_gudang_penerima_dan_cakupan_detail_pdf(pg,kind):
    u,wh,ops=await dunia(pg);did=await dryer_g2(pg,u,wh[1])
    async with pg() as db:
        tid=await _tiket(db,'TB-GUDANG-G2',kind);await db.commit()
    async with await _klien(pg,role='admin') as c:
        from pathlib import Path
        page=await c.get(f'/barang-masuk/{tid}')
        ctx=await c.get(f'/api/actions/penerimaan-ringkas/{tid}')
        assert page.status_code==ctx.status_code==200
        Path('../penerimaan-pilihan-gudang.html').write_text(page.text)
        Path('../penerimaan-pilihan-gudang.json').write_text(ctx.text)
    async with await _klien(pg,role='operator',gudang_id=wh[1].id) as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.get(f'/api/actions/penerimaan-ringkas/{tid}');assert r.status_code==200,r.text
        data=r.json();assert data['pending'] and data['gudang_penerima']==[{'value':wh[1].id,'label':wh[1].nama_gudang}]
        form=next(a for a in data['formulir'] if a['id']=='gabah_masuk');assert form['boleh']
        assert any(f['name']=='warehouse_id' and f['label']=='Gudang penerima' for f in form['fields'])
        assert any(t['warehouse_id']==wh[1].id and 'dryer' in t['value'] for t in data['tujuan'])
        wrong=await c.post('/api/actions/gabah-masuk',json={'timbangan_transaksi_id':tid,'warehouse_id':wh[0].id,'tujuan':f'dryer:{did}'})
        assert wrong.status_code==403,wrong.text
        r=await c.post('/api/actions/gabah-masuk',json={'timbangan_transaksi_id':tid,'warehouse_id':wh[1].id,'tujuan':f'dryer:{did}'})
        assert r.status_code==200,r.text
        r=await c.get(f'/barang-masuk/{tid}');assert r.status_code==200,r.text
        r=await c.get(f'/barang-masuk/{tid}/laporan.pdf');assert r.status_code==200,r.text[:500];assert r.content.startswith(b'%PDF')
    async with pg() as db:
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.timbangan_transaksi_id==tid));assert batch.warehouse_id==wh[1].id
        before=(batch.berat_total_kg,batch.status_batch,batch.dryer_id)
    async with await _klien(pg,role='operator',gudang_id=wh[0].id) as c:
        for path in (f'/barang-masuk/{tid}',f'/barang-masuk/{tid}/laporan.pdf'):
            r=await c.get(path);assert r.status_code==403,(path,r.text[:300])
        r=await c.get('/barang-masuk?status=diterima&cari=TB-GUDANG-G2');assert '0 hasil' in r.text
    async with pg() as db:
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.timbangan_transaksi_id==tid));assert (batch.berat_total_kg,batch.status_batch,batch.dryer_id)==before
        from app.services import barang_masuk_daftar as daftar
        d=await daftar.daftar(db,g1=True,g2=True,admin=False,status='diterima',cari='TB-GUDANG-G2',user=ops[1]);assert d['jumlah']==1

async def test_stok_satu_jenis_dan_pemilik_tidak_bercampur_gudang(pg):
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        for w,kg in zip(wh,(110,220)):
            db.add(ByproductStock(warehouse_id=w.id,jenis_produk='broken',source_type='manual',berat_kg=kg,tanggal=now_local().date(),waktu=now_local(),input_by=u.id))
        await db.commit()
        from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah
        assert await hitung_stok_broken_curah(db)==330
        assert await hitung_stok_broken_curah(db,user=ops[0])==110
        assert await hitung_stok_broken_curah(db,user=ops[1])==220
        from app.services.stok import stok_produk
        a=next(x for x in await stok_produk(db,user=ops[0]) if x.jenis=='broken')
        b=next(x for x in await stok_produk(db,user=ops[1]) if x.jenis=='broken')
        assert a.sisa_kg==110 and b.sisa_kg==220
        assert await db.scalar(select(func.sum(ByproductStock.berat_kg)))==330

async def test_picker_tujuan_menolak_gudang_lain(pg):
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        tid=await _tiket(db,'TB-PILIH-GUDANG','GABAH_KERING');await db.commit()
    async with await _klien(pg,role='operator',gudang_id=wh[0].id) as c:
        r=await c.get('/api/actions/tujuan-gabah',params={'induk':tid,'warehouse_id':wh[1].id})
        assert r.status_code==400,r.text
        r=await c.get('/api/actions/tujuan-gabah',params={'induk':tid,'warehouse_id':wh[0].id})
        assert r.status_code==200,r.text

async def test_filter_gudang_stok_admin_tidak_mengubah_peran(pg):
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        for w,kg in zip(wh,(110,220)):
            db.add(ByproductStock(warehouse_id=w.id,jenis_produk='broken',source_type='manual',berat_kg=kg,tanggal=now_local().date(),waktu=now_local(),input_by=u.id))
        await db.commit()
        from app.services.cakupan_fasilitas import konteks_baca_gudang
        from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah
        for w,kg in zip(wh,(110,220)):
            actor=await konteks_baca_gudang(db,u,w.kode_fungsi)
            assert actor.role==u.role and actor.default_warehouse_id==u.default_warehouse_id
            assert await hitung_stok_broken_curah(db,user=actor)==kg
        actor=await konteks_baca_gudang(db,ops[0],wh[1].kode_fungsi)
        assert await hitung_stok_broken_curah(db,user=actor)==0
        assert await hitung_stok_broken_curah(db)==330

@pytest.mark.fondasi_multi
async def test_line_giling_g2_saldo_riwayat_detail_pdf_dan_batas_operator(pg):
    from app.models import MillingProcess,Supplier,MillingProgressLog
    from app.penggilingan.gudang1.services import milling as m
    from app.services.fasilitas import simpan_lini
    from app.services import stok
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        jid=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode=='penggilingan'))
        line=await simpan_lini(db,user=u,kode='giling-g2-uji',nama='Line penggilingan G2 uji',warehouse_id=wh[1].id,jenis_proses_id=jid)
        silo=Silo(nama_silo='Silo Gabah Uji G2',warehouse_id=wh[1].id,jenis_isi='gabah',status='terisi',aktif=True);db.add(silo)
        sup=Supplier(nama_supplier='Supplier uji lokasi');db.add(sup);await db.flush()
        batch=PurchaseBatch(kode_batch='GB-UJI-G2-GILING',warehouse_id=wh[1].id,supplier_id=sup.id,tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),kondisi_gabah='kering',berat_total_kg=10000,sumber_berat='timbangan',status_batch='di_silo',input_by=u.id)
        db.add(batch);await db.flush()
        db.add(SiloStorage(silo_id=silo.id,purchase_batch_id=batch.id,tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=u.id,status='terisi'))
        await db.commit()
        old_silo=await db.scalar(select(Silo.id).where(Silo.warehouse_id==wh[0].id).order_by(Silo.id))
        db.add(MillingProcess(kode_proses='LEGACY-AKTIF-G1',status='proses',silo_id=old_silo,waktu_mulai=now_local(),created_by=u.id))
        await db.commit()
        pr=(await m.start_milling(db,user=ops[1],nama_silo=[silo.nama_silo],lini_id=line.id)).proc
        await m.log_progress(db,user=ops[1],kode_proses=pr.kode_proses,berat_kumulatif=6500)
        kode=pr.kode_proses
        found=next(x for x in await stok.pk_gudang1(db,user=ops[1]) if x.kode==kode)
        assert found.tersedia==6500 and found.warehouse_id==wh[1].id and found.gudang_nama==wh[1].nama_gudang
        assert kode not in [x.kode for x in await stok.pk_gudang1(db,user=ops[0])]
    async with await _klien(pg,role='operator',gudang_id=wh[1].id) as c:
        r=await c.get('/api/actions/giling-ringkas/'+kode);assert r.status_code==200,r.text
        r=await c.get('/proses-aktif/giling/'+kode);assert r.status_code==200,r.text
    async with await _klien(pg,role='operator',gudang_id=wh[0].id) as c:
        r=await c.get('/api/actions/giling-ringkas/'+kode);assert r.status_code==403,r.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(MillingProgressLog))==1

    async with pg() as db:
        await m.tutup_silo_giling(db,user=ops[1],kode_proses=kode,nama_silo='Silo Gabah Uji G2',sisa_kg=0)
        await m.finish_milling(db,user=ops[1],kode_proses=kode)
        from app.penggilingan.gudang1.services.milling import riwayat_giling
        own,_=await riwayat_giling(db,user=ops[1]);other,_=await riwayat_giling(db,user=ops[0])
        assert kode in [r.kode for r in own] and kode not in [r.kode for r in other]
    from tests.pg.test_riwayat_giling import _klien as browser_client
    from app.web.lihat_sebagai import NAMA_KUKI
    for view,expected in [('operator:g2',200),('operator:g1',403)]:
        async with await browser_client(pg,peran='superadmin') as c:
            c.cookies.set(NAMA_KUKI,view)
            for path in (f'/riwayat-giling/{pr.id}',f'/riwayat-giling/{pr.id}/laporan.pdf'):
                r=await c.get(path);assert r.status_code==expected,(path,r.text[:300])
                if expected==200 and path.endswith('.pdf'):
                    from pathlib import Path
                    assert r.content.startswith(b'%PDF')
                    Path('../laporan-giling-g2-uji.pdf').write_bytes(r.content)

@pytest.mark.parametrize('jenis,model,endpoint,fields',[
 ('BERAS_PK','pk','catat-pk-luar',{'jenis_pk':'kl'}),
 ('BERAS_MASUK','beras','catat-produk-timbang-masuk',{}),
 ('BROKEN_MASUK','broken','catat-produk-timbang-masuk',{}),
])
@pytest.mark.parametrize('index',[0,1])
async def test_gudang_penerima_pk_dan_produk_tersimpan_tidak_mengikuti_jenis(pg,jenis,model,endpoint,fields,index):
    from app.models import PkPurchaseBatch,FinishedGoodsStock
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        tid=await _tiket(db,'TB-PENERIMA-'+jenis,jenis);await db.commit()
    async with await _klien(pg,role='admin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.post('/api/actions/'+endpoint,json={'timbangan_transaksi_id':tid,'warehouse_id':wh[index].id,**fields})
        assert r.status_code==200,r.text
    async with pg() as db:
        native=PkPurchaseBatch if model=='pk' else FinishedGoodsStock if model=='beras' else ByproductStock
        query=select(native).where(native.timbangan_transaksi_id==tid) if model=='pk' else select(native).where(native.source_type=='timbangan',native.source_id==tid)
        row=await db.scalar(query);assert row is not None and row.warehouse_id==wh[index].id
        from app.services.barang_masuk import riwayat
        own=await riwayat(db,g1=True,g2=True,tid=tid,user=ops[index]);other=await riwayat(db,g1=True,g2=True,tid=tid,user=ops[1-index])
        assert len(own)==1 and not other
        assert own[0]['catatan'][0]['gudang_nama']==wh[index].nama_gudang
