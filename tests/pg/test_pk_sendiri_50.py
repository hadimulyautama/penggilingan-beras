"""Keputusan pemilik: PK sendiri otomatis karung50kg, sisa curah.

Transfer tetap satu transaksi kg; pencatatan karung luar dan ikatan dinamis
surat jalan tidak dipakai oleh PK sendiri. Semua data berasal dari fixture.
"""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select, func, text
from tests.pg.test_peristiwa_transfer import pabrik
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
from app.models import (User, Warehouse, MillingProgressLog, InternalTransfer,
    PkGudang2Intake, PkTumpukanToSilo, ProyeksiTransferPk, ProyeksiPindahTumpukanSilo, Peristiwa)
from app.services.transfer import create_internal_transfer, saldo_pk
from app.penggilingan.gudang2 import service as g2
from hmu_identitas import peran as P

pytestmark=pytest.mark.asyncio

async def siapkan(pg,pabrik,berat=6420):
    async with pg() as db:
        log=await db.scalar(select(MillingProgressLog))
        log.berat_kumulatif_kg=berat
        u=await db.get(User,pabrik['user_id'])
        tr=(await create_internal_transfer(db,user=u,kode_proses=pabrik['kode'],lokasi_tujuan='ditumpuk')).transfer
        g=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2'))
        op=User(nama='Operator PK50',role=P.OPERATOR,status='aktif',default_warehouse_id=g.id)
        db.add(op);await db.commit()
        it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id==tr.id))
        return op.id,it.id,tr.id

async def pindah(pg,ids,**kw):
    async with pg() as db:
        u=await db.get(User,ids[0])
        return await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=ids[1],nama_silo='A',**kw)

@pytest.mark.parametrize('kg,n,c',[(6420,128,20),(20,0,20),(50,1,0),(50.005,1,Decimal('.01'))])
async def test_transfer_unit_event_dan_saldo_tetap(pg,pabrik,kg,n,c):
    ids=await siapkan(pg,pabrik,kg)
    async with pg() as db:
        tr=await db.get(InternalTransfer,ids[2]);pr=await db.get(ProyeksiTransferPk,tr.peristiwa_id)
        assert (tr.jumlah_karung,tr.berat_curah_kg)==(n,c)
        assert (pr.jumlah_karung,pr.berat_curah_kg)==(n,c)
        assert tr.jumlah_karung*50+tr.berat_curah_kg==tr.berat_kg
        assert abs(await saldo_pk(db,pabrik['proc_id']))<.01
        assert await db.scalar(select(func.count()).select_from(PkGudang2Intake))==1
        # Proyeksi dapat dibangun ulang tanpa menduplikasi kg atau unit.
        from app.services import peristiwa as e
        await e.bangun_ulang(db);await db.commit()
        pr=await db.get(ProyeksiTransferPk,tr.peristiwa_id)
        assert pr.jumlah_karung==n and pr.berat_curah_kg==c

async def test_pindah_karung_curah_stok_dan_idempoten(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    r=await pindah(pg,ids,jumlah_karung=10,berat_curah_kg=20,kunci_kiriman='karung50-1')
    assert (r.berat_kg,r.sisa_tumpukan_intake,r.jumlah_karung,r.berat_curah_kg)==(520,5900,10,20)
    await pindah(pg,ids,jumlah_karung=10,berat_curah_kg=20,kunci_kiriman='karung50-1')
    async with pg() as db:
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.jumlah_karung is None and m.berat_timbang_kg==520
        assert m.jumlah_karung_50==10 and m.berat_curah_kg==20
        pr=await db.get(ProyeksiPindahTumpukanSilo,m.peristiwa_id)
        assert pr.jumlah_karung_50==10 and pr.berat_curah_kg==20
        silo=await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id)==520
        from app.services.stok import pk_gudang2
        kartu=(await pk_gudang2(db))[0]
        assert kartu.tersedia==5900 and '118 karung × 50 kg + 0 kg curah' in kartu.ringkasan_karung
    await pindah(pg,ids)
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,ids[1])==0
        silo=await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id)==6420

