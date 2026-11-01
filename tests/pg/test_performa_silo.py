"""Pembacaan banyak silo harus sama dengan hitungan transaksi satu per satu."""
import pytest
from sqlalchemy import select
from app.models import Silo
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_gabung_jasa import dunia
from tests.pg.test_portal_transit import _pk
pytestmark=pytest.mark.asyncio
async def test_saldo_banyak_silo_sama_dengan_jalur_transaksi(pg,dunia):
    await _pk(pg,dunia,silo='C',jid=dunia['jasa1'],code='PKB-PERFORMA-C',lewat_tumpukan=True)
    await _pk(pg,dunia,silo='D',jid=dunia['jasa3'],code='PKB-PERFORMA-D')
    async with pg() as db:
        ids=(await db.scalars(select(Silo.id))).all()
        hasil={}
        for pemilik in ('pabrik','jasa'):
            banyak=await g2._saldo_silo_halaman(db,pemilik)
            for ident in ids:
                assert banyak[ident]==await g2.hitung_stok_silo(db,ident,pemilik=pemilik)
            hasil[pemilik]=banyak
        assert hasil['jasa'][dunia['silo']['C']]==2000
        assert hasil['jasa'][dunia['silo']['D']]==2000
        assert hasil['pabrik'][dunia['silo']['C']]==0
