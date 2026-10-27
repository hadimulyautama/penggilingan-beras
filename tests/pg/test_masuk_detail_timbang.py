"""Penerimaan baca saja; seluruh tabel pada database uji loopback terpisah."""
import json
from decimal import Decimal
import pytest
import pytest_asyncio
import httpx
from sqlalchemy import select, text
from fastapi import FastAPI
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from app.database import now_local
from app.models import User, Supplier, Warehouse, PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock, ByproductStock, ProductSku, PackagingMaterial, PackageSize
from app.services.seed import seed_master
from app.services.masuk_detail_timbang import baca
from app.web import internal

@pytest_asyncio.fixture
async def contoh(pg):
    await seed_master()
    async with pg() as db:
        u=User(nama='Penerima Uji',role=P.ADMIN,status='aktif');s=Supplier(nama_supplier='Supplier Uji')
        db.add_all([u,s]);await db.flush()
        a=Akun(user_id=u.id,username='penerima-uji',password_hash='hash-uji',status='aktif');db.add(a);await db.flush()
        tid=await db.scalar(text("""INSERT INTO timbangan_transaksi
        (kode,tanggal,arah,jenis_kode,cara_timbang,supplier_id,nomor_polisi,timbang1_kg,timbang1_waktu,status_tiket,status_transaksi)
        VALUES ('TB-MASUK-UJI',CURRENT_DATE,'MASUK','GABAH_BASAH','DUA_KALI',:sid,'B 1 UJ',15000,NOW(),'TERBUKA','AKTIF') RETURNING id"""),{'sid':s.id})
        await db.commit();return dict(tid=tid,uid=u.id,sid=s.id,aid=a.id)

async def catat(db,x,jenis='GABAH_BASAH',berat=100,status='baru',sumber='timbangan',suffix='A'):
    await db.execute(text('UPDATE timbangan_transaksi SET jenis_kode=:j WHERE id=:id'),{'j':jenis,'id':x['tid']})
    umum=dict(input_by=x['uid'])
    if jenis in ('GABAH_BASAH','GABAH_KERING','BERAS_PK'):
        kw=dict(kode_batch='BATCH-UJI-'+suffix,supplier_id=x['sid'],berat_total_kg=berat,
            tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),sumber_berat=sumber,
            status_batch=status,timbangan_transaksi_id=x['tid'],**umum)
        model=PkPurchaseBatch if jenis=='BERAS_PK' else PurchaseBatch
        if model==PurchaseBatch:kw['kondisi_gabah']='basah' if jenis=='GABAH_BASAH' else 'kering'
        b=model(**kw)
    elif jenis=='BERAS_MASUK':
        sku=ProductSku(kategori='beras_putih',packaging_material_id=await db.scalar(select(PackagingMaterial.id)),package_size_id=await db.scalar(select(PackageSize.id)),aktif=True)
        db.add(sku);await db.flush();sku=sku.id
        b=FinishedGoodsStock(product_sku_id=sku,source_type='timbangan',source_id=x['tid'],jumlah_karung=2,berat_total_kg=berat,waktu=now_local(),**umum)
    else:
        b=ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=x['tid'],berat_kg=berat,tanggal=now_local().date(),waktu=now_local(),**umum)
    db.add(b);await db.flush();return b

