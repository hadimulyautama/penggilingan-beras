"""Alokasi/pengaitan nyata pada Postgres loopback; stok tidak pernah ditulis."""
import asyncio
import os
from decimal import Decimal as D
from types import SimpleNamespace
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select,text,func
from app.database import now_local
from app.models import (User,Supplier,Warehouse,ProductSku,PackageSize,PackagingMaterial,
    FinishedGoodsStock,ByproductStock,PkPurchaseBatch,PkGudang2Intake,PurchaseBatch,ActivityLog)
from app.models.retur_supplier import ReturSupplier,ReturSupplierItem
from app.services.seed import seed_master
from app.services import retur_supplier as s
from app.services.retur_supplier_detail import detail,kontrak
from app.services.barang_keluar import _sudah_dipesan
from hmu_identitas import peran as P

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture(scope='session',autouse=True)
async def skema_retur_timbang(_skema_head):
    from sqlalchemy.ext.asyncio import create_async_engine
    engine=create_async_engine(os.environ['UJI_PG_URL'])
    async with engine.begin() as db:
        lebar=await db.scalar(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='timbangan_transaksi' AND column_name='arah'"))
        if lebar<16:
            await db.execute(text('ALTER TABLE timbangan_transaksi ALTER COLUMN arah TYPE varchar(16)'))
    await engine.dispose()


async def tiket(db,supplier,jenis='BERAS_MASUK',arah='MASUK'):
    # Fondasi 0026 PadiFlow masih VARCHAR(10). Instalasi dua aplikasi memakai
    # migrasi retur TeraFlow yang melebarkannya menjadi16, sama dengan fixture
    # retur pelanggan lama. Rantai kedua aplikasi tetap diuji tersendiri.
    return await db.scalar(text('''INSERT INTO timbangan_transaksi
        (kode,tanggal,arah,jenis_kode,cara_timbang,supplier_id,nomor_polisi,timbang1_kg,timbang1_waktu,
         status_tiket,status_transaksi) VALUES(:kode,CURRENT_DATE,:arah,:jenis,'DUA_KALI',:sid,
         'B UJI',5000,NOW(),'TERBUKA','AKTIF') RETURNING id'''),
        dict(kode='UJI-'+uuid4().hex[:14],arah=arah,jenis=jenis,sid=supplier))


@pytest_asyncio.fixture
async def asal(pg):
    await seed_master()
    async with pg() as db:
        u=User(nama='Admin Uji Retur Supplier',role=P.ADMIN,status='aktif');sup=Supplier(nama_supplier='Supplier Uji Asal')
        db.add_all([u,sup]);await db.flush()
        wh=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))
        sku=ProductSku(kategori='beras_putih',aktif=True,
            packaging_material_id=await db.scalar(select(PackagingMaterial.id)),package_size_id=await db.scalar(select(PackageSize.id)))
        db.add(sku);await db.flush()
        tid=await tiket(db,sup.id)
        row=FinishedGoodsStock(product_sku_id=sku.id,source_type='timbangan',source_id=tid,
            jumlah_karung=20,berat_total_kg=D('998'),warehouse_id=wh,input_by=u.id,waktu=now_local())
        db.add(row);await db.flush();await db.commit()
        return dict(tid=tid,uid=u.id,sid=sup.id,fid=row.id,sku=sku.id,wh=wh)


def user(x,role=P.ADMIN,wh=None):
    return SimpleNamespace(id=x['uid'],role=role,default_warehouse_id=wh or x['wh'])


def jumlah(x,n='5'):
    return [dict(kunci='beras:'+str(x['fid']),jumlah=n)]


async def buat(db,x,n='5',key=None):
    data=await s.periksa(db,x['tid'],user(x),jumlah(x,n),'Mutu tidak sesuai','Catatan pengajuan uji')
    return await s.simpan(db,user=user(x),tid=x['tid'],jumlah=jumlah(x,n),alasan=data['alasan'],
        catatan=data['catatan'],kunci=key or uuid4().hex,dasar=data['dasar'])


async def sidik_stok(db):
    return {t:await db.scalar(text(f"SELECT md5(COALESCE(string_agg(row_to_json(x)::text,'' ORDER BY row_to_json(x)::text),'')) FROM {t} x")) for t in
        ['finished_goods_stock','byproduct_stock','purchase_batches','pk_purchase_batches','pk_gudang2_intakes',
         'outgoing_records','outgoing_items','customer_returns','customer_return_items','peristiwa','timbangan_transaksi']}


