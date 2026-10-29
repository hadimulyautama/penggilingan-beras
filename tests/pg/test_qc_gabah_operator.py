"""Operator G1 memperoleh tugas QC gabah tanpa mendapat izin keputusan Admin."""
import pytest
import pytest_asyncio
from sqlalchemy import select, func

from app.models import PurchaseBatchQcSample, PurchaseBatchQc, ActivityLog, User, SetelanPabrik
from app.services import berjalan
from app.services.seed import seed_master
from tests.pg.test_qc_gabah import _buat_batch, _isi
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


def payload(kondisi):
    data = dict(kode_batch='GB-OP-' + kondisi, **_isi(1))
    if kondisi == 'basah':
        data.update(lamur='tidak', jumlah_sak_lamur=0)
    return data


@pytest_asyncio.fixture
async def gabah(pg, pemakai, pemasok):
    await seed_master()
    for kondisi in ('basah', 'kering'):
        await _buat_batch(pg, pemakai, pemasok, kondisi, 'GB-OP-' + kondisi)


@pytest.mark.parametrize('role,gudang,boleh', [
    ('operator', 'Gudang 1', True), ('operator', 'Gudang 2', False),
    ('admin', None, True), ('superadmin', None, True),
])
async def test_kartu_dan_post_qc_mengikuti_gudang_efektif(pg, gabah, role, gudang, boleh):
    async with await _klien(pg, peran=role, gudang=gudang) as c:
        halaman = await c.get('/pekerjaan?asal=mutu')
        assert halaman.status_code == 200
        for kondisi in ('basah', 'kering'):
            assert ('GB-OP-' + kondisi in halaman.text) == boleh
            r = await c.post('/api/actions/qc-gabah/' + kondisi,
                json=payload(kondisi),
                headers={'X-CSRF-Token': cap_formulir(c)})
            assert r.status_code == (200 if boleh else 403), r.text
        async with pg() as db:
            rows = (await db.scalars(select(PurchaseBatchQcSample))).all()
            assert len(rows) == (2 if boleh else 0)
            if boleh:
                pencatat = await db.get(User, rows[0].input_by)
                assert pencatat.role == role and pencatat.nama == 'Uji ' + role
                assert all(s.input_by == pencatat.id for s in rows)
                daftar = await berjalan.untuk(db, pencatat)
                assert len([k for k in daftar.meja if k.aksi.startswith('qc_gabah_')]) == 2
                assert all('1/5' in k.isi for k in daftar.meja if k.aksi.startswith('qc_gabah_'))
                if role == 'operator':
                    assert not any(k.aksi in ('acc_permintaan_pk', 'tutup_permintaan_pk',
                        'betulkan_bobot_giling', 'qc_pk_luar', 'qc_giling') for k in daftar.meja)


async def test_fitur_mutu_nonaktif_menutup_kartu_dan_post_operator(pg, gabah):
    async with pg() as db:
        db.add(SetelanPabrik(kunci='fitur_mutu', nilai='0'))
        await db.commit()
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        r = await c.get('/pekerjaan?asal=mutu')
        assert r.status_code == 200 and 'GB-OP-basah' not in r.text
        r = await c.post('/api/actions/qc-gabah/basah',
            json=payload('basah'),
            headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == 400 and 'dimatikan' in r.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PurchaseBatchQcSample)) == 0


async def test_operator_tidak_mendapat_izin_admin_atau_aksi_gudang_lain(pg, gabah):
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        for path, data in [('/api/actions/qc-pk-luar', {'kode_batch':'PK-UJI'}),
                           ('/api/actions/tolak-pk-luar', {'timbangan_transaksi_id':999, 'alasan':'Uji'})]:
            r = await c.post(path, json=data, headers={'X-CSRF-Token': cap_formulir(c)})
            assert r.status_code == 403
        menu = (await c.get('/api/actions/menu')).json()
        for aksi in menu:
            if aksi['id'] in ('qc_gabah_basah', 'qc_gabah_kering', 'qc_gabah_tutup'):
                assert aksi['boleh'] is True


async def test_operator_menutup_qc_dengan_alur_dan_audit_yang_sama(pg, gabah):
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        headers = {'X-CSRF-Token': cap_formulir(c)}
        r = await c.post('/api/actions/qc-gabah/basah', json=payload('basah'), headers=headers)
        assert r.status_code == 200, r.text
        halaman = await c.get('/pekerjaan?asal=mutu')
        assert 'qc_gabah_tutup' in halaman.text and 'GB-OP-basah' in halaman.text
        preview = await c.get('/api/actions/pratinjau-tutup-qc?kode_batch=GB-OP-basah')
        assert preview.status_code == 200
        data = dict(kode_batch='GB-OP-basah', dasar=preview.json()['dasar'],
                    alasan='Pemeriksaan selesai; truk sudah habis dibongkar.')
        r = await c.post('/api/actions/tutup-qc-gabah', json=data, headers=headers)
        assert r.status_code == 200, r.text
        halaman = await c.get('/pekerjaan?asal=mutu')
        assert 'GB-OP-basah' not in halaman.text and 'GB-OP-kering' in halaman.text
        async with pg() as db:
            qc = await db.scalar(select(PurchaseBatchQc))
            log = await db.scalar(select(ActivityLog).where(ActivityLog.aksi == 'tutup_qc_gabah'))
            assert qc.ditutup_by == qc.input_by == log.changed_by
            assert log.alasan_perubahan == data['alasan']
        r = await c.post('/api/actions/qc-gabah/basah', json=payload('basah'), headers=headers)
        assert r.status_code == 400 and 'sudah ditutup' in r.text


@pytest.mark.parametrize('role,awal,tujuan,boleh', [
    ('operator', 'Gudang 2', 'operator:g1', True),
    ('operator', 'Gudang 1', 'operator:g2', False),
    ('superadmin', None, 'operator:g2', False),
])
async def test_kartu_dan_post_mengikuti_pergantian_gudang(pg, gabah, role, awal, tujuan, boleh):
    async with await _klien(pg, peran=role, gudang=awal) as c:
        r = await c.post('/lihat-sebagai', data={'peran': tujuan, '_csrf': cap_formulir(c)},
                         follow_redirects=False)
        assert r.status_code == 303, r.text
        r = await c.get('/pekerjaan?asal=mutu')
        assert r.status_code == 200 and ('GB-OP-kering' in r.text) == boleh
        r = await c.post('/api/actions/qc-gabah/kering', json=payload('kering'),
                         headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == (200 if boleh else 403), r.text
