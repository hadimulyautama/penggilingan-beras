"""Kerangka dua daftar tidak menunggu data dan tidak menjadi jalan izin baru.

Fixture tetap memakai migrasi PostgreSQL serta pembaca native. Perubahan
data di bawah hanya membentuk dunia sintetis sebelum oracle baca diambil;
bukan pembuktian browser/tenant hosted atau penulisan transaksi lewat GET.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from html.parser import HTMLParser
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select, text
from starlette.requests import Request

from app.models import User, Warehouse
from hmu_identitas import peran as P
from tests.pg.test_pk_karung import dunia, batch_baru, pindah  # noqa: F401
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio

PEMBACA = [(P.OPERATOR, 'Gudang 1'),
           (P.OPERATOR, 'Gudang 2 - Kerangka uji'),
           (P.ADMIN, 'Gudang 2 - Kerangka uji'),
           (P.SUPERADMIN, 'Gudang 2 - Kerangka uji')]


class _Elemen(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def pilih(self, tag, **attrs):
        return [a for t, a in self.tags if t == tag
                and all(a.get(k) == v for k, v in attrs.items())]


class _Struktur(HTMLParser):
    """Baca hubungan kontrol/panel dan sidebar, tanpa menafsirkan JavaScript."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__()
        self.nodes, self.stack, self.sidebar_hrefs = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = dict(tag=tag, attrs=dict(attrs), text=[])
        self.nodes.append(node)
        if tag == 'a' and 'href' in node['attrs'] and any(
                n['attrs'].get('id') == 'laci' for n in self.stack):
            self.sidebar_hrefs.append(node['attrs']['href'])
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        for node in self.stack:
            node['text'].append(data)

    def named_buttons(self, name):
        return [n for n in self.nodes if n['tag'] == 'button' and
                (n['attrs'].get('aria-label') or ' '.join(
                    ''.join(n['text']).split())) == name]

    def by_id(self, ident):
        matches = [n for n in self.nodes if n['attrs'].get('id') == ident]
        assert len(matches) == 1, ('Identitas panel/alasan harus tunggal', ident)
        return matches[0]


def _stamp(html):
    roots = [a for _, a in _Elemen(html).tags if 'data-halaman-bertahap' in a]
    assert len(roots) == 1
    return roots[0]['data-stamp']


def _isi(html):
    """Bandingkan isi yang benar-benar dipasang, bukan header HTTP/meta waktu."""
    awal, akhir = '<!-- isi-halaman:mulai -->', '<!-- isi-halaman:akhir -->'
    assert awal in html and akhir in html
    return re.sub(r'\s+', ' ', html.split(awal, 1)[1].split(akhir, 1)[0]).strip()


async def _sidik(pg):
    async with pg() as db:
        names = (await db.scalars(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "ORDER BY tablename"))).all()
        result = {}
        for name in names:
            ident = name.replace('"', '""')
            rows = (await db.scalars(text(
                'SELECT row_to_json(x)::text FROM "' + ident +
                '" x ORDER BY row_to_json(x)::text'))).all()
            result[name] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        return result


@pytest.fixture
async def proses_aktif(pg, dunia):
    from app.penggilingan.gudang2 import polishing
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        user, _, intake = await batch_baru(db, dunia, n=100, w=5000,
                                          kode='PKB-SHELL-01')
        warehouse = await db.get(Warehouse, user.default_warehouse_id)
        warehouse.nama_gudang = 'Gudang 2 - Kerangka uji'
        await db.commit()
        await pindah(db, user, intake, 100)
        process = (await polishing.mulai_penyosohan(
            db, user=user, nama_silos=['A'])).proc
        for kind, weight in [('medium', 2600), ('premium', 1300), ('broken', 400)]:
            await polishing.catat_output(db, user=user,
                kode=process.kode_proses, jenis=kind, berat_kumulatif=weight)
        return process.kode_proses


@pytest.mark.parametrize('role,warehouse', PEMBACA)
async def test_kerangka_aktif_tidak_memanggil_pembaca_antrean(
        pg, proses_aktif, monkeypatch, role, warehouse):
    from app.web import layar_pekerjaan

    async def tidak_boleh_dibaca(*args, **kwargs):
        pytest.fail('Kerangka menunggu pembentukan daftar pekerjaan penuh')

    monkeypatch.setattr(layar_pekerjaan, 'siapkan_daftar_pekerjaan', tidak_boleh_dibaca)
    async with await _klien(pg, peran=role, gudang=warehouse) as c:
        response = await c.get('/pekerjaan?tab=berjalan&cari=kode-uji&pemasok=Pihak+uji')
    assert response.status_code == 200
    doc = _Elemen(response.text)
    assert _stamp(response.text)
    assert len(doc.pilih('th', scope='col')) == 5
    assert 'Kode &amp; proses' in response.text
    assert 'Memuat data' in response.text and proses_aktif not in response.text
    assert {a.get('value') for a in doc.pilih('input', name='cari')} == {'kode-uji'}
    assert doc.pilih('input', name='pemasok', value='Pihak uji')
    assert any('disabled' in a for a in doc.pilih('select', name='pemasok'))
    assert 'no-store' in response.headers['cache-control'] and 'public' not in response.headers['cache-control']


