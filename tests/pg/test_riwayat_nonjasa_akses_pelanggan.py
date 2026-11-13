"""Riwayat penjualan dan titipan tetap terpisah; GET tidak membuat mutasi."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select, text

from app.main import app
from app.models import (FinishedGoodsStock, Jasa, OutgoingItem, OutgoingRecord,
                        Pelanggan, ProduksiAkun, User, Warehouse)
from app.models.portal import PortalAccount
from app.services import barang_keluar as bk
from app.web import csrf, security
from app.web.portal.security import COOKIE, issue
from hmu_identitas.model import mode_bawaan
from tests.pg.test_barang_keluar import gudang
from tests.pg.test_koreksi_pengiriman_selesai import request, preview, apply

pytestmark = pytest.mark.asyncio


def client(account, *, portal=False, view=None):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji')
    c.cookies.set(COOKIE if portal else security.NAMA_COOKIE,
                  issue(account) if portal else security.buat_token(account))
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    if view:
        c.cookies.set('produksi_lihat', view)
    return c


def codes(response):
    soup = BeautifulSoup(response.text, 'html.parser')
    return {a.get_text(strip=True) for a in soup.select(
        '[aria-labelledby="judul-riwayat-keluar"] tbody .tabel-standar__kode')}


def audit_text(response):
    return [x.get_text(' ', strip=True) for x in BeautifulSoup(
        response.text, 'html.parser').select('.audit__teks')]


@pytest_asyncio.fixture
async def scenario(pg, gudang):
    async with pg() as db:
        owners = [Pelanggan(nama_pelanggan=f'Pelanggan Uji {x}', kledo_contact_id=9500+i)
                  for i, x in enumerate(('A', 'B', 'Tanpa Data'))]
        db.add_all(owners)
        await db.flush()
        orders = [Jasa(kode=f'JAS-RIWAYAT-UJI-{x}', pelanggan_id=p.id, status='berjalan')
                  for x, p in zip(('A', 'B'), owners)]
        db.add_all(orders)
        await db.flush()
        stock = await db.scalar(select(FinishedGoodsStock))
        stock.jumlah_karung = 200
        stock.berat_total_kg = 5000
        for order in orders:
            db.add(FinishedGoodsStock(product_sku_id=stock.product_sku_id,
                rice_quality_standard_id=stock.rice_quality_standard_id,
                source_type=stock.source_type, source_id=stock.source_id,
                jumlah_karung=100, berat_total_kg=2500, warehouse_id=stock.warehouse_id,
                waktu=stock.waktu, input_by=stock.input_by, jasa_id=order.id))
        wh = dict((await db.execute(select(Warehouse.kode_fungsi, Warehouse.id))).all())
        staff = {}
        for key, role, warehouse in [('super', 'superadmin', None), ('admin', 'admin', None),
                                     ('g1', 'operator', wh['g1']), ('g2', 'operator', wh['g2'])]:
            user = User(nama='Petugas Uji '+key, role=role, status='aktif', default_warehouse_id=warehouse)
            db.add(user)
            await db.flush()
            account = ProduksiAkun(user_id=user.id, username='riwayat-uji-'+key,
                password_hash=security.hash_sandi('rahasia123'), status='aktif',
                mode_perangkat=mode_bawaan('operator' if warehouse else 'admin'))
            db.add(account)
            staff[key] = account
        customers = [PortalAccount(username='riwayat-portal-'+str(i), pelanggan_id=p.id,
            password_hash=security.hash_sandi('rahasia123'), active=True, token_version=1)
            for i, p in enumerate(owners)]
        db.add_all(customers)
        await db.commit()
    records = {}
    for kind in ('nonjasa', 'jasa'):
        for owner in range(2):
            for state in ('selesai', 'batal'):
                bags = 4 + owner * 2 + (4 if kind == 'jasa' else 0)
                async with pg() as db:
                    admin = await db.get(User, gudang['adm'])
                    h = await bk.buat_perintah(db, user=admin, pelanggan_id=owners[owner].id,
                        baris=[bk.BarisPerintah(tipe='finished_goods', sku_id=gudang['sku'],
                            std_id=gudang['std'], jumlah_karung=bags,
                            jasa_id=orders[owner].id if kind == 'jasa' else None)],
                        no_polisi=f'AD {1100+len(records)} UJI')
                    rid, code = h.rec.id, h.rec.kode
                    if state == 'batal':
                        await bk.batalkan(db, user=admin, rec_id=rid,
                            sebab=f'BATAL UJI {kind} pelanggan {owner}')
                    else:
                        await bk.muat_semua(db, user=await db.get(User, gudang['op']), rec_id=rid)
                        await bk.verifikasi(db, user=admin, rec_id=rid)
                if state == 'selesai':
                    req = await request(pg, rid, jumlah=bags-1)
                    _, token = await preview(pg, rid, gudang['adm'], req)
                    await apply(pg, rid, gudang['adm'], req, token)
                records[kind, owner, state] = SimpleNamespace(id=rid, code=code)
    result = SimpleNamespace(owners=owners, orders=orders, customers=customers,
                             staff=staff, records=records, stock=gudang)
    if os.getenv('BUKTI_RIWAYAT_UJI'):
        out = Path(os.environ['BUKTI_RIWAYAT_UJI'])
        out.mkdir(exist_ok=True, parents=True)
        (out/'dataset.json').write_text(json.dumps({
            'records':{'-'.join(map(str,k)):vars(v) for k,v in records.items()},
            'portal_users':[a.username for a in customers],
            'staff_users':{k:a.username for k,a in staff.items()},
            'source':'Data sintetis melalui layanan perintah/muat/verifikasi/batal/koreksi lama.'}, indent=2))
    return result


async def test_nonjasa_default_filter_detail_audit_dan_peran(pg, scenario):
    s = scenario
    normal = {r.code for (kind, owner, state), r in s.records.items() if state == 'selesai'}
    cancelled = {r.code for (kind, owner, state), r in s.records.items() if state == 'batal'}
    for role in ('super', 'admin', 'g1', 'g2'):
        async with client(s.staff[role]) as c:
            page = await c.get('/barang-keluar')
            assert page.status_code == (403 if role == 'g1' else 200)
            if role != 'g1':
                assert codes(page) == normal
                assert codes(await c.get('/barang-keluar?status=batal')) == cancelled
                for state in ('selesai', 'batal'):
                    row = s.records['nonjasa', 0, state]
                    assert (await c.get(f'/barang-keluar/{row.id}')).status_code == 200
            row = s.records['nonjasa', 0, 'batal']
            audit = await c.get('/audit', params={'rentang':'semua', 'cari':row.code})
            assert audit.status_code == (200 if role in ('super', 'admin') else 403)
            if audit.status_code == 200:
                assert len(audit_text(audit)) == 2
                assert any('dibatalkan' in x for x in audit_text(audit))
    async with client(s.staff['super']) as c:
        for view, allowed in [('admin', True), ('operator:g1', False), ('operator:g2', False)]:
            c.cookies.set('produksi_lihat', view)
            assert (await c.get('/audit?rentang=semua')).status_code == (200 if allowed else 403)


@pytest.mark.parametrize('owner', [0, 1, 2])
async def test_portal_daftar_filter_dan_jumlah_tetap_milik_sendiri(pg, scenario, owner):
    s = scenario
    async with client(s.customers[owner], portal=True) as c:
        for state, query in [('selesai',''), ('batal','?status=batal')]:
            page = await c.get('/pelanggan/barang-keluar'+query)
            assert page.status_code == 200
            expected = {s.records['jasa', owner, state].code} if owner < 2 else set()
            assert codes(page) == expected
            assert not BeautifulSoup(page.text, 'html.parser').select('[data-post],[data-aksi],dialog')
            assert 'Perbaiki pengiriman' not in page.text
            assert 'no-store' in page.headers['cache-control']
            for (kind, customer, _), r in s.records.items():
                if kind == 'nonjasa' or customer != owner:
                    assert r.code not in page.text
        foreign = s.records['jasa', 1 if owner == 0 else 0, 'batal']
        assert codes(await c.get('/pelanggan/barang-keluar', params={'status':'batal','q':foreign.code})) == set()


async def test_url_detail_dokumen_dan_penggantian_cakupan_ditolak(pg, scenario):
    s = scenario
    for owner in range(2):
        async with client(s.customers[owner], portal=True) as c:
            for state in ('selesai', 'batal'):
                own = s.records['jasa', owner, state]
                assert (await c.get(f'/pelanggan/barang-keluar/{own.id}')).status_code == 200
                for forbidden in (s.records['jasa', 1-owner, state], s.records['nonjasa', owner, state]):
                    for suffix in ('', '?rincian_perintah=1', '/serah-terima', '/serah-terima.pdf'):
                        assert (await c.get(f'/pelanggan/barang-keluar/{forbidden.id}'+suffix)).status_code == 404
            for path in ('barang-keluar', 'audit?rentang=semua'):
                sep = '&' if '?' in path else '?'
                assert (await c.get('/pelanggan/'+path+sep+'pelanggan_id='+str(s.owners[1-owner].id))).status_code == 404


async def test_audit_portal_dibatasi_sebelum_pencarian_dan_penghitungan(pg, scenario):
    s = scenario
    for owner in range(3):
        async with client(s.customers[owner], portal=True) as c:
            page = await c.get('/pelanggan/audit?rentang=semua')
            assert page.status_code == 200
            entries = audit_text(page)
            assert len(entries) == (2 if owner < 2 else 0)
            for kind in ('jasa', 'nonjasa'):
                if owner < 2:
                    assert any(s.records[kind, owner, 'selesai'].code in e for e in entries)
                for foreign in range(2):
                    if foreign != owner:
                        assert not any(s.records[kind, foreign, 'selesai'].code in e for e in entries)
            assert not BeautifulSoup(page.text, 'html.parser').main.select('form[method=post]')
            foreign = s.records['jasa', 1 if owner == 0 else 0, 'selesai']
            searched = await c.get('/pelanggan/audit', params={'rentang':'semua','cari':foreign.code})
            assert audit_text(searched) == []
            count = BeautifulSoup(searched.text, 'html.parser').select_one('.hitungan').get_text(' ', strip=True)
            assert count.startswith('0 dari '+('2' if owner < 2 else '0')+' catatan')


async def fingerprint(pg):
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        names = list(await db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")))
        result = {}
        for name in names:
            quoted = '"'+name.replace('"','""')+'"'
            result[name] = tuple((await db.execute(text(f"SELECT count(*),md5(COALESCE(string_agg(md5(to_jsonb(t)::text),'' ORDER BY md5(to_jsonb(t)::text)),'')) FROM {quoted} t"))).one())
        return result


async def test_pembacaan_dan_penolakan_akses_tidak_mengubah_data(pg, scenario):
    s = scenario
    before = await fingerprint(pg)
    async with client(s.staff['admin']) as c:
        for _ in range(2):
            for path in ('/barang-keluar', '/barang-keluar?status=batal', '/audit?rentang=semua'):
                assert (await c.get(path)).status_code == 200
    for owner in range(3):
        async with client(s.customers[owner], portal=True) as c:
            for path in ('/pelanggan/barang-keluar', '/pelanggan/barang-keluar?status=batal', '/pelanggan/audit?rentang=semua'):
                assert (await c.get(path)).status_code == 200
            assert (await c.get('/audit')).status_code == 303
            row = s.records['nonjasa', 0, 'selesai']
            for path in ('/audit/batalkan', f'/api/actions/koreksi-pengiriman/{row.id}/simpan'):
                r = await c.post(path, json={'jumlah':1}, headers={csrf.NAMA_HEADER:c.cookies.get(csrf.NAMA_COOKIE)})
                assert r.status_code in (303,401,403,404,405)
    after = await fingerprint(pg)
    assert after == before
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:
        balances = [float((await hitung_stok_finished_goods(db, s.stock['sku'], s.stock['std'], jasa_id=jid))['kg'])
                    for jid in [None, s.orders[0].id, s.orders[1].id]]
    assert balances == [4800, 2325, 2275]
    if os.getenv('BUKTI_RIWAYAT_UJI'):
        Path(os.environ['BUKTI_RIWAYAT_UJI'], 'sidik-tabel.json').write_text(json.dumps(
            dict(tabel=len(before), identik=True, saldo=dict(pabrik=balances[0], jasa_a=balances[1], jasa_b=balances[2])), indent=2))


async def test_retur_hanya_di_pengiriman_bukan_sidebar(pg, scenario):
    s = scenario
    for role in ('super', 'admin', 'g1', 'g2'):
        async with client(s.staff[role]) as c:
            page = await c.get('/pengaturan')
            assert page.status_code == 200
            nav = BeautifulSoup(page.text, 'html.parser').select_one('#laci')
            assert nav is not None and 'Barang Retur' not in nav.get_text()
            if role in ('super', 'admin'):
                page = await c.get('/barang-keluar')
                assert BeautifulSoup(page.text, 'html.parser').select_one('nav[aria-label="Jenis pengiriman"] a[href="/retur"]')
            else:
                assert (await c.get('/retur')).status_code == 403
    async with client(s.staff['super'], view='operator:g2') as c:
        page = await c.get('/pengaturan')
        assert 'Barang Retur' not in BeautifulSoup(page.text, 'html.parser').select_one('#laci').get_text()
        assert 'kembali' in page.text
        assert (await c.get('/retur')).status_code == 403
