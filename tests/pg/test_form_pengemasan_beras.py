"""Ringkasan pengemasan memakai saldo writer; tidak menambah syarat karung."""
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy import select,func,text,update
from app.models import (User,PolishingProcess,PolishingOutputLog,FinishedGoodsStock,
    ProductSku,ActivityLog,PackagingPurchase,Jasa,Pelanggan,Warehouse,BerasKeSilo)
from app.database import now_local
from app.penggilingan.inventory import finished_goods as bj,packaging as kms
from app.services.rencana_packing import rincian
from tests.pg.test_masukkan_beras_silo import sosoh
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

@pytest_asyncio.fixture
async def packing(pg,sosoh):
    async with pg() as db:
        u=await db.get(User,sosoh['user']);p=await db.get(PolishingProcess,sosoh['proc_id']);p.status='proses';p.waktu_selesai=None
        mat=await kms.get_material(db,'laminasi');size=await kms.get_size(db,25)
        db.add(PackagingPurchase(kode='PKP-UJI-PACK',packaging_material_id=mat.id,package_size_id=size.id,jumlah_lembar=50,tanggal=now_local().date(),waktu=now_local(),input_by=u.id));await db.commit()
        await bj.catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='beras_putih',grade='medium',material_kode='laminasi',ukuran=25,jumlah_karung=20)
        fg=await db.scalar(select(FinishedGoodsStock));db.add(FinishedGoodsStock(product_sku_id=fg.product_sku_id,rice_quality_standard_id=fg.rice_quality_standard_id,source_type='polishing',source_id=p.id,jumlah_karung=0,berat_total_kg=100,warehouse_id=fg.warehouse_id,waktu=now_local(),input_by=u.id))
        db.add(BerasKeSilo(kode_pindah='BRS-UJI-PACK',polishing_process_id=p.id,jenis='medium',silo_id=sosoh['silo_beras'],berat_kg=250,tanggal=now_local().date(),waktu=now_local(),input_by=u.id));await db.commit()
    return dict(**sosoh,sumber=sosoh['kode_pol']+'|medium')

async def simpan(db,p,n=10,**kw):
    return await bj.catat_packing(db,user=await db.get(User,p['user']),kode_pol=p['kode_pol'],kategori='beras_putih',grade='medium',material_kode='laminasi',ukuran=25,jumlah_karung=n,**kw)

async def test_saldo_dari_writer_bukan_seluruh_curah_dan_baca_tidak_menulis(pg,packing):
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        d=await rincian(db,packing['sumber'],'laminasi|25','',10)
        assert d['saldo']==dict(jenis='medium',hasil=8000,dialokasikan=600,dipindah_silo=250,tersedia=7150)
        assert d['maksimal']==286 and d['karung']==30
        assert d['rencana']==dict(jumlah=10,berat=250,sisa=6900,sisa_karung=20)
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==2
    async with pg() as db:
        await simpan(db,packing)
        d=await rincian(db,packing['sumber'],'laminasi|25')
        assert d['saldo']['tersedia']==6900 and d['karung']==20
        proc=await db.get(PolishingProcess,packing['proc_id']);assert proc.status=='proses' and proc.waktu_selesai is None
        row=await db.scalar(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id.desc()))
        assert row.source_id==proc.id and row.jasa_id is None and row.jumlah_karung==10 and float(row.berat_total_kg)==250 and row.input_by==packing['user']
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='finished_goods_stock'))==2

@pytest.mark.parametrize('jumlah',['',0,-1,1.5,'NaN','Infinity','salah',287])
async def test_invalid_dan_saldo_tetap(pg,packing,jumlah):
    async with pg() as db:
        d=await rincian(db,packing['sumber'],'laminasi|25','',jumlah);assert d['rencana'] is None
    async with await _klien(pg,packing['user'],'pack-invalid',mode='admin') as c:
        r=await c.post('/api/actions/catat-packing',json=dict(sumber=packing['sumber'],kemasan='laminasi|25',jumlah_karung=jumlah),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code in [400,422]
    async with pg() as db:assert (await rincian(db,packing['sumber']))['saldo']['tersedia']==7150

async def test_merk_opsional_karung_kurang_bukan_larangan_baru_dan_sisa_pecahan(pg,packing):
    async with pg() as db:
        d=await rincian(db,packing['sumber'],'laminasi|25','Sakura',10)
        assert d['karung']==0 and d['rencana']['sisa_karung']==-10
        await simpan(db,packing,10,brand_nama='Sakura')
        row=await db.scalar(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id.desc()));sku=await db.get(ProductSku,row.product_sku_id);assert sku.brand_id==(await kms.get_brand(db,'Sakura')).id
        # Sisa kurang dari satu kemasan tetap data, bukan dibulatkan menjadi karung.
        (await db.scalar(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==packing['proc_id']))).berat_kg=1127.5;await db.commit()
        d=await rincian(db,packing['sumber'],'laminasi|25');assert d['saldo']['tersedia']==27.5 and d['maksimal']==1
        await simpan(db,packing,1);assert (await rincian(db,packing['sumber'],'laminasi|25'))['saldo']['tersedia']==2.5

