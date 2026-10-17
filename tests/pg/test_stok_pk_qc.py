"""Riwayat QC stok mengikuti sumber fisiknya dan menjaga ringkasan kualitas."""
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, delete

from app.models import MillingProcess, MillingQcLog, User, Warehouse
from app.penggilingan.gudang1.services.milling import log_qc_milling
from app.penggilingan.gudang2.service import log_pk_qc
from app.services import stok
from hmu_identitas.peran import OPERATOR, SUPERADMIN
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_stok_g2_per_kode import dunia as dunia_asal

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dunia(pg, dunia_asal):
    # Fixture lama belum memberi fungsi gudang; autentikasi sekarang membaca
    # kode_fungsi, sama seperti master yang dipakai aplikasi sesungguhnya.
    async with pg() as db:
        for fungsi in ('g1', 'g2'):
            gudang = await db.get(Warehouse, dunia_asal[fungsi])
            gudang.kode_fungsi = fungsi
        await db.commit()
    return dunia_asal


async def test_transfer_membawa_semua_qc_dan_angka_kosong_bukan_nol(pg, dunia):
    async with pg() as db:
        user = await db.get(User, dunia['user'].id)
        await log_qc_milling(db, user=user, kode_proses='LOT-KODE-01',
                             kadar_air=14, broken=None, susut=0, kondisi='KS')
        g1 = await stok.riwayat_qc_pk(db, kode='LOT-KODE-01')
        g2 = await stok.riwayat_qc_pk(db, intake_id=dunia['giling_intake_id'])
    assert g1 == g2
    assert [r['nomor'] for r in g1['rows']] == [2, 1]
    assert g1['rows'][0]['ka'] == '14,0%'
    assert g1['rows'][0]['broken'] == '—'
    assert g1['rows'][0]['susut'] == '0,0%'
    # Operator G2 berhak melihat mutu bahan dari G1 melalui detail stoknya.
    async with await _klien(pg, peran=OPERATOR, gudang='Gudang 2') as c:
        for nama, path in [('g1', '/stok/pk/detail?gudang=g1&kode=LOT-KODE-01'),
                           ('transfer', f'/stok/pk/detail?gudang=g2&id={dunia["giling_intake_id"]}')]:
            r = await c.get(path)
            assert r.status_code == 200
            assert 'Nilai kualitas' in r.text and 'Riwayat QC' in r.text
            assert r.text.index('QC 2') < r.text.index('QC 1')
            assert 'data-ponsel="qc"' in r.text
            Path('/tmp/hmu-stok-qc-'+nama+'.html').write_text(r.text)


async def test_pk_luar_menampilkan_satu_hasil_terbaru_dan_catatan_aman(pg, dunia):
    async with pg() as db:
        await log_pk_qc(db, user=await db.get(User, dunia['user'].id),
                        kode='PKB-KODE-01', kadar_air=12.5, broken=0,
                        penyusutan_persen=None, butir_kuning='sedikit',
                        gabah='bersih', merang='banyak',
                        catatan_lab='<b>Catatan panjang</b> '+('ABCDEFGHIJ'*16))
        hasil = await stok.riwayat_qc_pk(db, intake_id=dunia['beli_intake_id'])
    assert hasil['hasil_terbaru_saja']
    assert len(hasil['rows']) == 1
    assert hasil['rows'][0]['ka'] == '12,5%'
    assert 'Merang: Banyak' in hasil['rows'][0]['keterangan']
    async with await _klien(pg, peran=SUPERADMIN) as c:
        r = await c.get(f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}')
        assert r.status_code == 200
        assert 'Perubahan sebelumnya belum disimpan' in r.text
        assert '&lt;b&gt;Catatan panjang&lt;/b&gt;' in r.text
        assert '13,8%' not in r.text
        Path('/tmp/hmu-stok-qc-luar.html').write_text(r.text)


async def test_stok_tanpa_qc_dan_saklar_mutu(pg, dunia):
    from app.services.setelan import set_fitur_mutu
    async with pg() as db:
        proc_id = await db.scalar(select(MillingProcess.id).where(
            MillingProcess.kode_proses == 'LOT-KODE-01'))
        await db.execute(delete(MillingQcLog).where(MillingQcLog.milling_process_id == proc_id))
        await db.commit()
    async with await _klien(pg, peran=SUPERADMIN) as c:
        path = '/stok/pk/detail?gudang=g1&kode=LOT-KODE-01'
        r = await c.get(path)
        assert r.status_code == 200
        assert 'Belum ada pemeriksaan QC untuk stok PK ini.' in r.text
        assert 'Belum ada data QC' in r.text
        async with pg() as db:
            await set_fitur_mutu(db, False, user=await db.get(User, dunia['user'].id))
        r = await c.get(path)
        assert r.status_code == 200
        assert 'Riwayat QC <span>' not in r.text
    async with await _klien(pg, peran=OPERATOR, gudang='Gudang 1') as c:
        assert (await c.get(f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}')).status_code == 404
