"""Bukti pratinjau baca saja dibandingkan transaksi domain, bukan simulasi UI."""
import pytest
from sqlalchemy import select,func,update
from app.models import User,PolishingOutputLog,PolishingProcess,ByproductStock,BrokenKeSilo,FinishedGoodsStock,Silo,Warehouse
from app.services.rencana_broken_silo import rincian
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_masukkan_broken_silo import sosoh,_curah,_kemas
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

async def hasil(pg,sosoh,w):
    async with pg() as db:
        await db.execute(update(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==sosoh['proc_id']).values(berat_kg=w));await db.commit()

@pytest.mark.parametrize('curah,packs,output,w',[(600,0,600,200),(0,10,500,175),(0,0,600,475),(250,20,1400,475)])
async def test_rencana_sama_dengan_hasil_simpan(pg,sosoh,curah,packs,output,w):
    await hasil(pg,sosoh,output)
    if curah:await _curah(pg,sosoh,curah)
    if packs:await _kemas(pg,sosoh,jumlah_karung=packs)
    async with pg() as db:
        before=await db.scalar(select(func.count()).select_from(ByproductStock));bags=await db.scalar(select(func.coalesce(func.sum(FinishedGoodsStock.jumlah_karung),0)))
        d=await rincian(db,'pemilik|pabrik',w,'C');assert d['saldo']['total']==output
        assert await db.scalar(select(func.count()).select_from(ByproductStock))==before
        assert await db.scalar(select(func.coalesce(func.sum(FinishedGoodsStock.jumlah_karung),0)))==bags
        p=d['rencana'];r=await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=None,nama_silo='C',berat_kg=w)
        assert r.dibongkar_dari_karung_kg==p['bongkar_kg']
    async with pg() as db:
        akhir=await rincian(db,'pemilik|pabrik');assert akhir['saldo']==p['sisa']
        assert await g2.hitung_stok_silo(db,sosoh['silo']['C'])==w

async def test_dua_ukuran_karung_fifo_dan_kelebihan(pg,sosoh):
    from app.penggilingan.inventory.finished_goods import catat_packing
    await hasil(pg,sosoh,200)
    async with pg() as db:
        u=await db.get(User,sosoh['user']);await catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='broken',material_kode='polos',ukuran=25,jumlah_karung=2)
        await catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='broken',material_kode='putih',ukuran=50,jumlah_karung=3)
        p=(await rincian(db,'pemilik|pabrik',175,'C'))['rencana'];assert p['karung']==5 and p['bongkar_kg']==200 and p['kelebihan']==25
        await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=u,jasa_id=None,nama_silo='C',berat_kg=175)
    async with pg() as db:assert (await rincian(db,'pemilik|pabrik'))['saldo']==p['sisa']

async def test_fifo_bukan_seluruh_curah_global_dahulu(pg,sosoh):
    from app.database import now_local
    await hasil(pg,sosoh,50);await _kemas(pg,sosoh,jumlah_karung=1)
    async with pg() as db:
        p=PolishingProcess(kode_proses='POL-UJIB-BARU',status='selesai',waktu_mulai=now_local(),created_by=sosoh['user']);db.add(p);await db.flush()
        db.add(ByproductStock(jenis_produk='broken',source_type='polishing',source_id=p.id,berat_kg=300,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']))
        await db.commit()
        d=await rincian(db,'pemilik|pabrik',75,'C');p=d['rencana'];assert p['urutan'][0]['isi_karung']==50 and p['urutan'][1]['curah']==25
        legacy=await rincian(db,sosoh['kode_pol']+'|');assert legacy['saldo']['total']==50 and len(legacy['sumber'])==1
        await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=None,nama_silo='C',berat_kg=75)
    async with pg() as db:assert (await rincian(db,'pemilik|pabrik'))['saldo']==p['sisa']

async def test_penerimaan_timbang_dipakai_sebelum_proses(pg,sosoh):
    from app.database import now_local
    async with pg() as db:
        db.add(ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=123,berat_kg=100,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']));await db.commit()
        d=await rincian(db,'pemilik|pabrik',125,'C');assert d['rencana']['urutan'][0]['tipe']=='timbangan' and d['rencana']['urutan'][0]['kg']==100
        await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=None,nama_silo='C',berat_kg=125)
    async with pg() as db:assert (await rincian(db,'pemilik|pabrik'))['saldo']==d['rencana']['sisa']

@pytest.mark.parametrize('role,view,wh,izin',[
 ('operator',None,'g2',True),('operator',None,'g1',False),('admin',None,'g2',False),('superadmin',None,'g2',True),
 ('admin','operator:g2','g2',True),('admin','operator:g1','g1',False),('superadmin','operator:g1','g1',False),('staff',None,'g2',False)])
async def test_izin_baca_dan_tulis(pg,sosoh,role,view,wh,izin):
    async with pg() as db:
        u=await db.get(User,sosoh['user']);u.role=role
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh).limit(1))
        if wid is None:w=Warehouse(nama_gudang='Gudang uji hak',kode_fungsi=wh);db.add(w);await db.flush();wid=w.id
        u.default_warehouse_id=wid;await db.commit()
    async with await _klien(pg,sosoh['user'],'broken-akses',mode='operator' if role=='operator' else 'admin') as c:
        if view:assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})).status_code==303
        d=await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=10,silo='C'));assert d.status_code==200 if izin else d.status_code in [401,403]
        d=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',berat_kg=10,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)});assert d.status_code==200 if izin else d.status_code in [401,403],d.text

