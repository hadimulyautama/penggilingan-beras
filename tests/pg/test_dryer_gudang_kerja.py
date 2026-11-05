"""Gudang kerja berasal dari sesi, sama untuk operator yang saling menggantikan.

Login asli + kuki pilihan gudang + CSRF melewati seluruh jalur HTTP. Memakai
override pengguna akan melewatkan bug pemuatan ulang profil pada saat simpan.
"""
import pytest
from sqlalchemy import select, func

from app.database import now_local
from app.models import (Warehouse, Dryer, User, Supplier, PurchaseBatch,
                        Pelanggan, Jasa, ActivityLog, DryingLot)
from app.services.seed import seed_master
from tests.pg.test_operator_ganti_gudang import _orang, _token, _klien, _gudang_di_db
from tests.pg.test_operator_ganti_gudang import pabrik as pabrik_g2
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def tempat(pg):
    await seed_master()
    async with pg() as db:
        wh = {w.kode_fungsi: w.id for w in await db.scalars(select(Warehouse))}
        dryer = await db.scalar(select(Dryer).where(Dryer.warehouse_id == wh['g1']))
        supplier = Supplier(nama_supplier='Pemasok uji dryer sesi')
        customer = Pelanggan(nama_pelanggan='Pelanggan uji dryer sesi')
        db.add_all([supplier, customer])
        await db.flush()
        order = Jasa(kode='JAS-UJI-DRYER', pelanggan_id=customer.id)
        db.add(order)
        await db.commit()
        return dict(**wh, dryer=dryer.id, supplier=supplier.id, jasa=order.id)


async def batch(pg, w, uid, *, jasa=False, kode='GB-UJI-DRYER-SESI', kg=11243):
    async with pg() as db:
        b = PurchaseBatch(kode_batch=kode, warehouse_id=w['g1'], supplier_id=None if jasa else w['supplier'],
            jasa_id=w['jasa'] if jasa else None, kondisi_gabah='basah',
            berat_total_kg=kg, sumber_berat='timbangan', status_batch='baru',
            flag_unverified=False, tanggal_pembelian=now_local().date(),
            waktu_pembelian=now_local(), input_by=uid)
        db.add(b)
        await db.commit()
        return b.id


@pytest.mark.parametrize('profil', ['g1', 'g2', None])
@pytest.mark.parametrize('jasa', [False, True])
async def test_operator_mana_pun_memasukkan_gabah_di_gudang_kerja(pg, tempat, profil, jasa):
    w = tempat
    stored = w.get(profil)
    aid, uid = await _orang(pg, nama='Operator pengganti', role='operator',
                           username='pengganti', gudang_id=stored)
    bid = await batch(pg, w, uid, jasa=jasa)
    async with _klien(await _token(pg, aid), gudang='g1') as c:
        # Picker menawarkan alat yang juga harus diterima oleh writer.
        menu = (await c.get('/api/actions/menu')).json()
        action = next(a for a in menu if a['id'] == 'pindah_tumpukan')
        choices = next(f for f in action['fields'] if f['name'] == 'tujuan')['options']
        target = f"dryer:{w['dryer']}"
        assert any(o[0] == target for o in choices), choices
        r = await c.post('/api/actions/pindah-tumpukan', json={
            'kode_batch': 'GB-UJI-DRYER-SESI', 'tujuan': target})
        assert r.status_code == 200, r.text
        # Pengulangan bukan penempatan baru.
        repeat = await c.post('/api/actions/pindah-tumpukan', json={
            'kode_batch': 'GB-UJI-DRYER-SESI', 'tujuan': target})
        assert repeat.status_code == 400, repeat.text
    async with pg() as db:
        b = await db.get(PurchaseBatch, bid)
        assert (b.status_batch, b.dryer_id, b.warehouse_id, b.berat_total_kg) == (
            'di_dryer', w['dryer'], w['g1'], 11243)
        assert b.jasa_id == (w['jasa'] if jasa else None)
        logs = list(await db.scalars(select(ActivityLog).where(
            ActivityLog.table_name == 'purchase_batches', ActivityLog.record_id == bid,
            ActivityLog.new_value.like('masuk dryer:%'))))
        assert len(logs) == 1 and logs[0].changed_by == uid
    assert await _gudang_di_db(pg, uid) == stored


@pytest.mark.parametrize('role', ['admin', 'superadmin'])
async def test_admin_tetap_bisa_menempatkan_gabah(pg, tempat, role):
    w = tempat
    aid, uid = await _orang(pg, nama='Pengelola', role=role, username='pengelola', gudang_id=None)
    await batch(pg, w, uid)
    async with _klien(await _token(pg, aid)) as c:
        r = await c.post('/api/actions/pindah-tumpukan', json={
            'kode_batch': 'GB-UJI-DRYER-SESI', 'tujuan': f"dryer:{w['dryer']}"})
        assert r.status_code == 200, r.text


