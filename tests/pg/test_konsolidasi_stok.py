"""Navigasi baru memakai saldo/aksi lama dan tetap memeriksa akses server."""
from dataclasses import asdict, is_dataclass
from datetime import date
from html import unescape
import re

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.pg.test_stok_produk_jasa import sosoh_jasa  # noqa: F401
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_stok_karung_jasa import _beli

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def stok_lengkap(pg, sosoh_jasa, pemakai):
    from app.models import (Jasa, Pelanggan, MillingProcess, MillingProgressLog,
                            User, Warehouse, Silo)
    from app.database import now_local
    from app.penggilingan.inventory import models, packaging
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingOutputLog
    async with pg() as db:
        gudang = {g.kode_fungsi: g.id for g in (await db.execute(select(Warehouse))).scalars()}
        silo = Silo(nama_silo='Silo Uji G1', warehouse_id=gudang['g1'])
        db.add(silo)
        await db.flush()
        # Nama sengaja sama: filter tidak boleh menyatukan dua kontak berbeda.
        pel = Pelanggan(nama_pelanggan='Bu Sri')
        db.add(pel)
        await db.flush()
        j = Jasa(kode='JAS-2610-002', pelanggan_id=pel.id, status='berjalan')
        db.add(j)
        await db.flush()
        for kode, jid, kg in [('LOT-STOK-PABRIK', None, 6500),
                              ('LOT-STOK-JASA', sosoh_jasa['jasa_id'], 3500),
                              ('LOT-STOK-LAIN', j.id, 1250)]:
            p = MillingProcess(kode_proses=kode, status='selesai', jasa_id=jid, silo_id=silo.id,
                               berat_gabah_masuk_kg=kg * 1.5,
                               waktu_mulai=now_local(), waktu_selesai=now_local(),
                               created_by=pemakai.id)
            db.add(p)
            await db.flush()
            db.add(MillingProgressLog(milling_process_id=p.id,
                                      berat_kumulatif_kg=kg, waktu_update=now_local(),
                                      input_by=pemakai.id))
        pol = PolishingProcess(kode_proses='POL-STOK-LAIN', status='selesai',
                               jasa_id=j.id, created_by=pemakai.id,
                               waktu_mulai=now_local(), waktu_selesai=now_local())
        db.add(pol)
        await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=pol.id, jenis='premium',
                                 berat_kg=2300, waktu_update=now_local(), input_by=pemakai.id))
        ids = await _beli(db, models, pemakai=pemakai, lembar=800, kode='KMS-STOK', merk='Penyunesia')
        # Pemindahan melalui layanan asli, agar saldo pemilik dan audit sungguhan.
        admin = User(nama='Admin stok contoh', role='admin', status='aktif')
        db.add(admin)
        await db.commit()
        await packaging.pindah_kepemilikan_karung(
            db, user=admin, material_kode='laminasi', ukuran=25, brand_nama='Penyunesia',
            jumlah_lembar=100, pelanggan_id=sosoh_jasa['pelanggan_id'])
        await packaging.pindah_kepemilikan_karung(
            db, user=admin, material_kode='laminasi', ukuran=25, brand_nama='Penyunesia',
            jumlah_lembar=50, pelanggan_id=pel.id)
    return {**sosoh_jasa, 'lain': pel.id, 'gudang': gudang, 'kemasan': ids}


PASANGAN = [('/stok', 'bahan', 'pabrik'), ('/stok-pk-jasa', 'bahan', 'jasa'),
            ('/stok-produk', 'produk', 'pabrik'), ('/stok-produk-jasa', 'produk', 'jasa'),
            ('/stok-karung', 'karung', 'pabrik'), ('/stok-karung-jasa', 'karung', 'jasa')]


def normal(nilai):
    if is_dataclass(nilai):
        return asdict(nilai)
    if isinstance(nilai, list):
        return [normal(v) for v in nilai]
    if isinstance(nilai, dict):
        return {k: normal(v) for k, v in nilai.items()}
    return nilai