async def sidik(db):
    # Membandingkan seluruh tabel bisnis dan audit, bukan hanya jumlah tiket.
    names=(await db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'alembic%' ORDER BY tablename"))).all()
    return {n:await db.scalar(text(f'SELECT md5(COALESCE(string_agg(row_to_json(t)::text,\'\' ORDER BY row_to_json(t)::text),\'\')) FROM "{n}" t')) for n in names}

@pytest.mark.parametrize('jenis',['GABAH_BASAH','GABAH_KERING','BERAS_PK','BERAS_MASUK','BROKEN_MASUK'])
async def test_lima_jenis_tidak_menulis_dan_tidak_ada_uang(pg,contoh,jenis):
    async with pg() as db:
        await catat(db,contoh,jenis);await db.commit()
        awal=await sidik(db)
        for _ in range(3):
            d=await baca(db,contoh['tid'],await db.get(User,contoh['uid']))
            assert len(d['catatan'])==1 and Decimal(d['berat_diterima_kg'])==100
            assert not any(k in json.dumps(d,default=str).lower() for k in ['hpp','harga','nilai_uang'])
        assert await sidik(db)==awal

@pytest.mark.parametrize('kasus',['belum','terpecah','ditolak','sementara','belum-diukur','sebagian','habis'])
async def test_total_penerimaan_sesuai_pembaca_lama(pg,contoh,kasus):
    async with pg() as db:
        if kasus!='belum':
            await catat(db,contoh,jenis='BERAS_MASUK' if kasus=='terpecah' else 'GABAH_BASAH',berat=None if kasus in ('belum-diukur','sebagian') else 100,
                sumber='menunggu' if kasus in ('belum-diukur','sebagian') else 'perkiraan' if kasus=='sementara' else 'timbangan',
                status='ditolak' if kasus=='ditolak' else 'selesai' if kasus=='habis' else 'baru')
        if kasus=='terpecah':await catat(db,contoh,jenis='BERAS_MASUK',berat=Decimal('50.25'),suffix='B')
        await db.commit();d=await baca(db,contoh['tid'],await db.get(User,contoh['uid']))
        if kasus in ('belum','ditolak','belum-diukur','sebagian'):assert d['berat_diterima_kg'] is None
        if kasus=='terpecah':assert Decimal(d['berat_diterima_kg'])==Decimal('150.25')
        if kasus=='sementara':assert d['keterangan_berat']=='Belum final' and d['catatan'][0]['sementara']
        if kasus=='habis':assert Decimal(d['berat_diterima_kg'])==100

@pytest.mark.parametrize('role,gudang,lihat,aktif,token,kode',[
    (P.OPERATOR,'g1',None,True,True,200),(P.OPERATOR,'g2',None,True,True,403),
    (P.OPERATOR,'g2','operator:g1',True,True,200),(P.OPERATOR,'g2',P.SUPERADMIN,True,True,403),
    (P.ADMIN,None,None,True,True,200),(P.SUPERADMIN,None,None,True,True,200),
    (P.ADMIN,None,'operator:g2',True,True,403),(P.SUPERADMIN,None,'operator:g1',True,True,200),
    (P.ADMIN,None,None,False,True,403),(P.ADMIN,None,None,True,False,403)])
async def test_endpoint_akun_gudang_dan_samaran(pg,contoh,monkeypatch,role,gudang,lihat,aktif,token,kode):
    async with pg() as db:
        u=await db.get(User,contoh['uid']);u.role=role
        u.default_warehouse_id=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==gudang)) if gudang else None
        a=await db.get(Akun,contoh['aid']);a.status='aktif' if aktif else 'nonaktif';await db.commit()
    monkeypatch.setattr(internal.settings,'internal_api_token','token-uji')
    app=FastAPI();app.include_router(internal.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        h={'X-Internal-Token':'token-uji' if token else 'salah','X-Operator-Akun':str(contoh['aid'])}
        if lihat:h['X-Produksi-Lihat']=lihat
        r=await c.get(f'/internal/masuk/tiket/{contoh["tid"]}/detail',headers=h)
        assert r.status_code==kode,r.text
        if kode==200:assert r.headers['cache-control']=='private, no-store' and r.json()['status']=='belum'
    async with pg() as db:assert (await db.get(User,contoh['uid'])).role==role

async def test_kepemilikan_per_catatan_dan_sumber_lain_tidak_tercampur(pg,contoh):
    from app.models import Jasa, Pelanggan
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pemilik catatan kedua');db.add(p);await db.flush()
        j=Jasa(kode='JAS-UJI',pelanggan_id=p.id);db.add(j);await db.flush()
        a=await catat(db,contoh,jenis='BERAS_MASUK',berat=100)
        b=await catat(db,contoh,jenis='BERAS_MASUK',berat=50,suffix='B');b.jasa_id=j.id
        c=await catat(db,contoh,jenis='BERAS_MASUK',berat=999,suffix='C');c.source_type='polishing'
        await db.commit();awal=await sidik(db)
        d=await baca(db,contoh['tid'],await db.get(User,contoh['uid']))
        assert Decimal(d['berat_diterima_kg'])==150 and len(d['catatan'])==2
        assert d['catatan'][0]['pemilik']=='Milik pabrik'
        assert 'Pemilik catatan kedua' in d['catatan'][1]['pemilik']
        assert d['catatan'][1]['jasa_id']==j.id
        assert await sidik(db)==awal

async def test_endpoint_memuat_qc_dan_historis_tanpa_mutasi(pg,contoh,monkeypatch):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    async with pg() as db:
        await catat(db,contoh);await db.commit()
        await catat_qc_gabah(db,user=await db.get(User,contoh['uid']),kode_batch='BATCH-UJI-A',
                            kadar_air_1=14,kadar_air_2=15,biji_hijau='sedikit',densiti='padat',lamur=False,jumlah_sak_lamur=0)
        await db.commit();awal=await sidik(db)
    monkeypatch.setattr(internal.settings,'internal_api_token','token-uji')
    app=FastAPI();app.include_router(internal.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        h={'X-Internal-Token':'token-uji','X-Operator-Akun':str(contoh['aid'])}
        r=await c.get(f'/internal/masuk/tiket/{contoh["tid"]}/detail',headers=h)
        assert r.status_code==200,r.text
        q=r.json()['catatan'][0]['qc'][0]
        assert len(q['putaran'])==1 and q['putaran'][0]['hasil'][0]==['Kadar air 1','14%']
        assert q['putaran'][0]['waktu']
    async with pg() as db:assert await sidik(db)==awal
