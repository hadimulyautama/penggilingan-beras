"""Kontrak saldo kemasan existing, bukan jalur Packing baru."""
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import select, func, update
from app.models import (User, Supplier, ByproductStock, PolishingOutputLog,
    FinishedGoodsStock, ProductSku, OutgoingItem, OutgoingRecord, BrokenKeSilo, BrokenKarungDibongkar)
from app.services.barang_keluar import buat_perintah, BarisPerintah, tersedia
from app.services.rencana_broken_silo import rincian
from app.services.saldo_broken_silo import karung_bebas
from tests.pg.test_masukkan_broken_silo import sosoh, _curah
from tests.pg.test_broken_silo_saldo_bebas import foto, sidik
from tests.pg.test_barang_keluar import _klien
from tests.pg.kontak import pelanggan_kledo
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('kg,status,bags,opened,free', [
    (1350, 200, 20, 0, 525), (1875, 200, 1, 475, 0), (1900, 400, 20, 0, 1875)])
async def test_perbandingan_native_20_karung_25_satu_dipesan(pg, sosoh, kg, status, bags, opened, free):
    # Resep exact pembanding a88: pembelian kemasan sah, FG historis native,
    # curah1150 + FG500 + raw1750; perintah curah1500 dan SATU karung25.
    from app.penggilingan.inventory.packaging import beli_kemasan, hitung_stok_kemasan
    from tests.pg.packing_historis import siapkan_packing_historis
    async with pg() as db:
        await db.execute(update(PolishingOutputLog).where(
            PolishingOutputLog.polishing_process_id == sosoh['proc_id']).values(berat_kg=3400))
        await db.commit()
    await _curah(pg, sosoh, 1150)
    async with pg() as db:
        await beli_kemasan(db, user=await db.get(User,sosoh['user']),
            material_kode='polos', ukuran=25, jumlah=20)
        await siapkan_packing_historis(db, user=await db.get(User,sosoh['user']),
            kode_pol=sosoh['kode_pol'], kategori='broken', material_kode='polos', ukuran=25, jumlah_karung=20)
        customer=pelanggan_kledo(nama_pelanggan='Penerima sintetis mixed')
        db.add(customer);await db.commit();cid=customer.id
        u=await db.get(User,sosoh['user'])
        await buat_perintah(db,user=u,pelanggan_id=cid,
            baris=[BarisPerintah(tipe='byproduct_curah',jenis='broken',berat_kg=1500)],no_polisi='AD 1234 XY')
        row=await db.scalar(select(FinishedGoodsStock))
        sku_id=row.product_sku_id;std_id=row.rice_quality_standard_id
        await buat_perintah(db,user=u,pelanggan_id=cid,
            baris=[BarisPerintah(tipe='finished_goods',sku_id=sku_id,std_id=std_id,jumlah_karung=1)],no_polisi='AD 2345 XY')
        assert (await tersedia(db,BarisPerintah(tipe='byproduct_curah',jenis='broken')))[0]==1875
        d=await rincian(db,'pemilik|pabrik',kg if status==200 else None,'C')
        assert d['saldo']['total']==1875 and d['saldo']['karung']==19
    async with await _klien(pg,sosoh['user'],'mixed-free-pack') as c:
        before=await sidik(pg)
        payload=dict(proses='pemilik|pabrik',silo='C',berat_kg=kg,kunci_kiriman=uuid4().hex)
        r=await c.post('/api/actions/masukkan-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==status,r.text
        after=await sidik(pg)
        for table in ['outgoing_records','outgoing_items','polishing_output_logs']:
            assert after[table]==before[table]
        if status==400:
            assert after==before and 'Transaksi ini tidak tersimpan' in r.text
        else:
            retry=await c.post('/api/actions/masukkan-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
            assert retry.status_code==200 and retry.json()==r.json() and await sidik(pg)==after
    async with pg() as db:
        assert (await tersedia(db,BarisPerintah(tipe='byproduct_curah',jenis='broken')))[0]==free
        assert await db.scalar(select(func.sum(FinishedGoodsStock.jumlah_karung)))==bags
        assert await db.scalar(select(func.coalesce(func.sum(BrokenKarungDibongkar.berat_kg),0)))==opened
        assert await db.scalar(select(func.coalesce(func.sum(BrokenKeSilo.berat_kg),0)))==(kg if status==200 else 0)
        fg=await db.scalar(select(FinishedGoodsStock));sku=await db.get(ProductSku,fg.product_sku_id)
        assert await hitung_stok_kemasan(db,sku.packaging_material_id,sku.package_size_id,sku.brand_id)==0
        assert int(await db.scalar(select(func.sum(OutgoingItem.jumlah_karung_perintah)).join(OutgoingRecord)
            .where(OutgoingRecord.status=='perintah',OutgoingItem.item_type=='finished_goods')))==1


async def test_pending_karung_dialokasikan_sekali_fifo_lintas_baris(pg,sosoh):
    from tests.pg.packing_historis import siapkan_packing_historis
    from app.penggilingan.inventory.packaging import beli_kemasan
    async with pg() as db:
        await beli_kemasan(db,user=await db.get(User,sosoh['user']),material_kode='polos',ukuran=25,jumlah=20)
        for _ in range(2):
            await siapkan_packing_historis(db,user=await db.get(User,sosoh['user']),
                kode_pol=sosoh['kode_pol'],kategori='broken',material_kode='polos',ukuran=25,jumlah_karung=10)
        rows=(await db.scalars(select(FinishedGoodsStock).order_by(FinishedGoodsStock.waktu,FinishedGoodsStock.id))).all()
        assert len(rows)==2
        customer=pelanggan_kledo(nama_pelanggan='Penerima FIFO sintetis');db.add(customer);await db.commit()
        await buat_perintah(db,user=await db.get(User,sosoh['user']),pelanggan_id=customer.id,
            baris=[BarisPerintah(tipe='finished_goods',sku_id=rows[0].product_sku_id,
                std_id=rows[0].rice_quality_standard_id,jumlah_karung=12)],no_polisi='AD 3456 XY')
        assert [await karung_bebas(db,r) for r in rows]==[0,8]


@pytest.mark.parametrize('spill',[False,True])
async def test_retur_penerimaan_terikat_tidak_dialihkan_ke_hasil_mesin(pg,foto,spill):
    from tests.pg.test_retur_supplier import tiket
    from app.services import retur_supplier as rs
    from tests.pg.test_broken_silo_persiapan_atomik import pesan
    async with pg() as db:
        sup=Supplier(nama_supplier='Pemasok sintetis broken');db.add(sup);await db.flush()
        tid=await tiket(db,sup.id,'BROKEN_MASUK')
        receipt=await db.get(ByproductStock,foto['receipt']);receipt.source_id=tid;await db.commit()
        user=await db.get(User,foto['user']);payload=[dict(kunci=f'broken:{receipt.id}',jumlah='200')]
        check=await rs.periksa(db,tid,user,payload,'Mutu perlu ditinjau','')
        await rs.simpan(db,user=user,tid=tid,jumlah=payload,alasan=check['alasan'],
            catatan='',kunci=uuid4().hex,dasar=check['dasar']);await db.commit()
    if spill:await pesan(pg,foto,1000)
    async with await _klien(pg,foto['user'],'return-source-free') as c:
        before=await sidik(pg)
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',
            silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex),headers={'X-CSRF-Token':cap_formulir(c)})
        after=await sidik(pg)
        if spill:
            assert r.status_code==400 and 'alokasi retur sumber' in r.text,r.text
            assert after==before
        else:
            assert r.status_code==200,r.text
            for table in ['retur_supplier','retur_supplier_items','outgoing_records','outgoing_items','polishing_output_logs']:
                assert before[table]==after[table]
            async with pg() as db:
                assert await db.scalar(select(func.sum(BrokenKeSilo.berat_kg)).where(
                    BrokenKeSilo.byproduct_stock_id==foto['receipt']))==Decimal('450')
