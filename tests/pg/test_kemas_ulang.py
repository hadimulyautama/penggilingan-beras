"""Neraca massa, kemasan baru, batch, reservasi, pemilik dan kiriman ulang."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import User,ProductSku,PackageSize,PackagingMaterial,PackagingPurchase,FinishedGoodsStock,KemasUlang
from app.database import now_local
from app.services import kemas_ulang as svc
from app.penggilingan.inventory import finished_goods as fg
from app.penggilingan.inventory.packaging import InventoryError,hitung_stok_kemasan,find_or_create_sku
from tests.pg.test_stok_produk_jasa import sosoh_jasa
pytestmark=pytest.mark.asyncio

async def awal(pg,g,jasa=False):
    async with pg() as db:
        u=await db.get(User,g['user'])
        await fg.catat_packing(db,user=u,kode_pol=g['kode_jasa'] if jasa else g['kode_pabrik'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=8)
        asal=await db.scalar(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id.desc()))
        sku=await db.get(ProductSku,asal.product_sku_id)
        for ukuran in (25,40,5):
            baru=await find_or_create_sku(db,kategori='beras_putih',material_kode='biasa',ukuran=ukuran)
            db.add(PackagingPurchase(kode=f'PKP-RE-{jasa}-{ukuran}',packaging_material_id=baru.packaging_material_id,package_size_id=baru.package_size_id,
                jumlah_lembar=100,tanggal=now_local().date(),waktu=now_local(),input_by=u.id,pelanggan_id=g['pelanggan_id'] if jasa else None))
        await db.commit()
        o=(await svc.pilihan(db,sku.id,asal.rice_quality_standard_id,asal.jasa_id,u.id))[0]
        return dict(sumber_id=asal.id,kunci=o['kunci'],jumlah_asal=4,material='biasa',ukuran=40,merk='',jumlah_baru=2),sku.id,asal.rice_quality_standard_id

@pytest.mark.parametrize('jasa',[False,True])
async def test_stok_kemasan_sisa_pemilik_idempoten(pg,sosoh_jasa,jasa):
    g=sosoh_jasa;req,sku,std=await awal(pg,g,jasa)
    owner=g['jasa_id'] if jasa else None;pel=g['pelanggan_id'] if jasa else None
    async with pg() as db:
        user=await db.get(User,g['user']);old=await db.get(ProductSku,sku)
        sebelum=await hitung_stok_kemasan(db,old.packaging_material_id,old.package_size_id,pelanggan_id=pel)
        r=await svc.simpan(db,user=user,**req)
        assert float(r.berat_asal_kg)==100 and float(r.berat_baru_kg)==80 and float(r.sisa_kg)==20
        assert r.jasa_id==owner
        assert (await fg.hitung_stok_finished_goods(db,sku,std,jasa_id=owner))=={'karung':4,'kg':100}
        assert (await fg.hitung_stok_finished_goods(db,r.sku_baru_id,std,jasa_id=owner))=={'karung':2,'kg':80}
        assert (await fg.hitung_stok_finished_goods(db,r.sku_baru_id,std,jasa_id=None if owner else g['jasa_id']))['kg']==0
        assert await hitung_stok_kemasan(db,old.packaging_material_id,old.package_size_id,pelanggan_id=pel)==sebelum
        baru=await db.get(ProductSku,r.sku_baru_id)
        assert await hitung_stok_kemasan(db,baru.packaging_material_id,baru.package_size_id,pelanggan_id=pel)==98
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg))))==200
        assert (await svc.simpan(db,user=user,**req)).id==r.id
        with pytest.raises(InventoryError):await svc.simpan(db,user=user,**{**req,'jumlah_baru':1})
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==1
        from app.services.stok import stok_produk
        kartu=next(x for x in await stok_produk(db,jasa_id=owner) if x.jenis=='medium')
        assert kartu.sisa_kg==(5000 if jasa else 9000)
        assert kartu.kemasan_stok_kg==180
        opsi=await svc.pilihan(db,sku,std,owner,user.id)
        sisa=next(o for o in opsi if o['curah'])
        await svc.simpan(db,user=user,**{**req,'sumber_id':sisa['id'],'kunci':sisa['kunci'],'jumlah_asal':10,'ukuran':5,'jumlah_baru':2})
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg))))==200
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)).where(FinishedGoodsStock.curah_kemas_ulang.is_(True))))==10

@pytest.mark.parametrize('ubah',[{'jumlah_asal':4.5},{'jumlah_asal':9},{'jumlah_baru':3},{'jumlah_baru':1.5},{'jumlah_asal':float('nan')}])
async def test_tolak_tanpa_mutasi(pg,sosoh_jasa,ubah):
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        with pytest.raises(InventoryError):await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**{**req,**ubah})
        await db.rollback()
        assert (await fg.hitung_stok_finished_goods(db,sku,std))['kg']==200
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==0

async def test_dua_operator_kiriman_sama_tidak_mengganda(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa)
    async def kirim():
        async with pg() as db:return (await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**req)).id
    assert len(set(await asyncio.gather(kirim(),kirim())))==1
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(KemasUlang))==1

async def test_kemasan_baru_tidak_cukup(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        s=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==40))
        p=await db.scalar(select(PackagingPurchase).where(PackagingPurchase.package_size_id==s.id));p.jumlah_lembar=1;await db.commit()
        with pytest.raises(InventoryError,match='kemasan baru'):await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**req)
        await db.rollback();assert (await fg.hitung_stok_finished_goods(db,sku,std))['kg']==200

async def test_stok_basi_dan_reservasi(pg,sosoh_jasa):
    from app.services import barang_keluar as bk
    from app.models import Pelanggan
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        user=await db.get(User,sosoh_jasa['user'])
        p=await db.scalar(select(Pelanggan).where(Pelanggan.id==sosoh_jasa['pelanggan_id']))
        p.kledo_contact_id=369;await db.commit()
        await bk.buat_perintah(db,user=user,pelanggan_id=p.id,baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=sku,std_id=std,jumlah_karung=6)])
        with pytest.raises(InventoryError,match='Stok berubah'):await svc.simpan(db,user=user,**req)
        await db.rollback()
        opsi=await svc.pilihan(db,sku,std,None,sosoh_jasa["user"])
        assert opsi[0]['jumlah']==2
        with pytest.raises(InventoryError):await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**{**req,'kunci':opsi[0]['kunci']})

async def test_ganti_merk_jenis_dan_ukuran(pg,sosoh_jasa):
    from app.models import Brand
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        b=Brand(nama='Merek Kemas Uji',aktif=True);db.add(b);await db.flush()
        target=await find_or_create_sku(db,kategori='beras_putih',material_kode='laminasi',ukuran=5,brand_nama=b.nama)
        db.add(PackagingPurchase(kode='PKP-BARU369',packaging_material_id=target.packaging_material_id,package_size_id=target.package_size_id,brand_id=b.id,
            jumlah_lembar=30,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh_jasa['user']))
        await db.commit()
        r=await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**{**req,'material':'laminasi','ukuran':5,'merk':b.nama,'jumlah_baru':20})
        assert r.sku_baru_id==target.id and float(r.sisa_kg)==0
        assert await hitung_stok_kemasan(db,target.packaging_material_id,target.package_size_id,b.id)==10
        assert (await fg.hitung_stok_finished_goods(db,target.id,std))=={'karung':20,'kg':100}

async def test_jasa_tidak_memakai_karung_pabrik(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa,True)
    async with pg() as db:
        size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==40))
        p=await db.scalar(select(PackagingPurchase).where(PackagingPurchase.package_size_id==size.id))
        p.pelanggan_id=None;await db.commit()
        with pytest.raises(InventoryError,match='pemilik ini'):await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**req)
        await db.rollback()
        assert (await fg.hitung_stok_finished_goods(db,sku,std,jasa_id=sosoh_jasa['jasa_id']))['kg']==200

async def test_halaman_dan_post_berizin_sesi(pg,sosoh_jasa):
    from tests.pg.test_barang_keluar import _klien
    from hmu_identitas.peran import SUPERADMIN
    from app.web import csrf,security
    req,sku,std=await awal(pg,sosoh_jasa,True)
    async with pg() as db:
        u=await db.get(User,sosoh_jasa['user']);u.role=SUPERADMIN;await db.commit()
    c=await _klien(pg,sosoh_jasa['user'],'kemas369')
    async with c:
        page=await c.get('/stok-produk/kemas-ulang',params={'sku_id':sku,'std_id':std,'jasa_id':sosoh_jasa['jasa_id']})
        assert page.status_code==200
        assert 'Bu Sri' in page.text and 'data-preview' in page.text
        import re
        token=re.search(r'id="formulir-sesi"[^>]*data-token="([^"]+)"',page.text).group(1)
        bad=await c.post('/api/kemas-ulang',json={**req,'setuju':True,'jasa_id':None},headers={'x-csrf-token':token})
        assert bad.status_code==422
        response=await c.post('/api/kemas-ulang',json={**req,'setuju':True},headers={'x-csrf-token':token})
        assert response.status_code==200,response.text
        p=await c.get('/stok-produk-jasa/detail',params={'jenis':'medium','pelanggan_id':sosoh_jasa['pelanggan_id']})
        assert 'Kemas ulang' in p.text and 'Sisa kemas ulang (curah)' in p.text
        from pathlib import Path
        Path('/tmp/kemas369-halaman.html').write_text(page.text)
        Path('/tmp/kemas369-stok-jasa.html').write_text(p.text)

async def test_dua_operator_tidak_memakai_batch_sama(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        asal_user=await db.get(User,sosoh_jasa['user'])
        op=User(nama='Operator kemas kedua',role=asal_user.role,status='aktif',default_warehouse_id=asal_user.default_warehouse_id)
        db.add(op);await db.commit();uid=op.id
        opsi=(await svc.pilihan(db,sku,std,None,uid))[0]
        req2={**req,'kunci':opsi['kunci'],'jumlah_asal':8,'jumlah_baru':5}
    async def kirim(uid,data):
        async with pg() as db:return await svc.simpan(db,user=await db.get(User,uid),**data)
    results=await asyncio.gather(kirim(sosoh_jasa['user'],{**req,'jumlah_asal':8,'jumlah_baru':5}),kirim(uid,req2),return_exceptions=True)
    assert sum(isinstance(x,InventoryError) for x in results)==1
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==1
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg))))==200

async def test_dua_batch_berebut_kemasan_baru(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        user=await db.get(User,sosoh_jasa['user'])
        await fg.catat_packing(db,user=user,kode_pol=sosoh_jasa['kode_pabrik'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=4)
        size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==40))
        stock=await db.scalar(select(PackagingPurchase).where(PackagingPurchase.package_size_id==size.id));stock.jumlah_lembar=3;await db.commit()
        opsi=await svc.pilihan(db,sku,std,None,user.id)
        req2={**req,'sumber_id':opsi[1]['id'],'kunci':opsi[1]['kunci']}
    async def kirim(data):
        async with pg() as db:return await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**data)
    result=await asyncio.gather(kirim(req),kirim(req2),return_exceptions=True)
    assert sum(isinstance(x,InventoryError) for x in result)==1
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==1
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg))))==300

async def test_pergantian_pemilik_menahan_form_lama(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa,True)
    async with pg() as db:
        sumber=await db.get(FinishedGoodsStock,req['sumber_id']);sumber.jasa_id=None;await db.commit()
        with pytest.raises(InventoryError,match='Stok berubah'):
            await svc.simpan(db,user=await db.get(User,sosoh_jasa['user']),**req)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==0
        assert (await fg.hitung_stok_finished_goods(db,sku,std))['kg']==200

async def test_kemasan_asal_dari_luar_tidak_dibebankan(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,req['sumber_id']);row.kemasan_mengurangi_stok=False;await db.commit()
        user=await db.get(User,sosoh_jasa['user'])
        req['kunci']=(await svc.pilihan(db,sku,std,None,user.id))[0]['kunci']
        lama=await db.get(ProductSku,sku)
        before=await hitung_stok_kemasan(db,lama.packaging_material_id,lama.package_size_id)
        r=await svc.simpan(db,user=user,**req)
        assert r.karung_lama_dihitung==0
        assert await hitung_stok_kemasan(db,lama.packaging_material_id,lama.package_size_id)==before

async def test_sisa_pecahan_tetap_tercatat(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa)
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,req['sumber_id']);row.berat_total_kg=Decimal('200.04');await db.commit()
        user=await db.get(User,sosoh_jasa['user'])
        req['kunci']=(await svc.pilihan(db,sku,std,None,user.id))[0]['kunci']
        r=await svc.simpan(db,user=user,**req)
        assert Decimal(str(r.sisa_kg))==Decimal('20.02')
        assert Decimal(str(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)))))==Decimal('200.04')

async def test_pindah_kepemilikan_karung_tidak_ikut_memindahkan_sisa_curah(pg,sosoh_jasa):
    req,sku,std=await awal(pg,sosoh_jasa,True)
    async with pg() as db:
        user=await db.get(User,sosoh_jasa['user'])
        await svc.simpan(db,user=user,**{**req,'ukuran':25,'jumlah_baru':3})
        await fg.catat_packing(db,user=user,kode_pol=sosoh_jasa['kode_jasa'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=4)
        kg=await fg.pindah_kepemilikan_barang_jadi(db,user=user,sku_id=sku,standard_id=std,jasa_id=sosoh_jasa['jasa_id'],karung=10)
        assert kg==250
        sisa=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.curah_kemas_ulang.is_(True)))
        assert sisa.jasa_id==sosoh_jasa['jasa_id'] and float(sisa.berat_total_kg)==25

@pytest.mark.parametrize('jasa',[False,True])
async def test_preview_kemasan_tidak_membuat_sku_atau_mengubah_stok(pg,sosoh_jasa,jasa):
    req,sku,std=await awal(pg,sosoh_jasa,jasa)
    async with pg() as db:
        n=await db.scalar(select(func.count()).select_from(ProductSku))
        saldo=await svc.saldo_kemasan(db,req['sumber_id'],'biasa',40,'')
        assert saldo=={'tersedia':100,'pemilik':'pelanggan jasa' if jasa else 'pabrik'}
        kosong=await svc.saldo_kemasan(db,req['sumber_id'],'laminasi',25,'')
        assert kosong['tersedia']==0
        assert await db.scalar(select(func.count()).select_from(ProductSku))==n
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==0
        assert (await fg.hitung_stok_finished_goods(db,sku,std,jasa_id=sosoh_jasa['jasa_id'] if jasa else None))['kg']==200

async def test_preview_http_izin_dan_saldo_pemilik(pg,sosoh_jasa):
    from tests.pg.test_barang_keluar import _klien
    from hmu_identitas.peran import SUPERADMIN
    req,sku,std=await awal(pg,sosoh_jasa,True)
    async with pg() as db:
        u=await db.get(User,sosoh_jasa['user']);u.role=SUPERADMIN;await db.commit()
    c=await _klien(pg,sosoh_jasa['user'],'preview372')
    async with c:
        r=await c.get('/api/kemas-ulang/kemasan',params={'sumber_id':req['sumber_id'],'material':'biasa','ukuran':40})
        assert r.status_code==200 and r.json()['tersedia']==100
        bad=await c.get('/api/kemas-ulang/kemasan',params={'sumber_id':req['sumber_id'],'material':'laminasi','ukuran':25,'merk':'Merek tidak ada'})
        assert bad.status_code==400

@pytest.mark.parametrize('jasa',[False,True])
async def test_pilihan_hanya_saldo_positif_dan_merek_pemilik(pg,sosoh_jasa,jasa):
    from app.models import Brand
    req,sku,std=await awal(pg,sosoh_jasa,jasa)
    async with pg() as db:
        b=Brand(nama='Merek tersedia',aktif=True);mati=Brand(nama='Merek nonaktif',aktif=False)
        db.add_all([b,mati]);await db.flush()
        for brand,owner,qty in [(b.id,sosoh_jasa['pelanggan_id'] if jasa else None,7),
                                (mati.id,sosoh_jasa['pelanggan_id'] if jasa else None,20),
                                (None,None if jasa else sosoh_jasa['pelanggan_id'],30)]:
            target=await find_or_create_sku(db,kategori='beras_putih',material_kode='laminasi',ukuran=25)
            db.add(PackagingPurchase(kode=f'PIL-{brand}-{owner}',packaging_material_id=target.packaging_material_id,
                package_size_id=target.package_size_id,brand_id=brand,pelanggan_id=owner,jumlah_lembar=qty,
                tanggal=now_local().date(),waktu=now_local(),input_by=sosoh_jasa['user']))
        await db.commit()
        data=await svc.kemasan_tersedia(db,'beras_putih',sosoh_jasa['jasa_id'] if jasa else None)
        p=next(x for x in data if x['value']=='laminasi|25')
        assert p['merek']==[{'value':'Merek tersedia','label':'Merek tersedia','tersedia':7}]
        assert all(m['tersedia']>0 for x in data for m in x['merek'])
        assert 'laminasi|5' not in [x['value'] for x in data]
        before=await db.scalar(select(func.count()).select_from(KemasUlang))
        await db.execute(__import__('sqlalchemy').update(PackagingPurchase).values(jumlah_lembar=0))
        await db.commit()
        assert await svc.kemasan_tersedia(db,'beras_putih',sosoh_jasa['jasa_id'] if jasa else None)==[]
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==before