async def test_bobot_nyata_alokasi_batal_dan_get_tidak_menulis(pg,asal):
    async with pg() as db:
        sebelum=await sidik_stok(db)
        rec=await buat(db,asal);await db.commit()
        assert await db.scalar(select(ReturSupplierItem.bobot_kg))==D('249.50')
        assert D(str(await _sudah_dipesan(db,sku_id=asal['sku'])))==D('249.50')
        _,pilihan=await s.siapkan(db,asal['tid'],user(asal))
        assert pilihan[0]['stok_jumlah']==20 and pilihan[0]['maksimum']==15
        for _ in range(3):
            d=await detail(db,rec.id,user(asal));assert d['hasil_kg'] is None
        assert await sidik_stok(db)==sebelum
        await s.batalkan(db,user=user(asal),identitas=rec.id,alasan='Tidak jadi diajukan');await db.commit()
        assert await _sudah_dipesan(db,sku_id=asal['sku'])==0
        assert await sidik_stok(db)==sebelum
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='retur_supplier'))==2


@pytest.mark.parametrize('n',['0','-1','1.5','NaN','Infinity','21','1.001'])
async def test_jumlah_tidak_sah_ditolak(pg,asal,n):
    async with pg() as db:
        with pytest.raises(ValueError):await s.periksa(db,asal['tid'],user(asal),jumlah(asal,n),'Mutu','')
        assert await db.scalar(select(func.count()).select_from(ReturSupplier))==0


@pytest.mark.parametrize('kasus',['kosong','alasan','asing','ganda'])
async def test_kelengkapan_dan_kepemilikan_sumber(pg,asal,kasus):
    rows=[] if kasus=='kosong' else jumlah(asal)
    if kasus=='asing':rows[0]['kunci']='beras:999999'
    if kasus=='ganda':rows=rows+rows
    async with pg() as db:
        with pytest.raises(ValueError):await s.periksa(db,asal['tid'],user(asal),rows,'   ' if kasus=='alasan' else 'Mutu','')


async def test_retry_tidak_ganda_dan_payload_beda_ditolak(pg,asal):
    key=uuid4().hex
    async with pg() as db:
        rec=await buat(db,asal,key=key);await db.commit()
        again=await buat(db,asal,key=key);await db.commit()
        assert again.id==rec.id
        with pytest.raises(ValueError,match='isian berbeda'):await buat(db,asal,n='4',key=key)
        assert await db.scalar(select(func.count()).select_from(ReturSupplier))==1


async def test_saldo_berubah_meminta_periksa_ulang(pg,asal):
    async with pg() as db:
        data=await s.periksa(db,asal['tid'],user(asal),jumlah(asal),'Mutu','')
        row=await db.get(FinishedGoodsStock,asal['fid']);row.berat_total_kg=D('990');await db.commit()
        with pytest.raises(ValueError,match='berubah'):
            await s.simpan(db,user=user(asal),tid=asal['tid'],jumlah=jumlah(asal),alasan='Mutu',catatan='',kunci=uuid4().hex,dasar=data['dasar'])
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ReturSupplier))==0


async def test_audit_gagal_tidak_menyisakan_sebagian(pg,asal,monkeypatch):
    async def gagal(*a,**kw):raise RuntimeError('Audit sintetis gagal')
    monkeypatch.setattr(s,'log_activity',gagal)
    async with pg() as db:
        with pytest.raises(RuntimeError):await buat(db,asal)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ReturSupplier))==0
        assert await db.scalar(select(func.count()).select_from(ReturSupplierItem))==0


async def test_dua_pengajuan_bersamaan_tidak_melebihi_saldo(pg,asal):
    async def kirim():
        async with pg() as db:
            try:
                r=await buat(db,asal,n='15');await db.commit();return r.id
            except ValueError:
                await db.rollback();return None
    hasil=await asyncio.gather(kirim(),kirim())
    assert sum(x is not None for x in hasil)==1
    async with pg() as db:
        assert await db.scalar(select(func.sum(ReturSupplierItem.jumlah)))==15


async def test_pengaitan_hasil_dan_pembatalan_tiket_tidak_menyelesaikan_retur(pg,asal):
    async with pg() as db:
        rec=await buat(db,asal);await db.commit();before=await sidik_stok(db)
        tid=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.commit()
        await s.hubungkan(db,user=user(asal),identitas=rec.id,tiket_id=tid);await db.commit()
        assert (await kontrak(db,tid,user(asal)))['pengajuan']['id']==rec.id
        assert (await detail(db,rec.id,user(asal)))['hasil_kg'] is None
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5300,berat_barang_kg=300,status_tiket='SELESAI' WHERE id=:id"),{'id':tid});await db.commit()
        d=await detail(db,rec.id,user(asal));assert d['selisih_kg']==D('50.50') and d['rec'].status=='diajukan'
        await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='VOID' WHERE id=:id"),{'id':tid});await db.commit()
        d=await detail(db,rec.id,user(asal));assert d['status_tiket']=='dibatalkan' and d['hasil_kg'] is None
        after=await sidik_stok(db)
        assert all(after[k]==v for k,v in before.items() if k!='timbangan_transaksi')


