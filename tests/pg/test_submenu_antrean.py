"""Filter HTTP untuk submenu muat dan penyosohan, termasuk mesin sibuk."""
import pytest

from tests.pg.test_barang_keluar import _perintah, gudang
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio


async def test_muat_hanya_memuat_perintah_keluar(pg, gudang):
    r = await _perintah(pg, gudang)
    async with await _klien(pg, peran="operator", gudang="Gudang 2",
                           lihat="operator:g2") as c:
        muat = await c.get("/aksi?grup=muat")
        sosoh = await c.get("/aksi?grup=penyosohan")
    assert muat.status_code == sosoh.status_code == 200
    assert r.rec.kode in muat.text
    assert "Muat" in muat.text
    assert r.rec.kode not in sosoh.text
    assert "Tidak ada pekerjaan perlu tindakan" in sosoh.text


async def test_silo_tetap_di_tunggu_penyosohan_saat_mesin_sibuk(pg, gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo

    async with await _klien(pg, peran="operator", gudang="Gudang 2",
                           lihat="operator:g2") as c:
        siap = await c.get("/aksi?grup=penyosohan")
        assert siap.status_code == 200
        assert "Silo B" in siap.text and "buka=mulai_penyosohan" in siap.text
        async with pg() as db:
            await pindah_tumpukan_ke_silo(
                db, user=gudang2["user"], intake_id=gudang2["intake_tumpukan"],
                nama_silo="A", berat=2_000)
            await mulai_penyosohan(db, user=gudang2["user"], nama_silos=["B"])
        sibuk = await c.get("/aksi?grup=penyosohan")
        muat = await c.get("/aksi?grup=muat")
    assert sibuk.status_code == muat.status_code == 200
    assert "Status &amp; informasi" in sibuk.text
    assert "Silo A" in sibuk.text
    assert "mesin sosoh sedang dipakai" in sibuk.text
    assert "Silo B" not in sibuk.text
    assert "Silo A" not in muat.text
    assert "Tidak ada pekerjaan perlu tindakan" in muat.text
