"""Riwayat besar dengan kepemilikan nyata, akun staf dan dua pelanggan."""
import importlib.util
import os
from datetime import timedelta
from pathlib import Path
import pytest
from sqlalchemy import insert, select
from tests.pg.test_portal_pelanggan import portal, qc, client
from tests.pg.test_papan_beranda_http import _klien

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(not os.environ.get('HMU_BEBAN_OUT'),reason='Beban besar dijalankan eksplisit')]

async def semai(sesi, portal, n, *, selesai_mutu=False):
    from app.models import (Jasa,PurchaseBatch,MillingProcess,SiloStorage,
        MillingProcessSource,MillingProgressLog,InternalTransfer,Silo,User,MillingQcLog,PurchaseBatchQc)
    from app.database import now_local
    async with sesi() as db:
        assert db.bind.url.host in ('127.0.0.1','localhost') and db.bind.url.database.startswith('uji_')
        silo=await db.scalar(select(Silo.id).order_by(Silo.id))
        user=await db.scalar(select(User.id).order_by(User.id))
        for start in range(0,n,500):
            seq=list(range(start,min(start+500,n)))
            order_ids=list((await db.execute(insert(Jasa).returning(Jasa.id),[
                dict(kode=f'BJ-{i:07}',pelanggan_id=portal.owners[i%2].id,status='selesai') for i in seq])).scalars())
            dates=[now_local()-timedelta(days=i%365+2) for i in seq]
            batches=list((await db.execute(insert(PurchaseBatch).returning(PurchaseBatch.id),[
                dict(kode_batch=f'BG-{i:07}',jasa_id=j,kondisi_gabah='kering',
                    tanggal_pembelian=dt.date(),waktu_pembelian=dt,input_by=user,
                    status_batch='digiling',berat_total_kg=10000,sumber_berat='manual')
                for i,j,dt in zip(seq,order_ids,dates)])).scalars())
            storage=list((await db.execute(insert(SiloStorage).returning(SiloStorage.id),[
                dict(silo_id=silo,purchase_batch_id=b,jasa_id=j,tipe_masuk='gabah_kering',
                    tanggal_masuk=dt,input_by=user,status='digiling')
                for b,j,dt in zip(batches,order_ids,dates)])).scalars())
            mills=list((await db.execute(insert(MillingProcess).returning(MillingProcess.id),[
                dict(kode_proses=f'BM-{i:07}',silo_id=silo,purchase_batch_id=b,jasa_id=j,
                    waktu_mulai=dt,waktu_selesai=dt+timedelta(hours=1),created_by=user,
                    status='selesai',berat_gabah_masuk_kg=10000)
                for i,b,j,dt in zip(seq,batches,order_ids,dates)])).scalars())
            await db.execute(insert(MillingProcessSource),[
                dict(milling_process_id=m,silo_storage_id=s,purchase_batch_id=b,berat_kg=10000,berat_terpakai_kg=10000)
                for m,s,b in zip(mills,storage,batches)])
            await db.execute(insert(MillingProgressLog),[
                dict(milling_process_id=m,berat_kumulatif_kg=6000,waktu_update=dt+timedelta(hours=1),input_by=user)
                for m,dt in zip(mills,dates)])
            await db.execute(insert(InternalTransfer),[
                dict(kode_transfer=f'BT-{i:07}',milling_process_id=m,jasa_id=j,berat_kg=6000,
                    lokasi_tujuan='gudang2',status='terkirim',created_by=user,waktu=dt+timedelta(hours=2))
                for i,m,j,dt in zip(seq,mills,order_ids,dates)])
            if selesai_mutu:
                # Skenario riwayat tahunan: 98% QC telah ditutup; 2%
                # sisanya tetap tugas aktif. Backlog seluruh QC diuji terpisah.
                await db.execute(insert(MillingQcLog),[
                    dict(milling_process_id=m,waktu=dt+timedelta(hours=2),input_by=user,kadar_air=14,broken_persen=20)
                    for i,m,dt in zip(seq,mills,dates) if i%50])
                await db.execute(insert(PurchaseBatchQc),[
                    dict(purchase_batch_id=b,biji_hijau='sedikit',densiti='padat',
                        input_by=user,ditutup_pada=dt+timedelta(hours=2),ditutup_by=user)
                    for i,b,dt in zip(seq,batches,dates) if i%50])
        await db.commit()

async def test_beban(pg,portal):
    n=int(os.environ.get('HMU_BEBAN_N','1000'))
    await semai(pg,portal,n,selesai_mutu=n>=10000)
    mod=importlib.util.spec_from_file_location('beban',os.environ['HMU_BEBAN_HARNESS'])
    harness=importlib.util.module_from_spec(mod);mod.loader.exec_module(harness)
    async with await _klien(pg,role='superadmin') as staff, client(portal.accounts[0]) as a, client(portal.accounts[1]) as b:
        detail='/jasa/pelanggan/'+str(portal.owners[0].id)
        paths=['/','/pekerjaan','/pekerjaan?halaman=2','/stok','/stok?tab=produk','/barang-masuk','/barang-keluar','/laporan','/jasa',detail,detail+'?tab=proses',detail+'?tab=penerimaan','/riwayat-giling/'+str(portal.process[0]['giling'])]
        portalpaths=['/pelanggan/','/pelanggan/barang-saya','/pelanggan/jasa-saya','/pelanggan/riwayat-proses','/pelanggan/riwayat-proses?halaman=5','/pelanggan/barang-masuk','/pelanggan/barang-keluar','/pelanggan/laporan']
        targets=[('staf',staff,p) for p in paths]+[('pelanggan-a',a,p) for p in portalpaths]+[('pelanggan-b',b,'/pelanggan/riwayat-giling/'+str(portal.process[1]['giling']))]
        if os.environ.get('HMU_BEBAN_PATHS'):
            allow=os.environ['HMU_BEBAN_PATHS'].split(',');targets=[t for t in targets if t[2] in allow]
        await harness.ukur(pg,targets,n)
