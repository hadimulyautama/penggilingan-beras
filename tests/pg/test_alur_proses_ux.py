"""Keputusan operasional: silo bebas bukan mesin selesai; hasil nyata boleh dipacking."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from app.models import User, PolishingProcess, PolishingSiloUsage, FinishedGoodsStock
from app.penggilingan.gudang2.polishing import (
    mulai_penyosohan, selesai_penyosohan, akhiri_penyosohan, tambah_silo_penyosohan,
    catat_output, Gudang2Error)
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_pengeringan import pabrik, _lot_selesai
from tests.pg.test_giling_beberapa_silo import silos, _mulai
from tests.pg.test_stok_produk import sosoh
from app.services.penyelesaian_proses import ringkasan_selesai
pytestmark = pytest.mark.asyncio


async def test_pendinginan_ulang_menahan_pindah_dan_menyimpan_waktu(pg,pabrik,monkeypatch):
    from app.web import api
    from app.models import DryingLot, DryingCoolingLog, Silo
    from app.penggilingan.gudang1.services.drying import mulai_pendinginan_ulang, finish_cooling, DryingError
    from app.penggilingan.gudang1.services.silo import masuk_silo, SiloError
    from hmu_core.proses_db import ProsesTerpadu
    kode=await _lot_selesai(pg,pabrik)
    monkeypatch.setattr(api,'_is_g1_operator',AsyncMock(return_value=True))
    async with pg() as db:
        u=await db.get(User,pabrik['user'])
        lot=await db.scalar(select(DryingLot).where(DryingLot.kode_lot==kode))
        dulu=lot.waktu_selesai_pendinginan
        assert kode in {r['value'] for r in await api.drying_done(user=u)}
        await mulai_pendinginan_ulang(db,user=u,kode_lot=kode)
        assert lot.waktu_selesai_pendinginan is None
        assert kode not in {r['value'] for r in await api.drying_done(user=u)}
        assert kode in {r['value'] for r in await api.cooling_active(user=u)}
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==pabrik['g1']))
        nama_silo=silo.nama_silo
        with pytest.raises(SiloError,match='pendinginan'):
            await masuk_silo(db,user=u,nama_silo=nama_silo,kode_lot=kode,kode_batch=None)
        await db.rollback()
    async with pg() as db:
        u=await db.get(User,pabrik['user'])
        lot,_=await finish_cooling(db,user=u,kode_lot=kode)
        assert lot.waktu_selesai_pendinginan>=dulu
        logs=(await db.scalars(select(DryingCoolingLog).where(DryingCoolingLog.drying_lot_id==lot.id))).all()
        assert any(l.waktu==dulu and 'selesai' in (l.catatan or '') for l in logs)
        assert any(l.catatan=='pendinginan ulang dimulai' for l in logs)
        row=await db.scalar(select(ProsesTerpadu).where(ProsesTerpadu.tabel_sumber=='drying_cooling',ProsesTerpadu.id_sumber==str(lot.id)))
        assert row.status=='selesai' and row.metadata_domain['putaran_sebelumnya'][0]['selesai']==dulu.isoformat()
        await masuk_silo(db,user=u,nama_silo=nama_silo,kode_lot=kode,kode_batch=None)
        with pytest.raises(DryingError,match='silo'):
            await mulai_pendinginan_ulang(db,user=u,kode_lot=kode)


async def test_semua_silo_bebas_refill_transit_gabung_ulang_dan_akhir_eksplisit(pg,gudang2):
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo,hitung_stok_silo,get_g2_silo
    from app.services.berjalan import untuk_operator_gudang2
    u=gudang2['user']
    async with pg() as db:
        p=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
        await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=0)
        assert p.status=='proses' and p.waktu_selesai is None
        await catat_output(db,user=u,kode=p.kode_proses,jenis='medium',berat_kumulatif=500)
        kartu=next(x for x in (await untuk_operator_gudang2(db)).berjalan if x.kode==p.kode_proses)
        assert kartu.aksi=='hasil_penyosohan'
        assert 'akhiri_penyosohan' in [x[0] for x in kartu.pilihan]
        pindah=await pindah_tumpukan_ke_silo(db,user=u,intake_id=gudang2['intake_tumpukan'],nama_silo='B',berat=1000)
        assert pindah.ke_proses is None
        silo=await get_g2_silo(db,'B')
        from app.penggilingan.gudang2.service import komposisi_bahan_silo
        komposisi=await komposisi_bahan_silo(db,silo.id)
        assert komposisi['pk']==1000 and sum(komposisi.values())==1000
        await tambah_silo_penyosohan(db,user=u,kode=p.kode_proses,nama_silos=['B'])
        us=(await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==p.id).order_by(PolishingSiloUsage.id))).all()
        assert len(us)==2 and float(us[0].berat_terpakai_kg)==9800
        assert float(us[1].berat_awal_kg)==1000
        assert await hitung_stok_silo(db,silo.id)==1000
        with pytest.raises(Gudang2Error,match='Bebaskan'):
            await akhiri_penyosohan(db,user=u,kode=p.kode_proses)
        await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=0)
        assert sum(float(x.berat_terpakai_kg) for x in us)==10800
        await catat_output(db,user=u,kode=p.kode_proses,jenis='medium',berat_kumulatif=700)
        awal=await ringkasan_selesai(db,jenis='sosoh',kode=p.kode_proses)
        await catat_output(db,user=u,kode=p.kode_proses,jenis='medium',berat_kumulatif=800)
        with pytest.raises(Gudang2Error,match='berubah'):
            await akhiri_penyosohan(db,user=u,kode=p.kode_proses,dasar=awal['dasar'])
        assert p.status=='proses'
        baru=await ringkasan_selesai(db,jenis='sosoh',kode=p.kode_proses)
        await akhiri_penyosohan(db,user=u,kode=p.kode_proses,dasar=baru['dasar'])
        assert p.status=='selesai'
        from app.services.undo import _undo_akhiri_penyosohan
        await _undo_akhiri_penyosohan(db,p.id)
        assert p.status=='proses' and all(x.berat_akhir_kg==0 for x in us)


async def test_sisa_kosong_berbeda_dengan_nol(pg,gudang2):
    u=gudang2['user']
    async with pg() as db:
        p=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
        with pytest.raises(Gudang2Error,match='Isi 0'):
            await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=None)
        us=await db.scalar(select(PolishingSiloUsage))
        assert us.berat_akhir_kg is None
        await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=0)
        assert us.berat_akhir_kg==0 and p.status=='proses'


async def test_giling_ringkasan_semua_silo_hasil_dan_perubahan(pg,silos):
    from app.penggilingan.gudang1.services.milling import log_progress,finish_milling,MillingError,tutup_silo_giling
    p=(await _mulai(pg,silos,['A','B'])).proc
    async with pg() as db:
        u=await db.get(User,silos['user'])
        await log_progress(db,user=u,kode_proses=p.kode_proses,berat_kumulatif=500)
        with pytest.raises(ValueError,match='sisa'):
            await ringkasan_selesai(db,jenis='giling',kode=p.kode_proses,berat_akhir=700)
        await tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='A',sisa_kg=0)
        with pytest.raises(ValueError,match='Silo B'):
            await ringkasan_selesai(db,jenis='giling',kode=p.kode_proses,berat_akhir=700)
        await tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='B',sisa_kg=100)
        awal=await ringkasan_selesai(db,jenis='giling',kode=p.kode_proses,berat_akhir=700)
        assert 'Silo A: sisa 0 kg' in awal['teks'] and 'Silo B: sisa 100 kg' in awal['teks']
        await log_progress(db,user=u,kode_proses=p.kode_proses,berat_kumulatif=600)
        with pytest.raises(MillingError,match='berubah'):
            await finish_milling(db,user=u,kode_proses=p.kode_proses,berat_akhir=700,dasar=awal['dasar'])
        baru=await ringkasan_selesai(db,jenis='giling',kode=p.kode_proses,berat_akhir=700)
        await finish_milling(db,user=u,kode_proses=p.kode_proses,berat_akhir=700,dasar=baru['dasar'])



async def _jadikan_berjalan(pg,sosoh):
    async with pg() as db:
        p=await db.get(PolishingProcess,sosoh['proses_id']);p.status='proses';p.waktu_selesai=None
        await db.commit()


async def test_packing_berjalan_picker_batas_dan_dua_operator(pg,sosoh):
    from app.web.aksi_inventory import beras_belum_dikemas
    from app.penggilingan.inventory.finished_goods import catat_packing,InventoryError
    await _jadikan_berjalan(pg,sosoh)
    async with pg() as db:
        u=await db.get(User,sosoh['user'])
        kedua=User(nama='Operator kedua',role=u.role,status='aktif',default_warehouse_id=u.default_warehouse_id)
        db.add(kedua);await db.commit();uid_kedua=kedua.id
    pilihan=await beras_belum_dikemas(user=u)
    assert any(r['value']==sosoh['kode']+'|medium' and 'berjalan' in r['label'] for r in pilihan)
    async def packing(uid):
        async with pg() as db:
            try:
                await catat_packing(db,user=await db.get(User,uid),kode_pol=sosoh['kode'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=200)
                return 'ok'
            except InventoryError:
                await db.rollback();return 'ditolak'
    assert sorted(await asyncio.gather(packing(sosoh['user']),packing(uid_kedua)))==['ditolak','ok']
    async with pg() as db:
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg))))==5000
        p=await db.get(PolishingProcess,sosoh['proses_id']);assert p.status=='proses'


async def test_packing_mengurangi_bahan_yang_sudah_ke_silo(pg,sosoh):
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_packing,InventoryError
    await _jadikan_berjalan(pg,sosoh)
    async with pg() as db:
        u=await db.get(User,sosoh['user']);u.role='superadmin';await db.commit()
        await masukkan_beras_ke_silo(db,user=u,jenis='medium',nama_silo='B',berat_kg=8000,sumber_stok='curah')
        with pytest.raises(InventoryError,match='tinggal 1.000'):
            await catat_packing(db,user=u,kode_pol=sosoh['kode'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=41)
        await catat_packing(db,user=u,kode_pol=sosoh['kode'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=40)


async def test_packing_berjalan_tetap_memisahkan_jenis_dan_pemilik(pg,sosoh):
    from app.models import Jasa,Pelanggan,PolishingOutputLog
    from app.database import now_local
    from app.penggilingan.inventory.finished_goods import catat_packing,InventoryError
    from app.web.aksi_inventory import beras_belum_dikemas
    await _jadikan_berjalan(pg,sosoh)
    async with pg() as db:
        u=await db.get(User,sosoh['user'])
        pel=Pelanggan(nama_pelanggan='Pemilik Uji');db.add(pel);await db.flush()
        j=Jasa(kode='JAS-UX-01',pelanggan_id=pel.id);db.add(j);await db.flush()
        p=PolishingProcess(kode_proses='POL-UX-JASA',status='proses',waktu_mulai=now_local(),created_by=u.id,jasa_id=j.id)
        db.add(p);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='medium',berat_kg=100,waktu_update=now_local(),input_by=u.id))
        await db.commit()
        with pytest.raises(InventoryError,match='tinggal 100'):
            await catat_packing(db,user=u,kode_pol=p.kode_proses,kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=5)
        with pytest.raises(InventoryError,match='Belum ada hasil'):
            await catat_packing(db,user=u,kode_pol=p.kode_proses,kategori='beras_putih',grade='premium',material_kode='biasa',ukuran=25,jumlah_karung=1)
        await catat_packing(db,user=u,kode_pol=p.kode_proses,kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=4)
        row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_id==p.id))
        assert row.jasa_id==j.id and row.berat_total_kg==100
        await catat_packing(db,user=u,kode_pol=sosoh['kode'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=4)
        rows=(await db.scalars(select(FinishedGoodsStock))).all()
        assert {r.jasa_id for r in rows}=={None,j.id}
    pilihan=await beras_belum_dikemas(user=u)
    assert not any(r['value'].startswith('POL-UX-JASA|') for r in pilihan)
    assert any(r['value'].startswith(sosoh['kode']+'|') for r in pilihan)


async def test_batas_packing_tidak_membulatkan_saldo_ke_atas(pg,sosoh):
    from app.models import PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import catat_packing,InventoryError
    await _jadikan_berjalan(pg,sosoh)
    async with pg() as db:
        log=await db.scalar(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==sosoh['proses_id']))
        log.berat_kg=99.9;await db.commit()
        with pytest.raises(InventoryError,match='tak bisa mengemas'):
            await catat_packing(db,user=await db.get(User,sosoh['user']),kode_pol=sosoh['kode'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=4)
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==0