@pytest.mark.parametrize('lama,tab,pemilik', PASANGAN)
async def test_enam_alias_saldo_dan_aksi_sama(pg, stok_lengkap, monkeypatch, lama, tab, pemilik):
    from app.web import tampilan
    asli = tampilan.render
    hasil = []
    def rekam(request, nama, **konteks):
        hasil.append((nama, konteks))
        return asli(request, nama, **konteks)
    monkeypatch.setattr(tampilan, 'render', rekam)
    async with await _klien(pg, role='admin') as c:
        a = await c.get(lama + '?buka=pindah_kepemilikan_karung&nilai=laminasi%7C25%7CPenyunesia')
        b = await c.get(f'/stok?tab={tab}&pemilik={pemilik}&buka=pindah_kepemilikan_karung&nilai=laminasi%7C25%7CPenyunesia')
        assert a.status_code == b.status_code == 200, b.text
    assert hasil[0][0] == hasil[1][0]
    for k in ('lot', 'tempat', 'total', 'kartu', 'beras', 'samping', 'kemasan', 'karung',
              'daftar', 'sisa_beras', 'sisa_samping', 'curah_beras', 'curah_samping',
              'boleh_ubah', 'boleh_minta', 'boleh_pindah_tumpukan', 'BOLEH_CATAT',
              'BOLEH_PINDAH', 'BOLEH_MASUKKAN_SILO', 'buka', 'nilai'):
        assert normal(hasil[0][1].get(k)) == normal(hasil[1][1].get(k)), k
    nav = hasil[1][1]['STOK_NAV']
    assert nav['jenis'] == tab and nav['pemilik'] == pemilik
    if any(hasil[1][1].get(k) for k in ('boleh_ubah', 'boleh_minta', 'boleh_pindah_tumpukan', 'BOLEH_CATAT', 'BOLEH_PINDAH', 'BOLEH_MASUKKAN_SILO')):
        assert 'data-nilai="laminasi|25|Penyunesia"' in b.text
    if tab == 'bahan':
        assert hasil[1][1]['total'] == (6500 if pemilik == 'pabrik' else 4750)
    if tab == 'produk' and pemilik == 'pabrik':
        assert hasil[1][1]['sisa_beras'] == 9000
    if tab == 'karung' and pemilik == 'pabrik':
        assert sum(r['lembar'] for r in hasil[1][1]['karung']) == 650


@pytest.mark.parametrize('tab', ['bahan', 'produk', 'karung'])
async def test_filter_id_pelanggan_bukan_nama_dan_tidak_memindahkan_stok(pg, stok_lengkap, tab, monkeypatch):
    from app.web import tampilan
    asli, hasil = tampilan.render, []
    def rekam(request, nama, **k):
        hasil.append(k)
        return asli(request, nama, **k)
    monkeypatch.setattr(tampilan, 'render', rekam)
    async with await _klien(pg, role='admin') as c:
        r = await c.get(f'/stok?tab={tab}&pemilik=jasa&pelanggan_id={stok_lengkap["pelanggan_id"]}')
        assert r.status_code == 200, r.text
        k = hasil[-1]
        p = k['kelompok_pk'] if tab == 'bahan' else k['daftar']
        assert [x['pelanggan_id'] for x in p] == [stok_lengkap['pelanggan_id']]
        assert len(k['STOK_NAV']['pelanggan']) == 2
        if tab == 'bahan':
            assert k['total'] == 3500
            assert 'LOT-STOK-LAIN' not in r.text
        elif tab == 'produk':
            assert p[0]['sisa_beras'] == 5000
        else:
            assert sum(b['lembar'] for b in p[0]['karung']) == 100
        # Kembali ke semua pemilik tidak mengurangi stok karena filter hanya GET.
        semua = await c.get(f'/stok?tab={tab}&pemilik=jasa')
        assert semua.status_code == 200
        assert len(hasil[-1]['STOK_NAV']['pelanggan']) == 2


@pytest.mark.parametrize('role,gudang', [('admin', None), ('operator', 'g1'), ('operator', 'g2')])
async def test_akses_lama_baru_dan_navigasi_saat_kosong(pg, stok_lengkap, role, gudang):
    async with await _klien(pg, role=role, gudang_id=stok_lengkap['gudang'].get(gudang)) as c:
        for lama, tab, pemilik in PASANGAN:
            for url in (lama, f'/stok?tab={tab}&pemilik={pemilik}'):
                r = await c.get(url)
                assert r.status_code == (403 if gudang == 'g1' and tab != 'bahan' else 200), url
                if r.status_code == 200:
                    assert 'aria-label="Jenis barang"' in r.text
                    assert 'aria-label="Kepemilikan stok"' in r.text
                    assert 'class="pintu__jml pintu__jml--stok"' not in r.text
        if role == 'admin':
            r = await c.get('/stok?tab=produk&pemilik=pabrik&gudang=g1')
            assert 'Tak ada' in r.text or 'Belum ada' in r.text
            assert '9.000' not in r.text
            assert 'aria-label="Jenis barang"' in r.text