@pytest.mark.parametrize('kwargs,kg', [({'jumlah_karung':1},50),({'berat_curah_kg':20},20),({'jumlah_karung':0,'berat_curah_kg':20},20),({'berat':75.125,'hasil_timbang':True},75.125),({},6420)])
async def test_jalur_karung_curah_kg_dan_kosong_semua(pg,pabrik,kwargs,kg):
    ids=await siapkan(pg,pabrik)
    r=await pindah(pg,ids,**kwargs)
    assert r.berat_kg==kg
    assert r.berat_curah_kg==float(Decimal(str(kg))%50)
    assert r.sisa_tumpukan_intake==6420-kg

@pytest.mark.parametrize('kwargs', [dict(jumlah_karung=129),dict(berat_curah_kg=21),dict(jumlah_karung=0,berat_curah_kg=0),dict(jumlah_karung=-1),dict(jumlah_karung=1.1),dict(berat_curah_kg=float('inf')),dict(berat_curah_kg=-1),dict(jumlah_karung_partai=100),dict(ukuran_karung_kg=80)])
async def test_input_tidak_sah_tidak_mencatat_sebagian(pg,pabrik,kwargs):
    ids=await siapkan(pg,pabrik)
    with pytest.raises(g2.Gudang2Error):await pindah(pg,ids,**kwargs)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==0
        assert await g2._sisa_tumpukan_intake(db,ids[1])==6420

async def test_dua_operator_tidak_menggandakan_sisa(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async def jalan():
        try:return await pindah(pg,ids,jumlah_karung=100)
        except g2.Gudang2Error:return None
    hasil=await asyncio.gather(jalan(),jalan())
    assert sum(h is not None for h in hasil)==1
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,ids[1])==1420
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==1