async def test_sumber_dipilih_tidak_mengambil_proses_lain_dan_saldo_berubah(pg,packing):
    async with pg() as db:
        p=PolishingProcess(kode_proses='POL-PACK-LAIN',status='selesai',waktu_mulai=now_local(),created_by=packing['user']);db.add(p);await db.flush();db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='medium',berat_kg=9000,waktu_update=now_local(),input_by=packing['user']));await db.commit()
        pid=p.id
        assert (await rincian(db,packing['sumber'],'laminasi|25','',280))['rencana']
        await simpan(db,packing,10)
        with pytest.raises(bj.InventoryError,match='tinggal'):await simpan(db,packing,280)
        await db.rollback();assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock).where(FinishedGoodsStock.source_id==pid))==0

async def test_karung_pelanggan_mengikuti_kontak_dan_pemilik_hasil(pg,packing):
    async with pg() as db:
        pel=Pelanggan(nama_pelanggan='Bu Sri Packing');db.add(pel);await db.flush();j=Jasa(kode='JAS-PACK-JASA',pelanggan_id=pel.id);db.add(j);await db.flush();(await db.get(PolishingProcess,packing['proc_id'])).jasa_id=j.id
        await db.execute(update(FinishedGoodsStock).values(jasa_id=j.id));await db.execute(update(PackagingPurchase).values(pelanggan_id=pel.id));await db.commit()
        d=await rincian(db,packing['sumber'],'laminasi|25','',10);assert d['jasa_id']==j.id and 'Bu Sri' in d['pemilik'] and d['karung']==30
        await simpan(db,packing);row=await db.scalar(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id.desc()));assert row.jasa_id==j.id
        d=await rincian(db,packing['sumber'],'laminasi|25');assert d['karung']==20
        mat=await kms.get_material(db,'laminasi');size=await kms.get_size(db,25);assert await kms.hitung_stok_kemasan(db,mat.id,size.id)==0

@pytest.mark.parametrize('role,view,wh,izin',[
 ('operator',None,'g2',True),('operator',None,'g1',False),('admin',None,'g2',True),('superadmin',None,'g2',True),
 ('admin','operator:g2','g2',True),('admin','operator:g1','g1',False),('superadmin','operator:g1','g1',False),('staff',None,'g2',False)])
async def test_izin_sama_dengan_packing_lama_bukan_masukkan_silo(pg,packing,role,view,wh,izin):
    async with pg() as db:
        u=await db.get(User,packing['user']);u.role=role;u.default_warehouse_id=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh).limit(1));await db.commit()
    async with await _klien(pg,packing['user'],'pack-izin',mode='operator' if role=='operator' else 'admin') as c:
        if view:assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})).status_code==303
        d=await c.get('/api/actions/rincian-packing-beras',params={'sumber':packing['sumber']})
        assert d.status_code==200 if izin else d.status_code in [401,403]
        r=await c.post('/api/actions/catat-packing',json=dict(sumber=packing['sumber'],kemasan='laminasi|25',jumlah_karung=10),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200 if izin else r.status_code in [401,403]

async def test_kontrak_lama_dan_beras_b(pg,packing):
    async with await _klien(pg,packing['user'],'pack-legacy',mode='admin') as c:
        r=await c.post('/api/actions/catat-packing',json=dict(kode_pol=packing['kode_pol'],produk='beras_putih|laminasi|25',grade='medium',jumlah_karung=10),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200 and r.json()['rincian_packing']['berat']==250
    async with pg() as db:
        db.add(PolishingOutputLog(polishing_process_id=packing['proc_id'],jenis='beras_b',berat_kg=100,waktu_update=now_local(),input_by=packing['user']));await db.commit()
        d=await rincian(db,packing['kode_pol']+'|beras_b','laminasi|25','',2);assert d['rencana']['berat']==50
        await bj.catat_packing(db,user=await db.get(User,packing['user']),kode_pol=packing['kode_pol'],kategori='beras_b',material_kode='laminasi',ukuran=25,jumlah_karung=2)
        assert (await db.scalar(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id.desc()))).rice_quality_standard_id is None

async def test_konkurensi_dan_rollback(pg,packing,monkeypatch):
    async def satu():
        async with pg() as db:return await simpan(db,packing,200)
    hasil=await asyncio.gather(satu(),satu(),return_exceptions=True);assert sum(isinstance(x,bj.InventoryError)for x in hasil)==1
    async with pg() as db:assert (await rincian(db,packing['sumber']))['saldo']['tersedia']==2150
    async def gagal(*a,**kw):raise RuntimeError('Audit uji gagal')
    monkeypatch.setattr(bj,'log_activity',gagal)
    with pytest.raises(RuntimeError):
        async with pg() as db:await simpan(db,packing,10)
    async with pg() as db:assert (await rincian(db,packing['sumber']))['saldo']['tersedia']==2150

async def test_picker_lingkup_dan_hasil_samping_tetap_lama(pg,packing):
    async with pg() as db:
        db.add(PolishingOutputLog(polishing_process_id=packing['proc_id'],jenis='broken',berat_kg=200,waktu_update=now_local(),input_by=packing['user']));await db.commit()
        assert await rincian(db,packing['kode_pol']+'|broken')=={'beras':False}
    async with await _klien(pg,packing['user'],'pack-side',mode='admin') as c:
        opts=(await c.get('/api/actions/beras-belum-dikemas?jenis=medium&pemilik=pabrik')).json();assert [x['value']for x in opts]==[packing['sumber']]
        r=await c.post('/api/actions/catat-packing',json=dict(sumber=packing['kode_pol']+'|broken',kemasan='putih|50',jumlah_karung=2),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200 and set(r.json())=={'ok','pesan'}
