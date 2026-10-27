"""Audit independen kontrak baca; semua perubahan fixture hanya di DB uji."""
import json
from decimal import Decimal as D
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text, func
from hmu_identitas.model import Akun
from app.database import now_local
from app.models import (ActivityLog, CustomerReturn, CustomerReturnItem,
    FinishedGoodsStock, OutgoingItem, OutgoingRecord, Pelanggan, KirimanKeluar,
    KemasanTara, PackageSize, ProductSku, User)
from app.penggilingan.inventory.models import ReturPemeriksaanLog, ReturRincian
from app.services import retur, retur_detail_timbang as detail
from app.web import internal
from tests.pg.test_retur_pengajuan import asal, simpan, terima

pytestmark = pytest.mark.asyncio

@pytest_asyncio.fixture(autouse=True)
async def presisi_tiket_tf(pg):
    # Rantai PF menyisakan definisi tabel TF historis skala0. Audit batas
    # desimal perlu KG resmi TF: Numeric(14,3), bukan pembulatan fixture lama.
    async with pg() as db:
        for kolom in ('timbang1_kg','timbang2_kg','berat_barang_kg'):
            await db.execute(text(f'ALTER TABLE timbangan_transaksi ALTER COLUMN {kolom} TYPE NUMERIC(14,3)'))
        await db.commit()

async def selesai(pg,asal,kg=250):
    # Helper lama mengikat :kg pada ekspresi integer 9000-:kg sehingga
    # asyncpg dapat menafsirkannya int4. CAST eksplisit menjaga angka uji
    # sesuai penyimpanan Numeric TF tanpa mengubah layanan bisnis.
    async with pg() as db:
        await db.execute(text("""UPDATE timbangan_transaksi SET
            status_tiket='SELESAI',timbang2_kg=9000-CAST(:kg AS NUMERIC),
            berat_barang_kg=CAST(:kg AS NUMERIC) WHERE id=:id"""),
            {'kg':D(str(kg)),'id':asal['tiket'][0]})
        await db.commit()

