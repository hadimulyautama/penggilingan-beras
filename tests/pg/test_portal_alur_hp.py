"""Satu pelanggan dengan stok, penerimaan, pengambilan dan semua tahap proses."""
import json
import os
from pathlib import Path
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select
from app.database import now_local
from app.models import (User,Warehouse,Dryer,PurchaseBatch,PkPurchaseBatch,MillingProcess,
    PolishingProcess,PolishingSiloUsage,PolishingOutputLog,CustomerReturn,CustomerReturnItem,Silo,OutgoingItem)
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_portal_transaksi_detail import transaksi  # noqa: F401
from tests.pg.test_portal_catatan import catatan  # noqa: F401

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def alur(pg,portal,catatan):
    from app.penggilingan.gudang1.services import drying
    from app.penggilingan.gudang2.service import _add_intake
    paths={k:'/pelanggan/'+v for k,v in dict(beranda='ringkasan',stok='barang-saya',
        proses='jasa-saya',riwayat='riwayat-proses',masuk='barang-masuk',ambil='barang-keluar',dokumen='laporan').items()}
    async with pg() as db:
        user=await db.get(User,1);order=portal.orders[0]
        mill=await db.get(MillingProcess,portal.process[0]['giling']);mill.status='proses';mill.waktu_selesai=None
        pol=await db.get(PolishingProcess,portal.process[0]['sosoh']);pol.status='proses';pol.waktu_selesai=None
        g2=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2'))
        foreign_silo=Silo(nama_silo='Lokasi privat B',warehouse_id=g2.id,jenis_isi='pk',status='kosong')
        db.add(foreign_silo);await db.flush()
        for item in (await db.scalars(select(OutgoingItem).where(OutgoingItem.jasa_id==portal.orders[1].id))).all():
            item.silo_id=foreign_silo.id
        usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pol.id));usage.berat_akhir_kg=None
        db.add(PolishingOutputLog(polishing_process_id=pol.id,jenis='medium',berat_kg=1000,waktu_update=now_local(),input_by=1))
        pk=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-QC-DETAIL'))
        intake=await _add_intake(db,user=user,sumber_tipe='beli_luar',tujuan='ditumpuk',berat_kg=12000,
            hpp_per_kg=0,tanggal=now_local().date(),jam=None,pk_purchase_batch_id=pk.id,bobot_final=True,jasa_id=order.id)
        paths.update(giling='/pelanggan/proses-aktif/giling/'+mill.kode_proses,
            sosoh='/pelanggan/proses-aktif/sosoh/'+pol.kode_proses,
            pk1='/pelanggan/stok/pk/detail?gudang=g1&kode='+mill.kode_proses,
            pk2='/pelanggan/stok/pk/detail?gudang=g2&id='+str(intake.intake.id),
            produk='/pelanggan/stok-produk-jasa/detail?jenis=medium')
        g1=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1'))
        for n,jenis in enumerate(('pengeringan','pendinginan')):
            dryer=Dryer(nama='Pengering HP '+str(n),warehouse_id=g1.id,kapasitas_kg=50000,status='aktif');db.add(dryer);await db.flush()
            code='GB-HP-'+str(n)
            db.add(PurchaseBatch(kode_batch=code,jasa_id=order.id,berat_total_kg=8000,kondisi_gabah='basah',
                tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=1,status_batch='baru',
                flag_unverified=False,sumber_berat='timbangan'))
            await db.commit()
            await drying.masuk_dryer(db,user=user,kode_batch_list=[code],dryer_id=dryer.id)
            result=await drying.start_drying(db,user=user,dryer_id=dryer.id,target_kadar_air=13)
            await drying.log_moisture(db,user=user,kode_lot=result.lot.kode_lot,sampel=[18]*4,indikator=19)
            await drying.log_moisture(db,user=user,kode_lot=result.lot.kode_lot,sampel=[15.5]*4,indikator=16)
            if jenis=='pendinginan':await drying.finish_drying(db,user=user,kode_lot=result.lot.kode_lot,kadar_air_akhir=13)
            paths[jenis]='/pelanggan/proses-aktif/'+jenis+'/'+result.lot.kode_lot
        retur=CustomerReturn(kode='RET-HP-OWN',timbangan_transaksi_id=900,kode_tiket='RET-HP-TIKET',
            pelanggan_id=portal.owners[0].id,berat_tiket_kg=10,berat_rincian_kg=10,selisih_kg=0,input_by=1,waktu=now_local())
        db.add(retur);await db.flush();db.add(CustomerReturnItem(customer_return_id=retur.id,jasa_id=order.id,jumlah_karung=1,berat_total_kg=10))
        paths['retur']='/pelanggan/retur/'+str(retur.id)
        await db.commit()
    paths.update(qc_gabah='/pelanggan/riwayat-qc/gabah-kering/GB-QC-KERING',
        qc_pk='/pelanggan/riwayat-qc/pk-luar/PKB-QC-DETAIL',
        qc_giling='/pelanggan/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL',
        karung='/pelanggan/stok?tab=karung',stok_bahan='/pelanggan/stok?tab=bahan',stok_produk='/pelanggan/stok?tab=produk',
        batch_kosong='/pelanggan/riwayat-qc/gabah-basah/GB-DETAIL-KOSONG',
        masuk_detail='/pelanggan/barang-masuk/'+str(catatan['masuk']['GABAH_KERING']),
        ambil_detail='/pelanggan/barang-keluar/'+str(catatan['keluar']['selesai']),
        ambil_aktif='/pelanggan/barang-keluar/'+str(catatan['keluar']['dimuat']),
        rekap='/pelanggan/jasa/'+str(order.id)+'/nota')
    return paths


async def test_semua_pintu_alur_hp_tetap_scoped_dan_terbaca(pg,portal,alur):
    out=Path(os.environ.get('BUKTI_PORTAL_ALUR','output/portal-alur-validation'));out.mkdir(parents=True,exist_ok=True)
    paths=dict(alur)
    async with client(portal.accounts[0]) as c:
        for name,path in paths.items():
            r=await c.get(path);assert r.status_code==200,(name,r.text[:200])
            assert 'Rahasia Pelanggan B' not in r.text and 'LOT-CATATAN-RAHASIA' not in r.text
            s=BeautifulSoup(r.text,'html.parser')
            assert len(s.select('main h1'))==1 and len(s.select('#menu-pelanggan'))==1
            assert not s.select('.portal-topbar .portal-menu')
            assert not s.select('main [data-post],main [data-aksi],main dialog')
            if name.startswith('qc_'):
                assert s.select_one('main h1').get_text()=='Pemeriksaan mutu'
                assert not s.select('.qc-summary-actions')
                assert not [d for d in s.select('main dt') if d.get_text(strip=True)=='Kepemilikan']
            (out/(name+'.html')).write_text(r.text)
    (out/'paths.json').write_text(json.dumps(paths))
