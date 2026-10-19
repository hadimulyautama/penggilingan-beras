"""Snapshot sumber ulang tetap terpisah pada detail aktif dan riwayat."""
import os
from pathlib import Path
import pytest
from tests.pg.test_riwayat_giling import pabrik, _isi_silo, _klien
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_sosoh import _silo_berisi
pytestmark = pytest.mark.asyncio

def simpan(nama, r):
    assert r.status_code == 200
    assert 'class="bahan-silo"' in r.text
    if os.environ.get('UJI_POTRET_RINGKAS'):
        folder = Path('/tmp/pos-kontras340/halaman345')
        folder.mkdir(exist_ok=True)
        (folder / (nama + '.html')).write_text(r.text)

async def test_giling_sumber_ulang_aktif_dan_riwayat(pg, pabrik):
    from app.services.seed import seed_master
    await seed_master()
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling, tutup_silo_giling, tambah_silo_giling, finish_milling, riwayat_giling
    await _isi_silo(pg, pabrik, 3000)
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
        pr = (await start_milling(db, user=u, nama_silo='A')).proc
        await tutup_silo_giling(db, user=u, kode_proses=pr.kode_proses, nama_silo='A', sisa_kg=0)
    await _isi_silo(pg, pabrik, 2000)
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
        await tambah_silo_giling(db, user=u, kode_proses=pr.kode_proses, nama_silo='A')
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        r = await c.get('/proses-aktif/giling/' + pr.kode_proses)
        simpan('aktif-giling', r)
        assert r.text.count('class="bahan-silo__satu"') == 2
        assert 'Belum dicatat' in r.text and 'Tidak dipisahkan' in r.text
    async with pg() as db:
        u = await db.get(User, pabrik['user'])
        await tutup_silo_giling(db, user=u, kode_proses=pr.kode_proses, nama_silo='A', sisa_kg=500)
        await finish_milling(db, user=u, kode_proses=pr.kode_proses, berat_akhir=1000)
        k = (await riwayat_giling(db, process_id=pr.id))[0][0]
        assert len(k.pemakaian_silo) == 2
        assert [dict(x['angka'])['Sisa akhir'] for x in k.pemakaian_silo] == ['0 kg','500 kg']
    async with await _klien(pg, peran='admin') as c:
        simpan('riwayat-giling', await c.get('/riwayat-giling'))
        simpan('detail-giling', await c.get(f'/riwayat-giling/{pr.id}'))

async def test_sosoh_pemakaian_ulang_aktif_dan_riwayat(pg, gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, selesai_penyosohan, tambah_silo_penyosohan, catat_output, akhiri_penyosohan
    u = gudang2['user']
    async with pg() as db:
        pr = (await mulai_penyosohan(db, user=u, nama_silos=['B'])).proc
        await selesai_penyosohan(db, user=u, kode=pr.kode_proses, nama_silo='B', sisa_kg=0)
    await _silo_berisi(pg, 'B', 500, u.id)
    async with pg() as db:
        await tambah_silo_penyosohan(db, user=u, kode=pr.kode_proses, nama_silos=['B'])
    async with await _klien(pg, peran='admin') as c:
        r = await c.get('/proses-aktif/sosoh/' + pr.kode_proses)
        simpan('aktif-sosoh', r)
        assert r.text.count('class="bahan-silo__satu"') == 2
        assert 'Belum dicatat' in r.text
    async with pg() as db:
        await catat_output(db, user=u, kode=pr.kode_proses, jenis='medium', berat_kumulatif=1000)
        await selesai_penyosohan(db, user=u, kode=pr.kode_proses, nama_silo='B', sisa_kg=100)
        await akhiri_penyosohan(db, user=u, kode=pr.kode_proses)
    async with await _klien(pg, peran='admin') as c:
        simpan('riwayat-sosoh', await c.get('/riwayat-sosoh'))
        r = await c.get(f'/riwayat-sosoh/{pr.id}')
        simpan('detail-sosoh',r)
        assert r.text.count('class="bahan-silo__satu"') == 2
        assert '100 kg' in r.text