async def test_http_pratinjau_simpan_dan_hak_akses(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async with await _klien(pg,ids[0],'pk50-http',mode='operator') as c:
        r=await c.get('/api/actions/pratinjau-pk-karung',params={'tumpukan':ids[1],'jumlah_karung':10,'berat_curah_kg':20})
        assert r.status_code==200 and '10 karung × 50 kg + 20 kg curah = 520 kg' in r.json()['teks']
        assert 'jumlah_karung_partai' in r.json()['nonaktif'] and 'berat_curah_kg' not in r.json()['nonaktif']
        r=await c.post('/api/actions/pindah-tumpukan-silo',json=dict(tumpukan=str(ids[1]),silo='A',jumlah_karung=10,berat_curah_kg=20),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        assert '520,0 kg' in r.json()['pesan'] and '118 karung × 50 kg + 0 kg curah' in r.json()['pesan']
    async with pg() as db:
        g1=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1'))
        op=User(nama='Operator G1 PK50',role=P.OPERATOR,status='aktif',default_warehouse_id=g1.id);db.add(op);await db.commit();uid=op.id
    async with await _klien(pg,uid,'pk50-ditolak',mode='operator') as c:
        assert (await c.get('/api/actions/pratinjau-pk-karung',params={'tumpukan':ids[1]})).status_code==403
        r=await c.post('/api/actions/pindah-tumpukan-silo',json=dict(tumpukan=str(ids[1]),silo='A',jumlah_karung=1),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==403,r.text

async def test_data_lama_tidak_diisi_ulang(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        tr=await db.get(InternalTransfer,ids[2]);tr.jumlah_karung=None;tr.berat_curah_kg=None;await db.commit()
        from app.services.detail_transfer import rincian
        d=await rincian(db,catatan=tr)
        assert d['packing']=='Belum tercatat pada data lama'
        assert tr.jumlah_karung is None

async def test_barang_keluar_dipotong_sebelum_menawarkan_karung(pg,pabrik):
    from app.models import OutgoingRecord,OutgoingItem
    from app.database import now_local
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        r=OutgoingRecord(kode='OUT-PK50-01',tanggal=now_local().date(),waktu=now_local(),input_by=ids[0]);db.add(r);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=r.id,item_type='pk_g2',berat_kg=75));await db.commit()
        assert await g2._sisa_tumpukan_intake(db,ids[1])==6345
        from app.services.stok import pk_gudang2
        assert (await pk_gudang2(db))[0].tersedia==6345
    with pytest.raises(g2.Gudang2Error):await pindah(pg,ids,jumlah_karung=127)
    r=await pindah(pg,ids)
    assert r.berat_kg==6345 and r.jumlah_karung==126 and r.berat_curah_kg==45

@pytest.mark.parametrize('baru', [6370,0])
async def test_koreksi_transfer_menyimpan_unit_asal_dan_pengganti(pg,pabrik,baru):
    from app.services.transfer import koreksi_hasil_transfer
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        r=await koreksi_hasil_transfer(db,user=await db.get(User,pabrik['user_id']),transfer_id=ids[2],berat_kg=baru,dasar_kg=6420,alasan='Pemeriksaan ulang berat muatan uji')
        asal=await db.get(InternalTransfer,ids[2])
        assert asal.status=='dibatalkan' and asal.jumlah_karung==128 and asal.berat_curah_kg==20
        if baru:
            assert r.id!=asal.id and r.jumlah_karung==127 and r.berat_curah_kg==20
        else:assert r is None
        assert await saldo_pk(db,pabrik['proc_id'])==6420-baru

async def test_pk_luar_tidak_mendapat_ukuran50_atau_field_curah(pg):
    from tests.pg.test_pk_karung import dunia,batch_baru
    d=await dunia.__wrapped__(pg)
    async with pg() as db:
        u,b,it=await batch_baru(db,d)
        with pytest.raises(g2.Gudang2Error):
            await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',jumlah_karung=1,berat_curah_kg=1)
        r=await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',jumlah_karung=1)
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.jumlah_karung==1 and m.jumlah_karung_50 is None and m.berat_curah_kg is None
        assert abs(r.berat_kg-10140/128)<.000001

async def test_unit50_tetap_kg_saat_ditambahkan_ke_sosoh_berjalan(pg,pabrik):
    from app.penggilingan.gudang2 import polishing as p
    from app.models import PolishingSiloUsage,PolishingOutputLog,FinishedGoodsStock
    ids=await siapkan(pg,pabrik)
    await pindah(pg,ids,jumlah_karung=10)
    async with pg() as db:
        u=await db.get(User,ids[0])
        proc=(await p.mulai_penyosohan(db,user=u,nama_silos=['A'])).proc
        kode=proc.kode_proses;pid=proc.id
        await p.catat_output(db,user=u,kode=kode,jenis='medium',berat_kumulatif=100)
    r=await pindah(pg,ids,jumlah_karung=10,berat_curah_kg=20)
    assert r.ke_proses==kode
    async with pg() as db:
        u=await db.get(User,ids[0]);usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid))
        assert usage.berat_awal_kg==500 and usage.berat_masuk_kg==520
        assert not usage.bobot_karung_dinamis
        assert await db.scalar(select(func.sum(PolishingOutputLog.berat_kg)))==100
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==0
        await p.selesai_penyosohan(db,user=u,kode=kode,nama_silo='A',sisa_kg=20)
        await p.akhiri_penyosohan(db,user=u,kode=kode)
        silo=await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id)==20
        assert await g2._sisa_tumpukan_intake(db,ids[1])==5400

@pytest.mark.parametrize('ulang',[dict(jumlah_karung=10),dict(berat_curah_kg=20),dict(jumlah_karung=10,berat_curah_kg=19),dict(berat=519,hasil_timbang=True)])
async def test_kunci_sama_tidak_menerima_muatan_unit_berbeda(pg,pabrik,ulang):
    ids=await siapkan(pg,pabrik)
    await pindah(pg,ids,jumlah_karung=10,berat_curah_kg=20,kunci_kiriman='unit-sama')
    with pytest.raises(g2.Gudang2Error,match='Kunci kiriman'):
        await pindah(pg,ids,kunci_kiriman='unit-sama',**ulang)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==1
        assert await g2._sisa_tumpukan_intake(db,ids[1])==5900