@pytest.mark.parametrize('w',[0,-1,'Infinity','NaN','abc',None])
async def test_isian_tidak_sah_tanpa_mutasi(pg,sosoh,w):
    async with await _klien(pg,sosoh['user'],'broken-invalid',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',berat_kg=w,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code in [400,422]
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(BrokenKeSilo))==0

async def test_saldo_terbaru_dan_nama_silo_master(pg,sosoh):
    async with pg() as db:
        silo=await db.get(Silo,sosoh['silo']['C']);silo.nama_silo='Silo Campuran Timur';await db.commit()
    async with await _klien(pg,sosoh['user'],'broken-berubah',mode='admin') as c:
        d=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=7000,silo='Campuran Timur'))).json();assert d['rencana']['kg']==7000
        await hasil(pg,sosoh,500)
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',berat_kg=7000,silo='Campuran Timur'),headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==400 and '500' in r.text,r.text
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(BrokenKeSilo))==0

async def test_pemilik_penerima_bukan_pemilik_hasil_mentah(pg,sosoh):
    from app.models import Jasa,Pelanggan
    from app.database import now_local
    async with pg() as db:
        pel=Pelanggan(nama_pelanggan='Pemilik titipan uji');db.add(pel);await db.flush();j=Jasa(kode='JAS-BROKEN-SHARE',pelanggan_id=pel.id);db.add(j);await db.flush()
        db.add(ByproductStock(jenis_produk='broken',source_type='polishing',source_id=sosoh['proc_id'],berat_kg=100,jasa_id=j.id,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']));await db.commit()
        d=await rincian(db,f'pemilik|{j.id}',75,'D');assert d['saldo']['total']==100 and d['saldo']['mesin']==0 and d['rencana']['mesin']==0

async def test_batas_transaksi_multisumber_lama_tercatat(pg,sosoh,monkeypatch):
    """Dokumentasikan keterbatasan lama: sumber pertama sudah commit ketika
    sumber berikutnya gagal. Perapian tidak mengklaim rollback seluruh sumber."""
    from app.database import now_local
    await hasil(pg,sosoh,100)
    async with pg() as db:
        p=PolishingProcess(kode_proses='POL-BROKEN-GAGAL-2',status='selesai',waktu_mulai=now_local(),created_by=sosoh['user']);db.add(p);await db.flush()
        db.add(ByproductStock(jenis_produk='broken',source_type='polishing',source_id=p.id,berat_kg=100,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']));await db.commit()
    asli=g2.masukkan_broken_ke_silo;called=0
    async def gagal(*a,**kw):
        nonlocal called
        called+=1
        if called==2:raise g2.Gudang2Error('Gangguan sumber kedua data uji')
        return await asli(*a,**kw)
    monkeypatch.setattr(g2,'masukkan_broken_ke_silo',gagal)
    async with pg() as db:
        with pytest.raises(g2.Gudang2Error):await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=None,nama_silo='C',berat_kg=150)
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,sosoh['silo']['C'])==100

@pytest.mark.parametrize('w,rencana,aktual',[(0.3,0,0),(500.49,500,500),(175.123,175.123,175.12)])
async def test_toleransi_lama_dan_bobot_aktual(pg,sosoh,w,rencana,aktual):
    await hasil(pg,sosoh,500);await _kemas(pg,sosoh,jumlah_karung=10)
    async with pg() as db:
        d=await rincian(db,'pemilik|pabrik',w,'C');assert d['rencana']['kg']==pytest.approx(rencana)
    async with await _klien(pg,sosoh['user'],'broken-presisi',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',berat_kg=w,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        assert r.json()['rincian_broken']['kg']==pytest.approx(aktual)

async def test_perbaikan_saldo_karung_tetap_terpakai_setelah_bongkar(pg,sosoh):
    """Persetujuan pemilik: saldo karung kosong tidak naik setelah bongkar."""
    from app.models import PackagingPurchase,ProductSku
    from app.database import now_local
    from app.penggilingan.inventory.packaging import hitung_stok_kemasan
    await hasil(pg,sosoh,500);await _kemas(pg,sosoh,jumlah_karung=10)
    async with pg() as db:
        sku=await db.scalar(select(ProductSku).join(FinishedGoodsStock,FinishedGoodsStock.product_sku_id==ProductSku.id).where(FinishedGoodsStock.source_id==sosoh['proc_id']))
        db.add(PackagingPurchase(kode='PKM-BROKEN-UJI',packaging_material_id=sku.packaging_material_id,package_size_id=sku.package_size_id,jumlah_lembar=100,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']));await db.commit()
        before=await hitung_stok_kemasan(db,sku.packaging_material_id,sku.package_size_id,sku.brand_id);assert before==90
        await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=None,nama_silo='C',berat_kg=175)
        after=await hitung_stok_kemasan(db,sku.packaging_material_id,sku.package_size_id,sku.brand_id)
        assert after==90

@pytest.mark.parametrize('owner_jasa,kurangi,berat',[(False,True,500),(False,False,175),(True,True,175)])
async def test_jejak_karung_pemilik_flag_dan_stok_habis(pg,sosoh,owner_jasa,kurangi,berat):
    from app.models import PackagingPurchase,ProductSku,BrokenKarungDibongkar,Jasa,Pelanggan
    from app.database import now_local
    from app.penggilingan.inventory.packaging import hitung_stok_kemasan
    await hasil(pg,sosoh,500);await _kemas(pg,sosoh,jumlah_karung=10)
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_id==sosoh['proc_id']));sku=await db.get(ProductSku,row.product_sku_id)
        jid=pid=None
        if owner_jasa:
            pel=Pelanggan(nama_pelanggan='Pemilik karung uji');db.add(pel);await db.flush();j=Jasa(kode='JAS-BONGKAR-KARUNG',pelanggan_id=pel.id);db.add(j);await db.flush();jid,pid=j.id,pel.id;row.jasa_id=jid
        row.kemasan_mengurangi_stok=kurangi
        db.add(PackagingPurchase(kode='PKM-BONGKAR-2',packaging_material_id=sku.packaging_material_id,package_size_id=sku.package_size_id,jumlah_lembar=100,pelanggan_id=pid,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']));await db.commit()
        before=await hitung_stok_kemasan(db,sku.packaging_material_id,sku.package_size_id,pelanggan_id=pid)
        await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=jid,nama_silo='C',berat_kg=berat)
        assert await hitung_stok_kemasan(db,sku.packaging_material_id,sku.package_size_id,pelanggan_id=pid)==before
        records=(await db.scalars(select(BrokenKarungDibongkar))).all();assert sum(r.jumlah_karung for r in records)==(10 if berat==500 else 4)
        assert all(r.jasa_id==jid and r.mengurangi_stok==kurangi for r in records)
        if owner_jasa:assert await hitung_stok_kemasan(db,sku.packaging_material_id,sku.package_size_id)==0
        if berat==500:assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==0

async def test_jejak_bongkar_ikut_rollback_sumber_gagal(pg,sosoh):
    from app.models import BrokenKarungDibongkar
    await hasil(pg,sosoh,500);await _kemas(pg,sosoh,jumlah_karung=10)
    async with await _klien(pg,sosoh['user'],'broken-rollback-karung',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses=sosoh['kode_pol']+'|',berat_kg=550,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==400
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(BrokenKarungDibongkar))==0
        assert await db.scalar(select(func.sum(FinishedGoodsStock.jumlah_karung)))==10
