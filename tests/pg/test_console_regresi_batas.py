"""Pagination dan batas akun tetap benar setelah jumlah pengguna berubah."""
import pytest
from app.services import console_monitoring as mon
from tests.pg.test_console_monitoring import orang
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

async def test_halaman_pengguna_dibatasi_setelah_filter_dan_perusahaan_lain(pg,orang):
    before=await fakta(pg)
    async with pg() as db:
        current=await mon.daftar_akun(db,company_id=orang['cid'],halaman=999)
        assert current['halaman']==current['halaman_total']
        assert current['pengguna']
        empty=await mon.daftar_akun(db,company_id=orang['cid'],cari='Nama pasti tidak ada',halaman=999)
        assert empty['total']==0 and empty['halaman']==empty['halaman_total']==1
        foreign=await mon.daftar_akun(db,company_id=orang['asing'],halaman=999)
        assert not foreign['cakupan']['tersedia'] and foreign['pengguna']==[] and foreign['halaman']==1
    assert await fakta(pg)==before

async def test_filter_gagal_tidak_disamakan_dengan_otorisasi(pg,orang,monkeypatch):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_console_akses import sesi
    from app.config import settings
    from hmu_identitas import peran as P
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        headers=await sesi(c);before=await fakta(pg)
        r=await c.get(f"/internal/console/perusahaan/{orang['cid']}?halaman_anggota=0",headers=headers)
        assert r.status_code==422
        assert (await c.get('/internal/console/saya',headers=headers)).status_code==200
        foreign=await c.get(f"/internal/console/monitoring/perusahaan/{orang['asing']}/pengguna/staf/{orang['aid']}",headers=headers)
        assert foreign.status_code in (403,404)
        assert (await c.get('/internal/console/saya',headers=headers)).status_code==200
        assert await fakta(pg)==before
