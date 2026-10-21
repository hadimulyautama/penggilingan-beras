"""Catatan buatan untuk pembuktian pelanggan campuran; bukan data operasional."""
from datetime import timedelta
from sqlalchemy import select,text


async def buat(pg,pemakai,*,ambil=True):
    from app.models import (User,Warehouse,Silo,Jasa,Pelanggan,PurchaseBatch,DryingLot,
        DryingLotBatch,SiloStorage,MillingProcess,MillingProcessSource,MillingProgressLog,
        PkPurchaseBatch,PkGudang2Intake,FinishedGoodsStock)
    from app.database import now_local
    from app.services.seed import seed_master
    from tests.pg.test_tiket_antrean_produksi import _tiket
    from app.services.transfer import create_internal_transfer
    from app.penggilingan.gudang2 import service as g2,polishing as pol
    from app.penggilingan.inventory import finished_goods as fg
    from app.services import barang_keluar as bk
    await seed_master()
    async with pg() as db:
        wh={g.kode_fungsi:g for g in (await db.scalars(select(Warehouse))).all()}
        for fungsi in ('g1','g2'):
            if fungsi not in wh:
                wh[fungsi]=Warehouse(nama_gudang='Gudang '+fungsi[-1],kode_fungsi=fungsi)
                db.add(wh[fungsi]);await db.flush()
        u=await db.get(User,pemakai.id)
        u.role='superadmin';u.default_warehouse_id=wh['g2'].id
        p=Pelanggan(nama_pelanggan='Catur Uji 392');lain=Pelanggan(nama_pelanggan='Catur Uji 392')
        db.add_all([p,lain]);await db.flush()
        js=[Jasa(kode=f'JAS-392-00{i+1}',pelanggan_id=p.id,status='berjalan') for i in range(3)]
        db.add_all(js);await db.flush()
        silos={}
        for fungsi in ('g1','g2'):
            for nama in ('A','B','C'):
                s=await db.scalar(select(Silo).where(Silo.nama_silo==f'Silo {nama}',Silo.warehouse_id==wh[fungsi].id))
                if s is None:
                    s=Silo(nama_silo=f'Silo {nama}',warehouse_id=wh[fungsi].id,status='kosong')
                    db.add(s);await db.flush()
                silos[fungsi,nama]=s
        kini=now_local()-timedelta(days=1)
        dryer=DryingLot(kode_lot='PGR-392-01',status='selesai',jasa_id=js[0].id,
            waktu_mulai_pengeringan=kini,waktu_selesai_pengeringan=kini+timedelta(hours=4),waktu_selesai_pendinginan=kini+timedelta(hours=5),created_by=u.id)
        db.add(dryer);await db.flush()
        for ix,(jenis,pk) in enumerate([('GABAH_BASAH',3000),('GABAH_KERING',4000)]):
            tid=await _tiket(db,f'TRX-392-{jenis}',jenis,pihak=p.nama_pelanggan)
            await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,jasa_id=:j,berat_barang_kg=6000,netto_timbangan_kg=6000,timbang2_kg=6000 WHERE id=:t'),{'p':p.id,'j':js[ix].id,'t':tid})
            b=PurchaseBatch(kode_batch=f'GB-392-{ix+1}',jasa_id=js[ix].id,kondisi_gabah='basah' if ix==0 else 'kering',
                berat_total_kg=6000,sumber_berat='timbangan',tanggal_pembelian=kini.date(),waktu_pembelian=kini,
                status_batch='digiling',input_by=u.id,timbangan_transaksi_id=tid)
            db.add(b);await db.flush()
            if ix==0:db.add(DryingLotBatch(drying_lot_id=dryer.id,purchase_batch_id=b.id))
            st=SiloStorage(silo_id=silos['g1',chr(65+ix)].id,tipe_masuk='dari_dryer' if ix==0 else 'langsung',
                drying_lot_id=dryer.id if ix==0 else None,purchase_batch_id=None if ix==0 else b.id,
                tanggal_masuk=kini,status='selesai',jasa_id=js[ix].id,input_by=u.id)
            db.add(st);await db.flush()
            m=MillingProcess(kode_proses=f'LOT-392-{ix+1}',silo_id=st.silo_id,status='selesai',jasa_id=js[ix].id,
                berat_gabah_masuk_kg=6000,waktu_mulai=kini+timedelta(hours=6),waktu_selesai=kini+timedelta(hours=7),created_by=u.id)
            db.add(m);await db.flush()
            db.add_all([MillingProcessSource(milling_process_id=m.id,silo_storage_id=st.id,
                    drying_lot_id=dryer.id if ix==0 else None,purchase_batch_id=None if ix==0 else b.id,
                    berat_kg=6000,berat_akhir_kg=0,berat_terpakai_kg=6000),
                MillingProgressLog(milling_process_id=m.id,berat_kumulatif_kg=pk,waktu_update=kini+timedelta(hours=7),input_by=u.id)])
        tid=await _tiket(db,'TRX-392-PK','BERAS_PK',pihak=p.nama_pelanggan)
        await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,jasa_id=:j,berat_barang_kg=5000,netto_timbangan_kg=5000,timbang2_kg=7000 WHERE id=:t'),{'p':p.id,'j':js[2].id,'t':tid})
        pb=PkPurchaseBatch(kode_batch='PKB-392-01',jasa_id=js[2].id,berat_total_kg=5000,sumber_berat='timbangan',
            tanggal_pembelian=kini.date(),waktu_pembelian=kini,input_by=u.id,timbangan_transaksi_id=tid)
        db.add(pb);await db.commit()
        await create_internal_transfer(db,user=u,kode_proses='LOT-392-1',lokasi_tujuan='A',berat=2500)
        await create_internal_transfer(db,user=u,kode_proses='LOT-392-2',lokasi_tujuan='B',berat=3500)
        it=await g2.masukkan_pk_luar(db,user=u,kode=pb.kode_batch,tujuan='ditumpuk')
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.intake.id,nama_silo='C',berat=4000)
        hasil=await pol.mulai_penyosohan(db,user=u,nama_silos=['A','B','C'])
        kode=hasil.proc.kode_proses
        for jenis,n in [('medium',6500),('broken',1000),('menir',200),('bekatul',2000)]:
            await pol.catat_output(db,user=u,kode=kode,jenis=jenis,berat_kumulatif=n)
        for nama in ('A','B','C'):
            await pol.selesai_penyosohan(db,user=u,kode=kode,nama_silo=nama,sisa_kg=0)
        await pol.akhiri_penyosohan(db,user=u,kode=kode)
        recid=None
        from app.models import PackagingMaterial,PackageSize,Brand,PackagingPurchase
        material=await db.scalar(select(PackagingMaterial).where(PackagingMaterial.kode=='biasa'))
        ukuran=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==50))
        brand=await db.scalar(select(Brand).where(Brand.nama=='Polos'))
        db.add(PackagingPurchase(kode='KMS-392-1',packaging_material_id=material.id,package_size_id=ukuran.id,
            brand_id=brand.id,jumlah_lembar=100,pelanggan_id=p.id,tanggal=kini.date(),waktu=kini,input_by=u.id))
        await db.commit()
        if ambil:
            await fg.catat_packing(db,user=u,kode_pol=kode,kategori='beras_putih',grade='medium',brand_nama='Polos',material_kode='biasa',ukuran=50,jumlah_karung=40)
            s=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_id==hasil.proc.id))
            j=hasil.proc.jasa_id
            out=await bk.buat_perintah(db,user=u,jasa_id=j,baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=s.product_sku_id,std_id=s.rice_quality_standard_id,jumlah_karung=40)])
            recid=out.rec.id
            await bk.muat_semua(db,user=u,rec_id=recid)
            await bk.verifikasi(db,user=u,rec_id=recid)
        return dict(pelanggan_id=p.id,lain_id=lain.id,jasa_ids=[j.id for j in js],pol_id=hasil.proc.id,kode_pol=kode,
                    keluar_id=recid,user=u.id,gudang={k:g.id for k,g in wh.items()})
