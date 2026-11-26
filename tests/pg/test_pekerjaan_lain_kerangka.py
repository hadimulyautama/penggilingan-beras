"""Katalog tidak membaca antrean untuk menyiapkan kerangka atau membuka hak."""
import json
from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_retur_supplier import asal, skema_retur_timbang
from tests.pg.test_retur_supplier_koreksi import keluar_dua
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_ruang_perusahaan import siapkan, aktifkan, konfigurasi
from tests.pg.test_halaman_bertahap import _sidik
from hmu_identitas.ruang_data import pasang_pagar

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,wh', [('admin', None), ('operator', 'g1'), ('operator', 'g2'), ('superadmin', None)])
async def test_katalog_sama_izin_native_tanpa_baca_antrean(pg, lengkap, stok_lengkap, keluar_dua, monkeypatch, role, wh):
    from app.web import layar_pekerjaan
    client = await _klien(pg, role=role, gudang_id=lengkap['gudang'][wh] if wh else None)
    space = await siapkan(pg)
    await aktifkan(pg, space)
    konfigurasi(monkeypatch, space)
    pasang_pagar(pg.kw['bind'], wajib=True)
    async with client:
        before = await _sidik(pg)
        menu = (await client.get('/api/actions/menu')).json()
        expected = {a['id']: a for a in menu if not a['kartu']}
        async def forbidden(*a, **kw):
            raise AssertionError('Kerangka katalog tidak boleh membaca antrean')
        original = layar_pekerjaan.siapkan_daftar_pekerjaan
        monkeypatch.setattr(layar_pekerjaan, 'siapkan_daftar_pekerjaan', forbidden)
        response = await client.get('/riwayat-retur-supplier', headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert response.status_code == 200
        html = BeautifulSoup(response.text, 'html.parser')
        data = json.loads(html.select_one('#padi-pl-kerangka').string)
        assert set(data['frames']) == {'/pekerjaan/catat-lain'}
        proto = BeautifulSoup(''.join(data['potongan'][i] for i in data['frames']['/pekerjaan/catat-lain']), 'html.parser')
        buttons = proto.select('[data-pl-aksi]')
        assert {b['data-pl-aksi'] for b in buttons} == set(expected)
        assert all(b.has_attr('disabled') and b.select_one('.tindakan__nama').text == expected[b['data-pl-aksi']]['label'] for b in buttons)
        assert all(s.text == '—' for s in proto.select('.kontrol-tab__jumlah'))
        assert not proto.select('form[method=post]')
        assert len(data['potongan']) > 0 and len(response.content) < 4*1024*1024
        monkeypatch.setattr(layar_pekerjaan, 'siapkan_daftar_pekerjaan', original)
        cold = await client.get('/pekerjaan/catat-lain', headers={'X-Pindah':'1'})
        assert cold.status_code == 200 and 'data-pl-controller' in cold.text
        # Jalur aksi/deep link existing tidak diambil alih oleh shell katalog.
        legacy = await client.get('/pekerjaan/catat-lain?buka=beli_kemasan', headers={'X-Pindah':'1'}, follow_redirects=False)
        assert legacy.status_code in (200,303)
        if legacy.status_code == 200:
            assert 'data-pl-controller' not in legacy.text and 'data-buka=' in legacy.text
        assert await _sidik(pg) == before


async def test_adapter_tidak_mengubah_mesin_borang_atau_kirim():
    from app.web.pekerjaan_lain_kerangka import aset
    native = (Path(__file__).resolve().parents[2]/'hmu_tampilan/static/aksi.js').read_text()
    engine = aset()['engine']
    marker = '  /* ── Yang sudah ditunjuk kartunya'
    assert engine[engine.index(marker):] == native[native.index(marker):]
    assert engine[:engine.index('  var katalogTujuan')] == native[:native.index('  async function muat() {')]
    assert '"/api/dashboard"' not in engine