@pytest.mark.parametrize('kasus',['supplier','arah','jenis','batal'])
async def test_tiket_yang_tidak_sah_ditolak(pg,asal,kasus):
    async with pg() as db:
        rec=await buat(db,asal);await db.commit()
        sup=Supplier(nama_supplier='Supplier Uji Berbeda');db.add(sup);await db.flush()
        tid=await tiket(db,sup.id if kasus=='supplier' else asal['sid'],
            'BERAS_MASUK' if kasus=='jenis' else 'RETUR_SUPPLIER','MASUK' if kasus=='arah' else 'RETUR_KELUAR')
        if kasus=='batal':await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='VOID' WHERE id=:id"),{'id':tid})
        await db.commit()
        with pytest.raises(ValueError):await s.hubungkan(db,user=user(asal),identitas=rec.id,tiket_id=tid)


async def test_role_efektif_dan_gudang_diperiksa_service(pg,asal):
    async with pg() as db:
        with pytest.raises(PermissionError):await s.periksa(db,asal['tid'],user(asal,P.OPERATOR),jumlah(asal),'Mutu','',kunci=True)
        _,opsi=await s.siapkan(db,asal['tid'],user(asal,P.OPERATOR));assert opsi
        g1=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        with pytest.raises(PermissionError):await s.siapkan(db,asal['tid'],user(asal,P.OPERATOR,wh=g1))
        row=await db.get(User,asal['uid']);row.status='nonaktif';await db.commit()
        with pytest.raises(PermissionError):await buat(db,asal)


async def test_pk_998_30_karung_tidak_kehilangan_karung_terakhir(pg,asal):
    async with pg() as db:
        tid=await tiket(db,asal['sid'],'BERAS_PK');now=now_local()
        b=PkPurchaseBatch(kode_batch='PKB-UJI',supplier_id=asal['sid'],berat_total_kg=998,jumlah_karung=30,
            ukuran_karung_kg=50,tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=asal['uid'],
            timbangan_transaksi_id=tid,status_batch='diterima',sumber_berat='timbangan')
        db.add(b);await db.flush()
        db.add(PkGudang2Intake(sumber_tipe='beli_luar',pk_purchase_batch_id=b.id,tujuan='ditumpuk',berat_kg=998,
            tanggal_masuk=now.date(),waktu_masuk=now,input_by=asal['uid']))
        await db.commit()
        _,opsi=await s.siapkan(db,tid,user(asal));assert opsi[0]['maksimum']==30
        payload=[dict(kunci=f'pk:{b.id}',jumlah='1')]
        a=await s.periksa(db,tid,user(asal),payload,'Uji PK','');assert a['total_kg']==D('33.26666667')
        r=await s.simpan(db,user=user(asal),tid=tid,jumlah=payload,alasan='Uji PK',catatan='',kunci=uuid4().hex,dasar=a['dasar']);await db.commit()
        _,opsi=await s.siapkan(db,tid,user(asal));assert opsi[0]['maksimum']==29
        _,opsi=await s.siapkan(db,tid,user(asal),kecuali=r.id);assert opsi[0]['maksimum']==30


async def test_dua_pengajuan_satu_tiket_hanya_satu_terhubung(pg,asal):
    async with pg() as db:
        a=await buat(db,asal);b=await buat(db,asal);tid=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.commit()
    async def tautkan(rid):
        async with pg() as db:
            try:await s.hubungkan(db,user=user(asal),identitas=rid,tiket_id=tid);await db.commit();return True
            except ValueError:await db.rollback();return False
    assert sum(await asyncio.gather(tautkan(a.id),tautkan(b.id)))==1


async def siap_keluar(db,asal,n='5',hasil='249.50'):
    from app.models import KemasanTara
    r=await buat(db,asal,n=n)
    sku=await db.get(ProductSku,asal['sku'])
    tara=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
    if tara:tara.tara_per_karung_kg=D('.1')
    else:db.add(KemasanTara(packaging_material_id=sku.packaging_material_id,package_size_id=sku.package_size_id,tara_per_karung_kg=D('.1')))
    tid=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.flush()
    await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=tid)
    await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5000::numeric+:kg,berat_barang_kg=:kg,status_tiket='SELESAI' WHERE id=:id"),dict(kg=D(hasil),id=tid))
    await db.commit()
    i=await db.scalar(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==r.id))
    return r,i,tid


@pytest.mark.parametrize('beda',['0','.50','-.50','.51','-.51'])
async def test_toleransi_inklusif_dan_tanpa_mutasi_saat_periksa(pg,asal,beda):
    from app.services import retur_supplier_selesai as f
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:
        r,i,tid=await siap_keluar(db,asal,hasil=str(D('249.50')+D(beda)))
        before=await sidik_stok(db)
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        assert D(snap['toleransi_kg'])==D('.5')
        assert snap['status']==('terverifikasi_otomatis' if abs(D(beda))<=D('.5') else 'perlu_koreksi')
        assert await sidik_stok(db)==before
        assert (await hitung_stok_finished_goods(db,asal['sku'],None))['kg']==998