async def klien(pg, asal, monkeypatch):
    async with pg() as db:
        a=Akun(user_id=asal['uid'], username='audit-kontrak', password_hash='uji', status='aktif')
        db.add(a);await db.commit();aid=a.id
    monkeypatch.setattr(internal.settings,'internal_api_token','audit-token')
    app=FastAPI();app.include_router(internal.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji'),{'X-Internal-Token':'audit-token','X-Operator-Akun':str(aid)}

async def test_endpoint_lama_tetap_token_saja_dan_tara_potongan_nol(pg,asal,monkeypatch):
    await simpan(pg,asal,10)
    async with pg() as db:expected=await retur.baca_muatan(db,asal['tiket'][0])
    c,h=await klien(pg,asal,monkeypatch)
    async with c:
        old=await c.get(f'/internal/retur/tiket/{asal["tiket"][0]}/muatan',headers={'X-Internal-Token':'audit-token'})
        new=await c.get(f'/internal/retur/tiket/{asal["tiket"][0]}/detail',headers=h)
    assert old.status_code==new.status_code==200
    assert old.json()==expected
    assert all(x['tara_per_karung_kg']=='0' for x in old.json()['muatan'])
    assert D(new.json()['pemeriksaan']['toleransi_kg'])==1
    assert new.headers['cache-control']=='private, no-store'

@pytest.mark.parametrize('kg,status,accepted', [('249','diterima_otomatis',True),('251','diterima_otomatis',True),('248.99','perlu_koreksi',False),('251.01','perlu_koreksi',False)])
async def test_selisih_dua_arah_tepat_batas_dan_di_luar(pg,asal,kg,status,accepted):
    r=await simpan(pg,asal,10);await selesai(pg,asal,D(kg));receipt=await terima(pg,r.id)
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        d=await detail.baca(db,asal['tiket'][0]);await db.flush();await db.rollback()
    assert d['status']==status
    assert D(d['pemeriksaan']['selisih_kg'])==D(kg)-250
    assert D(d['pemeriksaan']['toleransi_kg'])==1
    assert bool(receipt)==accepted
    assert (D(d['penerimaan']['berat_stok_kg'])==250) if accepted else d['penerimaan'] is None

@pytest.mark.parametrize('kg',['149.30','150.70'])
async def test_toleransi_kemasan_campuran_dan_stok_utuh(pg,asal,kg):
    async with pg() as db:
        first=await db.get(OutgoingItem,asal['iid']);sku1=await db.get(ProductSku,first.product_sku_id)
        size=PackageSize(ukuran_kg=50,aktif=True);db.add(size);await db.flush()
        sku2=ProductSku(kategori='menir',packaging_material_id=sku1.packaging_material_id,package_size_id=size.id,aktif=True)
        db.add(sku2);await db.flush()
        db.add(KemasanTara(packaging_material_id=sku1.packaging_material_id,package_size_id=size.id,tara_per_karung_kg=D('.25')))
        item2=OutgoingItem(outgoing_record_id=asal['oid'],item_type='finished_goods',product_sku_id=sku2.id,jumlah_karung=4,berat_kg=200)
        db.add(item2);await db.commit();iid2=item2.id
    from app.services import retur_pengajuan as writer
    async with pg() as db:
        rr=await writer.simpan(db,pengiriman_id=asal['oid'],tiket_id=asal['tiket'][0],jumlah={asal['iid']:'2',iid2:'2'},pelaku_id=asal['uid']);await db.commit();rid=rr.id
    await selesai(pg,asal,D(kg));await terima(pg,rid)
    async with pg() as db:d=await detail.baca(db,asal['tiket'][0])
    assert d['status']=='diterima_otomatis'
    assert D(d['pemeriksaan']['toleransi_kg'])==D('.70')
    assert D(d['penerimaan']['berat_stok_kg'])==150
    assert D(d['total_rincian_kg'])==150
    assert {D(x['tara_toleransi_kg']) for x in d['muatan']}=={D('.1'),D('.25')}

async def test_riwayat_selisih_besar_tetap_manual_setelah_koreksi(pg,asal):
    await selesai(pg,asal,250);r=await simpan(pg,asal,9)
    assert await terima(pg,r.id) is None
    r=await simpan(pg,asal,10,pengajuan_id=r.id,alasan='Koreksi jumlah karung nyata.')
    assert await terima(pg,r.id) is None
    async with pg() as db:
        d=await detail.baca(db,asal['tiket'][0]);actor=await db.get(User,asal['uid'])
    assert d['status']=='calon_manual' and d['wajib_manual'] and d['penerimaan'] is None
    assert await terima(pg,r.id,manual=True,pelaku=actor)
    async with pg() as db:d=await detail.baca(db,asal['tiket'][0])
    assert d['status']=='diterima_manual' and D(d['penerimaan']['berat_stok_kg'])==250

@pytest.mark.parametrize('statusfield,value',[('status_transaksi','VOID'),('status_tiket','DITUTUP_PAKSA')])
async def test_snapshot_pending_tiket_tidak_aktif(pg,asal,statusfield,value):
    await simpan(pg,asal,10)
    async with pg() as db:
        await db.execute(text(f'UPDATE timbangan_transaksi SET {statusfield}=:v WHERE id=:id'),{'v':value,'id':asal['tiket'][0]});await db.commit()
        d=await detail.baca(db,asal['tiket'][0])
    assert d['status']=='tiket_tidak_aktif' and d['penerimaan'] is None

async def test_bobot_baru_meminta_pemeriksaan_ulang_tanpa_penerimaan_GET(pg,asal,monkeypatch):
    await simpan(pg,asal,10);await selesai(pg,asal,250)
    def dilarang(*a,**kw):raise AssertionError('GET memanggil jalur tulis retur')
    from app.services import retur_pengajuan,retur_penerimaan
    monkeypatch.setattr(retur_pengajuan,'periksa',dilarang);monkeypatch.setattr(retur_penerimaan,'periksa_dan_terima',dilarang)
    c,h=await klien(pg,asal,monkeypatch)
    models=[CustomerReturn,CustomerReturnItem,FinishedGoodsStock,ReturPemeriksaanLog,ActivityLog]
    async with pg() as db:before=[await db.scalar(select(func.count()).select_from(m)) for m in models]
    async with c:
        for _ in range(3):
            x=await c.get(f'/internal/retur/tiket/{asal["tiket"][0]}/detail',headers=h)
            assert x.status_code==200 and x.json()['status']=='berubah' and x.json()['penerimaan'] is None
    async with pg() as db:assert [await db.scalar(select(func.count()).select_from(m)) for m in models]==before

async def test_tiket_asal_gabungan_memakai_kiriman_bersama(pg,asal):
    await simpan(pg,asal,10)
    async with pg() as db:
        k=KirimanKeluar(timbangan_transaksi_id=asal['tiket'][1],no_polisi='UJI');db.add(k);await db.flush()
        outgoing=await db.get(OutgoingRecord,asal['oid']);outgoing.kiriman_id=k.id;await db.commit()
        d=await detail.baca(db,asal['tiket'][0])
    assert d['asal']['id']==asal['oid'] and d['asal']['kiriman_id']==k.id
    assert d['asal']['tiket_id']==asal['tiket'][1]

@pytest.mark.parametrize('foreign',[False,True])
async def test_historis_receipt_tanpa_pengajuan_tidak_meminjam_item_pelanggan_lain(pg,asal,foreign):
    async with pg() as db:
        item=await db.get(OutgoingItem,asal['iid']);iid=item.id
        if foreign:
            other=Pelanggan(nama_pelanggan='Pelanggan kedua');db.add(other);await db.flush()
            out=OutgoingRecord(kode='OUT-LAIN',pelanggan_id=other.id,tanggal=now_local().date(),waktu=now_local(),input_by=asal['uid'],status='selesai');db.add(out);await db.flush()
            oi=OutgoingItem(outgoing_record_id=out.id,item_type='finished_goods',product_sku_id=item.product_sku_id,jumlah_karung=10,berat_kg=250);db.add(oi);await db.flush();iid=oi.id
        receipt=CustomerReturn(kode='RET-LAMA',timbangan_transaksi_id=asal['tiket'][0],kode_tiket='RTP-UJI-A',pelanggan_id=asal['pid'],berat_tiket_kg=250,berat_rincian_kg=250,selisih_kg=0,input_by=asal['uid'],waktu=now_local());db.add(receipt);await db.flush()
        db.add(CustomerReturnItem(customer_return_id=receipt.id,outgoing_item_id=iid,product_sku_id=item.product_sku_id,jumlah_karung=10,berat_total_kg=250));await db.commit()
        if foreign:
            with pytest.raises(ValueError):await detail.baca(db,asal['tiket'][0])
        else:
            d=await detail.baca(db,asal['tiket'][0]);assert d['status']=='diterima'
            assert d['muatan'][0]['outgoing_item_id']==asal['iid']

async def test_tara_hilang_tidak_dijadikan_nol(pg,asal):
    rr=await simpan(pg,asal,10);await selesai(pg,asal,250)
    async with pg() as db:await db.execute(text('DELETE FROM kemasan_tara'));await db.commit()
    assert await terima(pg,rr.id) is None
    async with pg() as db:d=await detail.baca(db,asal['tiket'][0])
    assert d['status']=='tertahan' and d['pemeriksaan']['toleransi_kg'] is None and d['penerimaan'] is None

async def item_pelanggan_lain(db,asal):
    original=await db.get(OutgoingItem,asal['iid'])
    customer=Pelanggan(nama_pelanggan='Penerima lain');db.add(customer);await db.flush()
    record=OutgoingRecord(kode='OUT-PELANGGAN-LAIN',pelanggan_id=customer.id,
        tanggal=now_local().date(),waktu=now_local(),input_by=asal['uid'],status='selesai')
    db.add(record);await db.flush()
    item=OutgoingItem(outgoing_record_id=record.id,item_type='finished_goods',
        product_sku_id=original.product_sku_id,jumlah_karung=10,berat_kg=250)
    db.add(item);await db.flush();return item

async def test_rincian_historis_tanpa_header_asal_tetap_memeriksa_pelanggan_item(pg,asal):
    r=await simpan(pg,asal,10)
    async with pg() as db:
        foreign=await item_pelanggan_lain(db,asal)
        rr=await db.get(ReturRincian,r.id)
        rr.outgoing_record_id=None
        rr.muatan=[dict(rr.muatan[0],outgoing_item_id=foreign.id)]
        await db.commit()
        with pytest.raises(ValueError):await detail.baca(db,asal['tiket'][0])

async def test_item_receipt_diperiksa_meski_rincian_pengajuan_tersedia(pg,asal):
    r=await simpan(pg,asal,10);await selesai(pg,asal);receipt=await terima(pg,r.id)
    async with pg() as db:
        foreign=await item_pelanggan_lain(db,asal)
        row=await db.scalar(select(CustomerReturnItem).where(CustomerReturnItem.customer_return_id==receipt.id))
        row.outgoing_item_id=foreign.id
        await db.commit()
        with pytest.raises(ValueError):await detail.baca(db,asal['tiket'][0])