@pytest.mark.parametrize('tab', ['bahan', 'produk', 'karung'])
@pytest.mark.parametrize('role,warehouse', PEMBACA)
async def test_kerangka_stok_tidak_memanggil_pembaca_saldo(
        pg, proses_aktif, monkeypatch, tab, role, warehouse):
    from app.services import stok
    from app.web import layar_produk

    async def tidak_boleh_dibaca(*args, **kwargs):
        pytest.fail('Kerangka menunggu pembacaan saldo/barang native')

    monkeypatch.setattr(stok, 'pk_gudang1', tidak_boleh_dibaca)
    monkeypatch.setattr(stok, 'pk_gudang2', tidak_boleh_dibaca)
    monkeypatch.setattr(stok, 'barang_jadi_g2', tidak_boleh_dibaca)
    monkeypatch.setattr(layar_produk, 'pembaca_stok', tidak_boleh_dibaca)
    async with await _klien(pg, peran=role, gudang=warehouse) as c:
        response = await c.get('/stok', params={'tab': tab, 'cari': 'contoh-uji'})
    assert response.status_code == 200
    doc = _Elemen(response.text)
    assert _stamp(response.text)
    assert len(doc.pilih('th', scope='col')) >= 6
    assert 'Memuat data' in response.text
    assert {a.get('value') for a in doc.pilih('input', name='cari')} == {'contoh-uji'}
    assert any('disabled' in a for a in doc.pilih('select', name='pelanggan_id'))


@pytest.mark.parametrize('role,warehouse', PEMBACA)
@pytest.mark.parametrize('kind,query', [
    ('pekerjaan', 'tab=berjalan'),
    ('stok', 'tab=bahan'),
    ('stok', 'tab=produk'),
    ('stok', 'tab=karung'),
])
async def test_isi_sama_dengan_native_dan_seluruh_tabel_tetap(
        pg, proses_aktif, role, warehouse, kind, query):
    async with await _klien(pg, peran=role, gudang=warehouse) as c:
        # Semua seed dan sesi sintetis selesai sebelum fase baca diukur.
        before = await _sidik(pg)
        shell = await c.get('/' + kind + '?' + query)
        native = await c.get('/' + kind + '?' + query, headers={'X-Pindah': '1'})
        response = await c.get('/api/halaman-bertahap/' + kind + '?' + query)
        assert shell.status_code == native.status_code == response.status_code == 200
        payload = response.json()
        assert payload['stamp'] == _stamp(shell.text)
        assert 'data-halaman-bertahap' not in native.text
        assert _isi(payload['html']) == _isi(native.text)
        if kind == 'pekerjaan':
            if role == P.OPERATOR and warehouse == 'Gudang 1':
                assert proses_aktif not in native.text
            else:
                assert proses_aktif in native.text
        assert await _sidik(pg) == before
        assert 'no-store' in response.headers['cache-control'] and 'public' not in response.headers['cache-control']


async def test_get_opsi_pelanggan_tetap_html_native_dengan_penanda_konteks(
        pg, proses_aktif):
    async with await _klien(pg, peran=P.ADMIN, gudang='Gudang 2 - Kerangka uji') as c:
        before = await _sidik(pg)
        response = await c.get('/api/halaman-bertahap/stok/html?tab=bahan&pemilik=jasa')
        native = await c.get('/stok?tab=bahan&pemilik=jasa', headers={'X-Pindah': '1'})
        assert response.status_code == native.status_code == 200
        assert response.headers['content-type'].startswith('text/html')
        assert re.fullmatch('[0-9a-f]{64}', response.headers['x-halaman-konteks'])
        assert _isi(response.text) == _isi(native.text)
        assert await _sidik(pg) == before


