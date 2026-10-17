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
                             kadar_air=14, broken=None, susut=0, kondisi='KS',
                             butir_kuning='sedikit',gabah='bersih',merang='banyak')
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
    assert dict(hasil['rows'][0]['kualitatif']) == {
        'Butir kuning': 'Sedikit', 'Gabah': 'Bersih', 'Merang': 'Banyak'}
    async with await _klien(pg, peran=SUPERADMIN) as c:
        r = await c.get(f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}')
        assert r.status_code == 200
        assert 'Perubahan sebelumnya belum disimpan' in r.text
        assert '&lt;b&gt;Catatan panjang&lt;/b&gt;' in r.text
        assert '13,8%' not in r.text
        for label in ['Butir kuning', 'Gabah', 'Merang']:
            assert f'data-label="{label}"' in r.text
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


async def test_isian_fisik_wajib_di_formulir_dan_server_tanpa_menyimpan_sebagian(pg, dunia):
    from sqlalchemy import func
    from app.web import csrf
    from app.penggilingan.gudang2.models import PkPurchaseVerification
    async with await _klien(pg, peran=SUPERADMIN) as c:
        c.headers[csrf.NAMA_HEADER] = c.cookies.get(csrf.NAMA_COOKIE)
        katalog = (await c.get('/api/actions/menu')).json()
        # Kontrak katalog dipakai aksi.js untuk validasi sebelum tombol Simpan.
        aksi = katalog if isinstance(katalog, list) else katalog['actions']
        assert {'qc_giling', 'qc_pk_luar'} <= {x['id'] for x in aksi}
        for item in aksi:
            if item['id'] in ('qc_giling', 'qc_pk_luar'):
                for field in item['fields']:
                    if field['name'] in ('butir_kuning', 'gabah', 'merang'):
                        assert not field.get('optional', False)
        async with pg() as db:
            jumlah_awal = await db.scalar(select(func.count()).select_from(MillingQcLog))
            luar_awal = await db.scalar(select(PkPurchaseVerification))
            ka_awal = luar_awal.kadar_air
        for path, kode in [('/api/actions/qc-giling', {'kode_proses': 'LOT-KODE-01'}),
                           ('/api/actions/qc-pk-luar', {'kode_batch': 'PKB-KODE-01'})]:
            lengkap = {**kode, 'kadar_air': 12, 'butir_kuning': 'bersih',
                       'gabah': 'sedikit', 'merang': 'bersih'}
            for medan in ('butir_kuning', 'gabah', 'merang'):
                for kosong in (None, '', '  ', 'tidak-sah'):
                    r = await c.post(path, json={**lengkap, medan: kosong})
                    assert r.status_code == 400, r.text
                kurang = dict(lengkap)
                kurang.pop(medan)
                assert (await c.post(path, json=kurang)).status_code == 400
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(MillingQcLog)) == jumlah_awal
            assert (await db.scalar(select(PkPurchaseVerification))).kadar_air == ka_awal


async def test_qc_giling_lengkap_terbaca_di_stok_transfer_dan_riwayat(pg, dunia):
    from app.web import csrf
    from app.penggilingan.gudang1.services.milling import qc_rata
    async with await _klien(pg, peran=SUPERADMIN) as c:
        c.headers[csrf.NAMA_HEADER] = c.cookies.get(csrf.NAMA_COOKIE)
        for ka,kuning,gabah,merang in [(14,'bersih','sedikit','bersih'),
                                       (16,'banyak','sedang','sedikit')]:
            r = await c.post('/api/actions/qc-giling', json={
                'kode_proses': 'LOT-KODE-01', 'kadar_air': ka,
                'butir_kuning': kuning, 'gabah': gabah, 'merang': merang,
                'catatan_lab': '<b>Catatan QC giling</b>'})
            assert r.status_code == 200, r.text
            assert 'Gabah' in r.json()['pesan']
        async with pg() as db:
            proc_id = await db.scalar(select(MillingProcess.id).where(
                MillingProcess.kode_proses == 'LOT-KODE-01'))
            rata = await qc_rata(db, proc_id)
            assert rata.n == 3
            assert rata.kadar_air == pytest.approx((13.2+14+16)/3)
            assert rata.broken == 4 and rata.n_broken == 1
            assert rata.butir_kuning == 'banyak' and rata.gabah == 'sedang'
            for kartu in [(await stok.pk_gudang1(db))[0],
                          next(x for x in await stok.pk_gudang2(db)
                               if x.intake_id == dunia['giling_intake_id'])]:
                assert dict(kartu.mutu)['Butir kuning'] == 'Banyak'
                assert dict(kartu.mutu)['Gabah'] == 'Sedang'
                assert dict(kartu.mutu)['Merang'] == 'Sedikit'
        for nama,path in [('g1','/stok/pk/detail?gudang=g1&kode=LOT-KODE-01'),
                          ('transfer',f'/stok/pk/detail?gudang=g2&id={dunia["giling_intake_id"]}')]:
            r = await c.get(path)
            assert r.status_code == 200
            assert 'Catatan lab: &lt;b&gt;Catatan QC giling&lt;/b&gt;' in r.text
            for label in ('Butir kuning', 'Gabah', 'Merang'):
                assert r.text.count(f'data-label="{label}"') == 3
            Path('/tmp/hmu-stok-qc-'+nama+'.html').write_text(r.text)
        r = await c.get('/riwayat-qc/pk-hasil-giling/LOT-KODE-01')
        assert r.status_code == 200
        for nilai in ('Butir kuning', 'Gabah', 'Merang', 'Banyak', 'Sedang', 'Sedikit'):
            assert nilai in r.text
        assert '&lt;b&gt;Catatan QC giling&lt;/b&gt;' in r.text


async def test_log_lama_tetap_belum_dinilai_dan_bisa_mencatat_qc_fisik_saja(pg, dunia):
    from app.database import now_local
    async with pg() as db:
        proc_id = await db.scalar(select(MillingProcess.id).where(
            MillingProcess.kode_proses == 'LOT-KODE-01'))
        db.add(MillingQcLog(milling_process_id=proc_id, kadar_air=15,
                            waktu=now_local(), input_by=dunia['user'].id))
        await db.commit()
        hasil = await stok.riwayat_qc_pk(db, kode='LOT-KODE-01')
        assert set(dict(hasil['rows'][0]['kualitatif']).values()) == {'Belum dinilai'}
        r = await log_qc_milling(db, user=await db.get(User, dunia['user'].id),
                                kode_proses='LOT-KODE-01', kadar_air=None,
                                broken=None, susut=None, kondisi=None,
                                butir_kuning=' SEDIKIT ', gabah='bersih',merang='banyak')
        assert r.rata.kadar_air == pytest.approx((13.2+15)/2)
        assert r.rata.butir_kuning == 'sedikit'