async def test_operator_hanya_menindak_gudang_yang_sedang_dipilih(pg, tempat):
    w = tempat
    aid, uid = await _orang(pg, nama='Operator berpindah', role='operator',
                           username='berpindah', gudang_id=w['g1'])
    bid = await batch(pg, w, uid)
    token = await _token(pg, aid)
    body = {'kode_batch': 'GB-UJI-DRYER-SESI', 'tujuan': f"dryer:{w['dryer']}"}
    async with _klien(token, gudang='g2') as g2, _klien(token, gudang='g1') as g1:
        assert (await g2.post('/api/actions/pindah-tumpukan', json=body)).status_code == 403
        async with pg() as db:
            b = await db.get(PurchaseBatch, bid)
            assert b.status_batch == 'baru' and b.dryer_id is None
        assert (await g1.post('/api/actions/pindah-tumpukan', json=body)).status_code == 200
        assert (await g2.post('/api/actions/mulai-pengeringan', json={'dryer_id': w['dryer']})).status_code == 403
        r = await g1.post('/api/actions/mulai-pengeringan', json={'dryer_id': w['dryer']})
        assert r.status_code == 200, r.text
    assert await _gudang_di_db(pg, uid) == w['g1']


async def test_operator_pengganti_melanjutkan_sampai_selesai_pendinginan(pg, tempat):
    w = tempat
    a, uid = await _orang(pg, nama='Shift pertama', role='operator', username='shift1', gudang_id=w['g2'])
    b, uid2 = await _orang(pg, nama='Shift berikutnya', role='operator', username='shift2', gudang_id=None)
    await batch(pg, w, uid, jasa=True)
    async with _klien(await _token(pg, a), gudang='g1') as c:
        r = await c.post('/api/actions/pindah-tumpukan', json={
            'kode_batch':'GB-UJI-DRYER-SESI', 'tujuan':f"dryer:{w['dryer']}"})
        assert r.status_code == 200, r.text
        r = await c.post('/api/actions/mulai-pengeringan', json={'dryer_id':w['dryer'], 'target_kadar_air':13})
        assert r.status_code == 200, r.text
    async with pg() as db:
        lot = await db.scalar(select(DryingLot))
        kode, lid = lot.kode_lot, lot.id
        assert lot.created_by == uid and lot.jasa_id == w['jasa']
    async with _klien(await _token(pg, b), gudang='g1') as c:
        for path, payload in [
            ('kadar-air', {'kode_lot':kode, 'tes':[18,19], 'indikator':20}),
            ('ubah-target', {'kode_lot':kode, 'target':14}),
            ('selesai-pengeringan', {'kode_lot':kode, 'kadar_air':14}),
            ('selesai-pendinginan', {'kode_lot':kode}),
        ]:
            r = await c.post('/api/actions/'+path, json=payload)
            assert r.status_code == 200, (path, r.text)
    async with pg() as db:
        lot = await db.get(DryingLot, lid)
        assert lot.status == 'selesai' and lot.waktu_selesai_pendinginan is not None
        assert lot.jasa_id == w['jasa'] and lot.target_kadar_air == 14
        assert await db.scalar(select(func.count()).select_from(DryingLot)) == 1
    assert await _gudang_di_db(pg, uid) == w['g2']
    assert await _gudang_di_db(pg, uid2) is None


async def test_pilihan_gudang_eksplisit_dan_tautan_lama_tidak_mereset_tugas(pg, tempat):
    from bs4 import BeautifulSoup
    w = tempat
    aid, uid = await _orang(pg, nama='Operator bebas gudang', role='operator',
                           username='pilihgudang', gudang_id=w['g1'])
    async with _klien(await _token(pg, aid), gudang='g2') as c:
        r = await c.get('/pengaturan/peran')
        assert r.status_code == 200, r.text
        html = BeautifulSoup(r.text, 'html.parser')
        choices = html.select('select[name=peran] option')
        assert {o['value'] for o in choices} == {'operator:g1', 'operator:g2'}
        assert next(o['value'] for o in choices if o.has_attr('selected')) == 'operator:g2'
        assert 'gudang utama' not in html.get_text().lower()
        assert html.select_one('.pita-samar a')['href'] == '/pengaturan/peran'
        for path, body in [('/lihat-sebagai', {'peran':''}), ('/lihat-sebagai/selesai', {})]:
            r = await c.post(path, data={**body, '_csrf':cap_formulir(c)})
            assert r.status_code == 303, r.text
            assert c.cookies.get('produksi_lihat') == 'operator:g2'
            assert (await c.get('/api/me')).json()['default_warehouse_id'] == w['g2']
    assert await _gudang_di_db(pg, uid) == w['g1']


async def test_operator_memilih_gudang_2_lalu_menjalankan_penyosohan(pg, pabrik_g2):
    w = pabrik_g2
    async with _klien(w['token'], gudang='g2') as c:
        r = await c.post('/api/actions/pindah-tumpukan-silo', json={
            'tumpukan':str(w['intake']), 'silo':'A', 'berat_kg':5000})
        assert r.status_code == 200, r.text
        r = await c.post('/api/actions/mulai-penyosohan', json={'silo':'A'})
        assert r.status_code == 200, r.text
        kode = r.json()['kode_proses']
        r = await c.post('/api/actions/hasil-penyosohan', json={
            'kode_proses':kode, 'jenis':'premium', 'berat_kumulatif':3000})
        assert r.status_code == 200, r.text
        # Pindah tugas ke G1 menutup akses untuk menulis proses G2.
        c.cookies.set('produksi_lihat', 'operator:g1')
        from app.web.csrf import NAMA_HEADER
        c.headers[NAMA_HEADER] = cap_formulir(c)
        r = await c.post('/api/actions/hasil-penyosohan', json={
            'kode_proses':kode, 'jenis':'premium', 'berat_kumulatif':3500})
        assert r.status_code == 403, r.text
    from app.models import PolishingOutputLog
    async with pg() as db:
        assert await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))) == 3000
    assert await _gudang_di_db(pg, w['op']) == w['g1']