async def test_keluar_sekali_historis_utuh_dan_alokasi_dilepas(pg,asal):
    from app.services import retur_supplier_selesai as f
    from app.models.retur_supplier import ReturSupplierKeluar
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods,sisa_karung_per_sumber
    async with pg() as db:
        r,i,tid=await siap_keluar(db,asal)
        other=await buat(db,asal,n='2');await db.commit()
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        k=await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        assert (await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True)).kode==k.kode
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ReturSupplierKeluar))==1
        row=await db.get(FinishedGoodsStock,asal['fid']);assert row.jumlah_karung==20 and row.berat_total_kg==998
        assert (await hitung_stok_finished_goods(db,asal['sku'],None))==dict(karung=15,kg=748.5)
        assert (await sisa_karung_per_sumber(db,asal['sku'],None,source_type=None))[0][1:]==(15,748.5)
        assert await _sudah_dipesan(db,sku_id=asal['sku'])==float(D('99.80'))
        with pytest.raises(ValueError,match='sudah tercatat'):await s.batalkan(db,user=user(asal),identitas=r.id,alasan='Tidak boleh rollback semu')


async def test_besar_koreksi_aktual_manual_lengket(pg,asal):
    from app.services import retur_supplier_selesai as f
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal,hasil='199.60')
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        assert snap['status']=='perlu_koreksi'
        with pytest.raises(ValueError):await f.manual(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],catatan='Alasan saja',konfirmasi=True)
        with pytest.raises(ValueError,match='alasan'):await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='4')])
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='4')],alasan='Satu karung tidak ikut keluar setelah diperiksa fisik');await db.commit()
        assert snap['status']=='siap_manual' and (await db.get(ReturSupplier,r.id)).wajib_manual
        with pytest.raises(ValueError):await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True)
        await f.manual(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],catatan='Koreksi jumlah aktual sudah diperiksa',konfirmasi=True);await db.commit()
        await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        assert (await db.get(ReturSupplier,r.id)).status=='selesai_gudang'


@pytest.mark.parametrize('perubahan',['saldo','revisi'])
async def test_perubahan_setelah_periksa_tahan_keluar(pg,asal,perubahan):
    from app.services import retur_supplier_selesai as f
    from app.models.retur_supplier import ReturSupplierKeluar
    async with pg() as db:
        r,i,tid=await siap_keluar(db,asal)
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        if perubahan=='saldo':await buat(db,asal,n='2')
        else:await db.execute(text('UPDATE timbangan_transaksi SET updated_at=NOW() WHERE id=:id'),dict(id=tid))
        await db.commit()
        with pytest.raises(ValueError,match='berubah'):await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ReturSupplierKeluar))==0


async def buat_sumber(db,x,jenis,*,kg='998',bags=None):
    now=now_local();t=await tiket(db,x['sid'],{'pk':'BERAS_PK','gabah':'GABAH_KERING','broken':'BROKEN_MASUK','curah':'BERAS_MASUK'}[jenis])
    args=dict(input_by=x['uid'],waktu=now)
    if jenis=='broken':row=ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=t,berat_kg=D(kg),tanggal=now.date(),**args)
    elif jenis=='curah':row=FinishedGoodsStock(product_sku_id=x['sku'],source_type='timbangan',source_id=t,berat_total_kg=D(kg),jumlah_karung=0,curah_kemas_ulang=True,warehouse_id=x['wh'],**args)
    else:
        args=dict(kode_batch='UJI-'+uuid4().hex[:12],supplier_id=x['sid'],berat_total_kg=D(kg),input_by=x['uid'],
            tanggal_pembelian=now.date(),waktu_pembelian=now,timbangan_transaksi_id=t,sumber_berat='timbangan')
        row=PkPurchaseBatch(**args,jumlah_karung=bags,ukuran_karung_kg=50 if bags else None,status_batch='diterima') if jenis=='pk' else PurchaseBatch(**args,kondisi_gabah='kering',status_batch='baru')
    db.add(row);await db.flush()
    if jenis=='pk':db.add(PkGudang2Intake(sumber_tipe='beli_luar',pk_purchase_batch_id=row.id,tujuan='ditumpuk',berat_kg=D(kg),tanggal_masuk=now.date(),waktu_masuk=now,input_by=x['uid']))
    await db.flush()
    key=('beras' if jenis=='curah' else jenis)+':'+str(row.id)
    return t,row,key