async def test_data_memeriksa_ulang_akun_setelah_kerangka(pg, proses_aktif):
    from app.models import ProduksiAkun

    async with await _klien(pg, peran=P.OPERATOR, gudang='Gudang 2 - Kerangka uji') as c:
        shell = await c.get('/pekerjaan?tab=berjalan')
        assert shell.status_code == 200 and _stamp(shell.text)
        async with pg() as db:
            account = await db.scalar(select(ProduksiAkun).order_by(ProduksiAkun.id.desc()))
            user = await db.get(User, account.user_id)
            user.status = 'nonaktif'
            await db.commit()
        response = await c.get('/api/halaman-bertahap/pekerjaan?tab=berjalan',
                               follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'].startswith('/masuk?next=')
        assert proses_aktif not in response.text


@pytest.mark.parametrize('path', [
    '/api/halaman-bertahap/pekerjaan?tab=berjalan',
    '/api/halaman-bertahap/stok?tab=bahan',
    '/api/halaman-bertahap/stok/html?tab=bahan',
])
async def test_endpoint_baru_tidak_membuka_baca_tanpa_sesi(pg, path):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://uji') as c:
        response = await c.get(path)
    assert response.status_code == 303
    assert response.headers['location'].startswith('/masuk?next=')
    assert 'data-halaman-bertahap' not in response.text


async def test_penanda_membedakan_query_dan_batas_konteks():
    """Kontrak stale-response, bukan pengujian grant atau tenant hosted."""
    from app.web import csrf, security
    from app.web.halaman_bertahap import penanda, penanda_konteks

    account = SimpleNamespace(id=43, token_version=1, sesi_pendek=False,
        user=SimpleNamespace(id=42, role=P.OPERATOR, default_warehouse_id=20))
    token = security.buat_token(account)

    def request(query='tab=berjalan', view='polesan', company=7,
                namespace='operator:g2', session=token, nonce='fixture-csrf-only'):
        cookies = (f'{security.NAMA_COOKIE}={session}; {csrf.NAMA_COOKIE}={nonce}; '
                   f'produksi_lihat={namespace}')
        return Request({'type': 'http', 'method': 'GET', 'scheme': 'http',
            'path': '/pekerjaan', 'query_string': query.encode(),
            'headers': [(b'cookie', cookies.encode())],
            'server': ('uji', 80), 'client': ('127.0.0.1', 1),
            'state': {'view': view, 'akses_produk': SimpleNamespace(company_id=company)}})

    original = penanda(request(), account, 'pekerjaan')
    changed_query = request(query='tab=berjalan&cari=lain')
    assert penanda(changed_query, account, 'pekerjaan') != original
    assert penanda_konteks(changed_query, account) == penanda_konteks(request(), account)
    for changed in [request(view='selepan'), request(company=8),
                    request(namespace='operator:g1'), request(nonce='fixture-lain')]:
        assert penanda(changed, account, 'pekerjaan') != original
    account.user.role = P.ADMIN
    assert penanda(request(), account, 'pekerjaan') != original
    account.user.role = P.OPERATOR
    account.token_version = 2
    assert penanda(request(session=security.buat_token(account)), account, 'pekerjaan') != original


@pytest.mark.parametrize('role,warehouse', PEMBACA)
@pytest.mark.parametrize('path', ['/pekerjaan?tab=berjalan', '/stok?tab=bahan'])
async def test_sidebar_kerangka_mempertahankan_pintu_native(
        pg, proses_aktif, role, warehouse, path):
    """Angka boleh belum ada; alias/pintu yang pensiun tidak boleh muncul lagi."""
    async with await _klien(pg, peran=role, gudang=warehouse) as c:
        initial = await c.get(path)
        native = await c.get(path, headers={'X-Pindah': '1'})
    assert initial.status_code == native.status_code == 200
    shell_hrefs = _Struktur(initial.text).sidebar_hrefs
    native_hrefs = _Struktur(native.text).sidebar_hrefs
    assert shell_hrefs and native_hrefs
    assert Counter(shell_hrefs) == Counter(native_hrefs)


@pytest.mark.parametrize('path', ['/pekerjaan?tab=berjalan', '/stok?tab=bahan'])
async def test_panduan_tersambung_dan_cetak_belum_aktif_sebelum_data(
        pg, proses_aktif, path):
    async with await _klien(pg, peran=P.OPERATOR, gudang='Gudang 2 - Kerangka uji') as c:
        response = await c.get(path)
    assert response.status_code == 200
    document = _Struktur(response.text)
    guides = document.named_buttons('Panduan')
    assert len(guides) == 1
    attrs = guides[0]['attrs']
    target = (attrs.get('aria-controls') or attrs.get('data-lk-buka')
              or attrs.get('data-sk-buka') or attrs.get('data-shell-guide'))
    assert target, 'Panduan harus menunjuk panel yang benar-benar dirender'
    panel = document.by_id(target)
    assert panel['tag'] in {'dialog', 'details', 'section', 'div'}
    assert len(''.join(panel['text']).strip()) > 40
    prints = document.named_buttons('Cetak')
    assert len(prints) == 1, 'Jangan menawarkan Cetak native aktif bersama Cetak shell'
    assert 'disabled' in prints[0]['attrs']
    reason_id = prints[0]['attrs'].get('aria-describedby')
    assert reason_id, 'Cetak nonaktif harus memiliki alasan yang dapat dibaca'
    reason = document.by_id(reason_id)
    assert re.search(r'memuat|belum|setelah|tunggu', ''.join(reason['text']), re.I)