async def test_detail_dan_kembali_mempertahankan_filter(pg, stok_lengkap):
    from urllib.parse import urlencode
    asal = '/stok?' + urlencode(dict(tab='bahan', pemilik='jasa', gudang='g1', pelanggan_id=stok_lengkap['pelanggan_id']))
    async with await _klien(pg, role='superadmin') as c:
        r = await c.get(asal)
        href = next(unescape(h) for h in re.findall('href="([^"]+)"', r.text)
                    if h.startswith('/stok/pk/detail?') and 'LOT-STOK-JASA' in h)
        d = await c.get(href)
        assert d.status_code == 200, d.text
        from urllib.parse import urlsplit, parse_qs
        kembali = next(unescape(h) for h in re.findall('class="pk-detail__back" href="([^"]+)"', d.text))
        assert parse_qs(urlsplit(kembali).query) == parse_qs(urlsplit(asal).query)
        assert 'buka=verify_output' in d.text
        assert 'kembali_stok=' in d.text
        p = await c.get(f'/stok?tab=produk&pemilik=jasa&pelanggan_id={stok_lengkap["pelanggan_id"]}')
        href = next(unescape(h) for h in re.findall('href="([^"]+)"', p.text) if h.startswith('/stok-produk-jasa/detail?'))
        assert (await c.get(href)).status_code == 200
        k = await c.get('/stok?tab=karung&pemilik=pabrik&gudang=g2')
        href = next(unescape(h) for h in re.findall('href="([^"]+)"', k.text)
                    if 'buka=pindah_kepemilikan_karung' in h)
        q = parse_qs(urlsplit(href).query)
        assert q['tab'] == ['karung'] and q['pemilik'] == ['pabrik']
        assert q['gudang'] == ['g2']
        assert q['nilai'] == ['laminasi|25|Penyunesia']
        assert (await c.get(href)).status_code == 200


async def test_parameter_tidak_sah_tidak_membuka_semua_pemilik(pg, stok_lengkap):
    async with await _klien(pg, role='admin') as c:
        for url in ['/stok?tab=salah', '/stok?pemilik=semua', '/stok?pemilik=jasa&pelanggan_id=x']:
            assert (await c.get(url)).status_code == 422
        assert (await c.get('/stok?pemilik=jasa&pelanggan_id=99999')).status_code == 404


async def test_membaca_seluruh_tab_tidak_menulis_stok_atau_audit(pg, stok_lengkap):
    from sqlalchemy import event
    c = await _klien(pg, role='admin')
    async with pg() as db:
        mesin = db.bind.sync_engine
    tulis = []
    def rekam(conn, cursor, statement, params, context, many):
        if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            tulis.append(statement)
    event.listen(mesin, 'before_cursor_execute', rekam)
    try:
        async with c:
            for lama, tab, pemilik in PASANGAN:
                for url in (lama, f'/stok?tab={tab}&pemilik={pemilik}'):
                    assert (await c.get(url)).status_code == 200
    finally:
        event.remove(mesin, 'before_cursor_execute', rekam)
    assert tulis == []


async def test_navigasi_enam_pilihan_tetap_ada_pada_database_kosong(pg):
    async with await _klien(pg, role='admin') as c:
        for lama, tab, pemilik in PASANGAN:
            r = await c.get(f'/stok?tab={tab}&pemilik={pemilik}')
            assert r.status_code == 200, r.text
            assert 'aria-label="Jenis barang"' in r.text
            assert 'aria-label="Kepemilikan stok"' in r.text
            assert 'Belum ada' in r.text


async def test_karung_jasa_mempertahankan_cakupan_baca_lama_g2(pg, stok_lengkap, pemakai):
    from app.penggilingan.inventory import models, packaging
    from app.models import User
    async with pg() as db:
        await _beli(db, models, pemakai=pemakai, kode_mat='karung_pk', nama_mat='Karung PK',
                    ukuran=50, lembar=60, kode='KMS-PK-G1', merk=None)
        user = (await db.execute(select(User).where(User.nama == 'Admin stok contoh'))).scalar_one()
        await packaging.pindah_kepemilikan_karung(db, user=user, material_kode='karung_pk',
                  ukuran=50, brand_nama=None, pelanggan_id=stok_lengkap['pelanggan_id'], jumlah_lembar=20)
    async with await _klien(pg, gudang_id=stok_lengkap['gudang']['g2']) as c:
        for url in ('/stok-karung-jasa', '/stok?tab=karung&pemilik=jasa'):
            r = await c.get(url)
            assert r.status_code == 200
            assert 'Karung PK' in r.text
        r = await c.get('/stok?tab=karung&pemilik=pabrik')
        assert 'Karung PK' not in r.text