@pytest.mark.parametrize('jenis',['gabah','pk','broken','curah'])
async def test_curah_presisi_keluar_tanpa_menimpa_penerimaan(pg,asal,jenis):
    from app.services import retur_supplier_selesai as f
    async with pg() as db:
        tid,row,key=await buat_sumber(db,asal,jenis)
        payload=[dict(kunci=key,jumlah='125.25')]
        check=await s.periksa(db,tid,user(asal),payload,'Uji curah','')
        r=await s.simpan(db,user=user(asal),tid=tid,jumlah=payload,alasan='Uji curah',catatan='',kunci=uuid4().hex,dasar=check['dasar'])
        t=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.flush()
        await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=t)
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5125.25,berat_barang_kg=125.25,status_tiket='SELESAI' WHERE id=:id"),dict(id=t));await db.commit()
        it=await db.scalar(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==r.id))
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=it.id,jumlah='125.25')]);await db.commit()
        assert D(snap['toleransi_kg'])==0 and snap['status']=='terverifikasi_otomatis'
        await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        _,opsi=await s.siapkan(db,tid,user(asal));assert opsi[0]['stok_kg']==D('872.75')
        await db.refresh(row)
        assert (row.berat_kg if jenis=='broken' else row.berat_total_kg)==998
        if jenis=='gabah':
            from app.penggilingan.gudang1.services.bobot import dari_batch
            assert D(str(dari_batch(row).kg))==D('872.75')
        if jenis=='curah':assert await _sudah_dipesan(db,sku_id=asal['sku'])==0


async def test_satu_item_nol_alokasi_seluruhnya_dilepas(pg,asal):
    from app.services import retur_supplier_selesai as f
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:
        r,i,tid=await siap_keluar(db,asal)
        # Tambah satu sumber sah pada penerimaan dan ajukan lewat jalur normal.
        await s.batalkan(db,user=user(asal),identitas=r.id,alasan='Uji ulang beberapa sumber')
        b=FinishedGoodsStock(product_sku_id=asal['sku'],source_type='timbangan',source_id=asal['tid'],jumlah_karung=10,berat_total_kg=499,warehouse_id=asal['wh'],input_by=asal['uid'],waktu=now_local())
        db.add(b);await db.flush()
        p=jumlah(asal)+[dict(kunci=f'beras:{b.id}',jumlah='3')]
        check=await s.periksa(db,asal['tid'],user(asal),p,'Uji banyak barang','')
        r=await s.simpan(db,user=user(asal),tid=asal['tid'],jumlah=p,alasan='Uji banyak barang',catatan='',kunci=uuid4().hex,dasar=check['dasar'])
        tid=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR')
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5249.5,berat_barang_kg=249.5,status_tiket='SELESAI' WHERE id=:id"),dict(id=tid))
        await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=tid);await db.commit()
        items=(await db.scalars(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==r.id).order_by(ReturSupplierItem.id))).all()
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=it.id,jumlah='5' if n==0 else '0') for n,it in enumerate(items)],alasan='Barang kedua tidak ikut keluar');await db.commit()
        await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        assert await _sudah_dipesan(db,sku_id=asal['sku'])==0
        assert (await hitung_stok_finished_goods(db,asal['sku'],None))==dict(karung=25,kg=1247.5)


async def test_keluar_bersamaan_dan_gagal_audit_atomik(pg,asal,monkeypatch):
    from app.services import retur_supplier_selesai as f
    from app.models.retur_supplier import ReturSupplierKeluar
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal)
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
    original=f._audit
    async def gagal(db,rec,user,aksi,*args,**kw):
        if aksi=='retur_supplier_keluar':raise RuntimeError('Audit keluar gagal sintetis')
        return await original(db,rec,user,aksi,*args,**kw)
    monkeypatch.setattr(f,'_audit',gagal)
    async with pg() as db:
        with pytest.raises(RuntimeError):await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ReturSupplierKeluar))==0
    monkeypatch.setattr(f,'_audit',original)
    async def keluar():
        async with pg() as db:
            k=await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit();return k.peristiwa_id
    ids=await asyncio.gather(keluar(),keluar());assert ids[0]==ids[1]
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(ReturSupplierKeluar))==1


async def test_tara_hilang_dan_aktual_semua_nol_ditolak(pg,asal):
    from app.services import retur_supplier_selesai as f
    from app.models import KemasanTara
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal)
        with pytest.raises(ValueError,match='Minimal satu'):await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='0')],alasan='Tidak muat')
        sku=await db.get(ProductSku,asal['sku']);tara=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id));await db.delete(tara);await db.commit()
        with pytest.raises(ValueError,match='Tara'):await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')])


def api_uji(pg,x,*,role=P.ADMIN,portal=False):
    from fastapi import FastAPI,Request
    from app.web import retur_supplier as web,internal
    from app.web.security import butuh_akun
    app=FastAPI();app.include_router(web.router);app.include_router(internal.router)
    async def akun(request:Request):
        if portal:request.state.portal_scope=object()
        request.state.view='meja'
        a=SimpleNamespace(user=user(x,role),nama='Uji Lokal',peran=role,sesi_pendek=False)
        request.state.akun=a
        return a
    app.dependency_overrides[butuh_akun]=akun
    return app


