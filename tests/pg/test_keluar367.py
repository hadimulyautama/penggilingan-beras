"""Pencarian berlaku di SQL sebelum batas halaman; stok tidak berubah."""
import pytest
from datetime import date, timedelta
from tests.pg.test_barang_keluar import gudang, _perintah, _klien, _stok
pytestmark=pytest.mark.asyncio
async def test_filter_daftar_dan_riwayat(pg,gudang):
    from app.services import barang_keluar as bk
    from app.models import OutgoingRecord
    a=await _perintah(pg,gudang,karung=2)
    b=await _perintah(pg,gudang,karung=3)
    async with pg() as db:
        ra=await db.get(OutgoingRecord,a.rec.id);rb=await db.get(OutgoingRecord,b.rec.id)
        ra.nama_pembeli='Pelanggan 100% _uji';ra.no_polisi='AD 1234 UJ'
        rb.nama_pembeli='Pelanggan lain';rb.status='batal'
        await db.commit()
        assert [r.id for r,_ in await bk.daftar(db,pencarian='100% _')]==[ra.id]
        assert [r.id for r,_ in await bk.daftar(db,pencarian='AD 1234')]==[ra.id]
        assert [r.id for r,_ in await bk.daftar(db,pencarian=rb.kode,status=('batal',))]==[rb.id]
        assert not await bk.daftar(db,sejak=date.today()+timedelta(days=2))
    awal=await _stok(pg,gudang)
    c=await _klien(pg,gudang['adm'],'filter367')
    async with c:
        page=await c.get('/barang-keluar',params={'q':'100% _'})
        assert page.status_code==200;assert ra.kode in page.text;assert rb.kode not in page.text
        assert 'Target' in page.text and 'Aktual' in page.text and 'Milik pabrik' in page.text
        page=await c.get('/barang-keluar',params={'status':'batal'})
        assert rb.kode in page.text;assert ra.kode not in page.text
        assert (await c.get('/barang-keluar?sejak=rusak')).status_code==422
    assert await _stok(pg,gudang)==awal
