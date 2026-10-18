"""Saldo yang sama tidak dijanjikan ke dua truk atau tercampur antar pemilik."""
import asyncio
import pytest
from sqlalchemy import select
from app.models import User
from app.services import barang_keluar as bk
from tests.pg.test_barang_keluar import gudang,_perintah,_pelanggan
from tests.pg.test_stok_produk_jasa import sosoh_jasa,_packing
pytestmark=pytest.mark.asyncio


async def test_dua_perintah_bersamaan_tidak_memesan_saldo_yang_sama(pg,gudang):
    ids=[await _pelanggan(pg,'Pembeli '+str(i)) for i in range(2)]
    async def simpan(pid):
        async with pg() as db:
            try:
                return await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),
                    pelanggan_id=pid,no_polisi='B 1234 XY',baris=[bk.BarisPerintah(
                        tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=300)])
            except bk.BarangKeluarError as e:
                await db.rollback();return str(e)
    hasil=await asyncio.gather(*(simpan(pid) for pid in ids))
    assert sum(not isinstance(h,str) for h in hasil)==1
    assert any(isinstance(h,str) and 'tinggal' in h for h in hasil)


async def test_barang_berulang_satu_formulir_tidak_melampaui_saldo(pg,gudang):
    pid=await _pelanggan(pg,'Pembeli baris ulang')
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError,match='tinggal'):
            await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=pid,
                no_polisi='B 1234 XY',baris=[bk.BarisPerintah(tipe='finished_goods',
                    sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=240)]*2)


async def test_reservasi_pabrik_tidak_menghabiskan_saldo_pesanan_jasa(pg,sosoh_jasa):
    from app.penggilingan.inventory.models import FinishedGoodsStock
    for kode in ['kode_pabrik','kode_jasa']:
        await _packing(pg,sosoh_jasa,kode_pol=sosoh_jasa[kode],karung=40)
    async with pg() as db:
        u=await db.get(User,sosoh_jasa['user'])
        stok=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.jasa_id.is_(None)))
        b=bk.BarisPerintah(tipe='finished_goods',sku_id=stok.product_sku_id,
            std_id=stok.rice_quality_standard_id,jumlah_karung=40)
        await bk.buat_perintah(db,user=u,pelanggan_id=sosoh_jasa['pelanggan_id'],no_polisi='B 1111 XX',baris=[b])
        await bk.buat_perintah(db,user=u,pelanggan_id=sosoh_jasa['pelanggan_id'],no_polisi='B 2222 XX',
            jasa_id=sosoh_jasa['jasa_id'],baris=[b])
        for jid in [None,sosoh_jasa['jasa_id']]:
            assert await bk._sudah_dipesan(db,sku_id=b.sku_id,std_id=b.std_id,jasa_id=jid)==1000