async def test_http_render_awal_dan_tindakan_berizin(pg,asal):
    import httpx
    from app.web import retur_supplier as web
    # Modul diimpor sesudah fixture pg: arahkan referensi sesi yang baru.
    web.SessionLocal=pg
    async with pg() as db:r,i,_=await siap_keluar(db,asal)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_uji(pg,asal)),base_url='http://uji') as c:
        a=await c.get(f'/barang-masuk/{asal["tid"]}/retur-supplier');assert a.status_code==200,a.text
        assert '<option value="">Pilih tiket' not in a.text # Pemilihan tiket tahap berikutnya.
        assert 'name="pilih"' in a.text and ' checked' not in a.text
        b=await c.get(f'/retur-supplier/{r.id}/penyelesaian');assert b.status_code==200,b.text
        assert 'Pemeriksaan bobot' in b.text
        a=await c.post(f'/retur-supplier/{r.id}/penyelesaian/periksa',json=dict(jumlah=[dict(item_id=i.id,jumlah='5')],alasan=''))
        assert a.status_code==200,a.text;snap=a.json()
        a=await c.post(f'/retur-supplier/{r.id}/penyelesaian/keluar',json=dict(dasar=snap['dasar'],konfirmasi=True));assert a.status_code==200,a.text
        a=await c.get(a.json()['alamat']);assert a.status_code==200,a.text
        assert 'Barang keluar sudah tercatat' in a.text and 'bukan merupakan bukti' not in a.text


@pytest.mark.parametrize('aksi',['manual','tiket','batalkan'])
async def test_http_operator_tidak_bisa_memanipulasi_tindakan(pg,asal,aksi):
    import httpx
    from app.web import retur_supplier as web
    web.SessionLocal=pg
    async with pg() as db:r,i,tid=await siap_keluar(db,asal)
    body={'periksa':dict(jumlah=[dict(item_id=i.id,jumlah='5')]),'manual':dict(dasar='x',catatan='x',konfirmasi=True),
        'keluar':dict(dasar='x',konfirmasi=True),'tiket':dict(tiket_id=tid),'batalkan':dict(alasan='x')}[aksi]
    path=f'/retur-supplier/{r.id}/'+('penyelesaian/' if aksi in ('periksa','manual','keluar') else '')+aksi
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_uji(pg,asal,role=P.OPERATOR)),base_url='http://uji') as c:
        a=await c.post(path,json=body);assert a.status_code==403,a.text


async def test_http_portal_ditolak_get_dan_post(pg,asal):
    import httpx
    from app.web import retur_supplier as web
    web.SessionLocal=pg
    async with pg() as db:r,i,_=await siap_keluar(db,asal)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_uji(pg,asal,portal=True)),base_url='http://uji') as c:
        assert (await c.get(f'/retur-supplier/{r.id}/penyelesaian')).status_code==403
        assert (await c.post(f'/retur-supplier/{r.id}/penyelesaian/periksa',json=dict(jumlah=[dict(item_id=i.id,jumlah='5')]))).status_code==403


async def test_http_kontrak_internal_akun_token_gudang(pg,asal,monkeypatch):
    import httpx
    from app.web import internal
    from app.config import settings
    from hmu_identitas.model import Akun
    internal.SessionLocal=pg
    monkeypatch.setattr(settings,'internal_api_token','uji-bukan-rahasia')
    async with pg() as db:
        r,i,tid=await siap_keluar(db,asal)
        u=await db.get(User,asal['uid']);u.default_warehouse_id=asal['wh']
        a=Akun(user_id=u.id,username='uji-retur-api',password_hash='tidak-dipakai',status='aktif');db.add(a);await db.commit();aid=a.id
    headers={'X-Internal-Token':'uji-bukan-rahasia','X-Operator-Akun':str(aid)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_uji(pg,asal)),base_url='http://uji') as c:
        url=f'/internal/retur-supplier/tiket/{tid}/detail'
        a=await c.get(url,headers=headers);assert a.status_code==200,a.text
        assert a.json()['pengajuan']['id']==r.id and a.headers['cache-control']=='private, no-store'
        assert (await c.get(url,headers={**headers,'X-Internal-Token':'salah'})).status_code==403
        assert (await c.get(url,headers={**headers,'X-Produksi-Lihat':'operator:g1'})).status_code==403
        async with pg() as db:
            ac=await db.get(Akun,aid);ac.status='nonaktif';await db.commit()
        assert (await c.get(url,headers=headers)).status_code==403


async def test_operator_mencatat_keluar_gudang_efektif_tetap_admin_manual(pg,asal):
    from app.services import retur_supplier_selesai as f
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal)
        g1=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        with pytest.raises(PermissionError):await f.periksa(db,identitas=r.id,user=user(asal,P.OPERATOR,wh=g1),jumlah=[dict(item_id=i.id,jumlah='5')])
        check=await f.periksa(db,identitas=r.id,user=user(asal,P.OPERATOR),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        with pytest.raises(PermissionError):await f.manual(db,identitas=r.id,user=user(asal,P.OPERATOR),dasar=check['dasar'],catatan='Dilarang operator',konfirmasi=True)
        await f.catat_keluar(db,identitas=r.id,user=user(asal,P.OPERATOR),dasar=check['dasar'],konfirmasi=True);await db.commit()
        assert (await db.get(ReturSupplier,r.id)).status=='selesai_gudang'


async def test_alokasi_dilindungi_muat_lama_dan_kartu_stok(pg,asal):
    from app.services import barang_keluar as bk,retur_supplier_selesai as f
    from app.services.stok import stok_produk
    from app.models import OutgoingRecord,OutgoingItem
    from app.penggilingan.inventory.finished_goods import sisa_karung_per_sumber
    async with pg() as db:
        r,i,tid=await siap_keluar(db,asal)
        ada,_=await bk.tersedia(db,bk.BarisPerintah(tipe='finished_goods',sku_id=asal['sku']),abaikan_pesanan=True)
        assert D(str(ada))==D('748.50')
        # Penjualan lama hanya mengonsumsi bagian bebas, bukan sumber retur.
        now=now_local();out=OutgoingRecord(kode='OUT-UJI-BEBAS',tanggal=now.date(),waktu=now,input_by=asal['uid'],status='selesai');db.add(out);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=out.id,item_type='finished_goods',product_sku_id=asal['sku'],jumlah_karung=15,berat_kg=D('748.50')));await db.commit()
        physical=await sisa_karung_per_sumber(db,asal['sku'],None,source_type=None);assert physical[0][1]==5
        check=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=check['dasar'],konfirmasi=True);await db.commit()
        cards=await stok_produk(db)
        assert all(c.kemasan_stok_kg>=-.001 and c.curah_stok_kg>=-.001 for c in cards)
        assert not await sisa_karung_per_sumber(db,asal['sku'],None,source_type=None)


async def test_undo_sumber_gabah_dan_pk_ditahan_hilir(pg,asal):
    from app.services.undo import _undo_purchase,_undo_pk_intake,UndoError
    async with pg() as db:
        for jenis in ('gabah','pk'):
            tid,row,key=await buat_sumber(db,asal,jenis)
            p=[dict(kunci=key,jumlah='100')];check=await s.periksa(db,tid,user(asal),p,'Uji guard hilir','')
            r=await s.simpan(db,user=user(asal),tid=tid,jumlah=p,alasan='Uji guard hilir',catatan='',kunci=uuid4().hex,dasar=check['dasar']);await db.commit()
            with pytest.raises(UndoError,match='Retur ke Supplier'):
                if jenis=='gabah':await _undo_purchase(db,row.id)
                else:await _undo_pk_intake(db,await db.scalar(select(PkGudang2Intake.id).where(PkGudang2Intake.pk_purchase_batch_id==row.id)))


async def test_aktual_kosong_ditolak_dan_http_saldo_terbaru(pg,asal):
    import httpx
    from app.services import retur_supplier_selesai as f
    from app.web import retur_supplier as web
    web.SessionLocal=pg
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal)
        with pytest.raises(ValueError,match='Gunakan angka 0'):await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah=' ')])
        check=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        await buat(db,asal,n='2');await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_uji(pg,asal)),base_url='http://uji') as c:
        a=await c.post(f'/retur-supplier/{r.id}/penyelesaian/keluar',json=dict(dasar=check['dasar'],konfirmasi=True))
        assert a.status_code==409 and a.json()['opsi'][0]['maksimum']=='18'


async def test_perubahan_tara_dan_catatan_tidak_menghapus_manual(pg,asal):
    from app.services import retur_supplier_selesai as f
    from app.models import KemasanTara
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal,hasil='280')
        await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        sku=await db.get(ProductSku,asal['sku']);kt=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
        kt.tara_per_karung_kg=10;await db.commit()
        check=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')],alasan='Master tara berubah dalam uji sintetis');await db.commit()
        assert check['status']=='perlu_koreksi' and (await db.get(ReturSupplier,r.id)).wajib_manual
        with pytest.raises(ValueError):await f.manual(db,identitas=r.id,user=user(asal),dasar=check['dasar'],catatan='Alasan bukan koreksi kuantitas atau timbang',konfirmasi=True)


async def test_proyeksi_keluar_bisa_dibangun_ulang_tanpa_keluar_kedua(pg,asal):
    from app.services import retur_supplier_selesai as f,peristiwa
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    from app.models.retur_supplier import ReturSupplierKeluar
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal)
        check=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
        k=await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=check['dasar'],konfirmasi=True);await db.commit();eid=k.peristiwa_id
        await peristiwa.bangun_ulang(db)
        assert await db.scalar(select(func.count()).select_from(ReturSupplierKeluar))==1
        assert await db.get(ReturSupplierKeluar,eid)
        assert (await hitung_stok_finished_goods(db,asal['sku'],None))==dict(karung=15,kg=748.5)
        await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='VOID' WHERE id=:id"),dict(id=await db.scalar(select(ReturSupplier.timbangan_transaksi_id).where(ReturSupplier.id==r.id))))
        await db.commit()
        assert (await hitung_stok_finished_goods(db,asal['sku'],None))==dict(karung=15,kg=748.5)


@pytest.mark.parametrize('jenis',['pk','beras'])
async def test_retur_bertahap_998_30_tetap_menyisakan_karung_terakhir(pg,asal,jenis):
    from app.services import retur_supplier_selesai as f
    from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
    from app.penggilingan.gudang2.karung import bobot_per_karung
    from app.models import KemasanTara
    async with pg() as db:
        if jenis=='pk':tid,row,key=await buat_sumber(db,asal,'pk',bags=30)
        else:
            tid=asal['tid'];row=await db.get(FinishedGoodsStock,asal['fid']);row.jumlah_karung=30;key=f'beras:{row.id}'
        await db.commit();weights=[]
        tara=await db.scalar(select(KemasanTara).join(PackageSize).where(PackageSize.ukuran_kg==50))
        assert tara
        for n in (1,1,28):
            p=[dict(kunci=key,jumlah=str(n))];check=await s.periksa(db,tid,user(asal),p,'Uji retur bertahap','')
            r=await s.simpan(db,user=user(asal),tid=tid,jumlah=p,alasan=check['alasan'],catatan='',kunci=uuid4().hex,dasar=check['dasar'])
            rt=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.flush()
            await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=rt)
            hasil=check['total_kg'].quantize(D('.001'))
            await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5000::numeric+:kg,berat_barang_kg=:kg,status_tiket='SELESAI' WHERE id=:id"),dict(kg=hasil,id=rt));await db.commit()
            i=await db.scalar(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==r.id))
            request=dict(item_id=i.id,jumlah=str(n),kemasan_tara_id=tara.id if jenis=='pk' else None)
            snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[request]);await db.commit()
            assert snap['status']=='terverifikasi_otomatis'
            weights.append(D(snap['total_kg']))
            await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
            _,opsi=await s.siapkan(db,tid,user(asal))
            if len(weights)==2:
                assert opsi[0]['maksimum']==28
                await db.refresh(row)
                old=berat_karung_nyata(row,28) if jenis=='beras' else bobot_per_karung(row,jumlah=28)
                assert abs(old-opsi[0]['stok_kg'])<=D('.000001')
        assert abs(sum(weights)-D(998))<=D('.000001')
        assert opsi[0]['stok_jumlah']==0 and opsi[0]['maksimum']==0 and abs(opsi[0]['stok_kg'])<=D('.000001')


@pytest.mark.parametrize('perubahan',['supplier','sku'])
async def test_perubahan_identitas_asal_tidak_diterima_diam_diam(pg,asal,perubahan):
    from app.services import retur_supplier_selesai as f
    async with pg() as db:
        r,i,_=await siap_keluar(db,asal)
        if perubahan=='supplier':
            sup=Supplier(nama_supplier='Supplier Koreksi Uji');db.add(sup);await db.flush()
            await db.execute(text('UPDATE timbangan_transaksi SET supplier_id=:sid WHERE id=:tid'),dict(sid=sup.id,tid=asal['tid']))
        else:
            old=await db.get(ProductSku,asal['sku']);sku=ProductSku(kategori='menir',packaging_material_id=old.packaging_material_id,package_size_id=old.package_size_id,aktif=True);db.add(sku);await db.flush()
            row=await db.get(FinishedGoodsStock,asal['fid']);row.product_sku_id=sku.id
        await db.commit()
        with pytest.raises(ValueError,match='berubah'):await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')])


async def test_detail_barang_masuk_menyediakan_tautan_histori_pengajuan_batal(pg,asal):
    import httpx
    from app.web import retur_supplier as web,layar_pekerjaan as layar
    web.SessionLocal=pg;layar.SessionLocal=pg
    app=api_uji(pg,asal);app.include_router(layar.router)
    async with pg() as db:
        r=await buat(db,asal);await db.commit()
        await s.batalkan(db,user=user(asal),identitas=r.id,alasan='Uji keterbacaan riwayat batal');await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        a=await c.get(f'/barang-masuk/{asal["tid"]}');assert a.status_code==200,a.text
        assert 'Pengajuan Retur ke Supplier terkait' in a.text and f'href="/retur-supplier/{r.id}"' in a.text
