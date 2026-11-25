"""Registry berizin native tanpa data; bukan tes transaksi atau akses baru."""
import json
import hashlib
import os
import time
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import event

from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role', ['operator', 'admin'])
async def test_registry_native_tanpa_pembaca_operasional_dan_scope_utuh(pg, lengkap, role, monkeypatch):
    from app.database import engine
    from app.web import kerangka_langsung as s
    from app.services import berjalan, barang_masuk_daftar, jasa_pelanggan
    from app.web import layar_pekerjaan

    asli = s.susun_registry
    ukuran, raw = {}, {}
    kemas_asli = s.kemas_frame
    def simpan_frame(frames):
        raw.clear(); raw.update(frames)
        return kemas_asli(frames)
    monkeypatch.setattr(s, 'kemas_frame', simpan_frame)
    def dilarang(*a, **kw):
        pytest.fail('Registry tidak boleh membaca daftar operasional')
    async def susun(request, akun, **kwargs):
        sql = []
        def rekam(*args):
            sql.append(args[2].split(None, 1)[0])
        asal_state = dict(request.scope.get('state', {}))
        asal_aktor = (akun.id, akun.user.id, akun.user.role, akun.user.default_warehouse_id)
        event.listen(engine.sync_engine, 'before_cursor_execute', rekam)
        start = time.perf_counter()
        try:
            with monkeypatch.context() as m:
                m.setattr(berjalan, 'untuk', dilarang)
                m.setattr(barang_masuk_daftar, 'daftar', dilarang)
                m.setattr(layar_pekerjaan, 'siapkan_daftar_pekerjaan', dilarang)
                m.setattr(jasa_pelanggan, 'daftar', dilarang)
                data = await asli(request, akun, **kwargs)
        finally:
            event.remove(engine.sync_engine, 'before_cursor_execute', rekam)
        assert request.scope.get('state', {}) == asal_state
        assert (akun.id, akun.user.id, akun.user.role, akun.user.default_warehouse_id) == asal_aktor
        elapsed = (time.perf_counter()-start)*1000
        decoded = {k: ''.join(data['potongan'][i] for i in refs) for k, refs in data['frames'].items()}
        sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
        assert {k:sha(v) for k,v in decoded.items()} == {k:sha(v) for k,v in raw.items()}
        from app.web.tampilan import templates
        naive = {k:data[k] for k in ('konteks', 'cap', 'sesi')}
        naive.update(versi=1, frames=raw)
        template = templates.get_template('_kerangka_langsung_registry.html')
        packed_size = len(template.render(registry=data).encode())
        naive_size = len(template.render(registry=naive).encode())
        assert packed_size < naive_size
        ukuran.update(sql=len(sql), ms=elapsed,
                      frame_bytes={k:len(v.encode()) for k,v in raw.items()},
                      frame_source_sha256={k:sha(v) for k,v in raw.items()},
                      frame_decoded_sha256={k:sha(v) for k,v in decoded.items()},
                      json_bytes=len(json.dumps(data).encode()), unique_chunks=len(data['potongan']),
                      frame_ref_counts={k:len(v) for k,v in data['frames'].items()},
                      packed_encoded_host_bytes=packed_size, naive_same_frames_host_bytes=naive_size,
                      reduction_bytes=naive_size-packed_size, reduction_percent=100*(naive_size-packed_size)/naive_size)
        return data
    monkeypatch.setattr(s, 'susun_registry', susun)
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as c:
        before = await _sidik(pg)
        r = await c.get('/kabar')
        assert r.status_code == 200
        doc = BeautifulSoup(r.text, 'html.parser')
        host = doc.select_one('#padi-kerangka-langsung')
        assert host and not host.find_parent(class_='bingkai')
        data = json.loads(host.string)
        assert set(data['frames']) == set(s.LITERAL) | ({'/jasa'} if role=='admin' else set())
        assert data['sesi'] == doc.select_one('#formulir-sesi')['data-token']
        assert data['konteks'] == doc.select_one('.bingkai')['data-pindah-konteks']
        assert data['versi'] == 2 and data['penyandian'] == 'baris-1'
        for url, refs in data['frames'].items():
            html = ''.join(data['potongan'][i] for i in refs)
            frame = BeautifulSoup(html, 'html.parser')
            assert len(frame.select('.bingkai')) == len(frame.select('#isi-halaman')) == 1
            assert frame.select_one('.bingkai')['data-pindah-alamat'] == url
            assert frame.select_one('.bingkai')['data-pindah-konteks'] == data['konteks']
            assert frame.select_one('.bingkai')['data-pindah-kerangka'] == '1'
            assert frame.select_one('#formulir-sesi')['data-token'] == data['sesi']
            assert not frame.select('#padi-kerangka-langsung,.halaman-memuat,.antrian-item,.masuk-baris')
            assert not any(marker in html for marker in ('TRX-391-', 'LOT-STOK-', 'POL-UJIP-', 'POL-UJIJ-'))
            assert frame.select_one('script[src*="menu-layar.js"]')
            assert frame.select_one('script[src*="sesi.js"]')
            assert frame.select_one('script[src*="kabar-badge.js"]')
            assert frame.select_one('section[aria-label],h1,[role="region"][aria-label]')
            columns = [n.get_text(strip=True) for n in frame.select('thead th')]
            if url == '/jasa':
                assert role == 'admin'
                assert frame.select_one('[data-jasa-bertahap]')
                assert frame.select_one('[data-jasa-kontrol] input[name=cari]')['value'] == ''
                assert frame.select_one('[data-jasa-baca-isi]')['aria-busy'] == 'true'
                assert not frame.select('a.jasa-pelanggan')
                from app.web.jasa_kerangka_aset import ASET, ROOT
                assert len(frame.select('[data-jasa-aset-native]')) == len(ASET)
                for name, path, tag in ASET:
                    node = frame.select_one(f'{tag}[data-jasa-aset-native="{name}"]')
                    assert node and node.string == (ROOT/path).read_text()
                    assert not frame.select(f'[href^="/static/{name}?"],[src^="/static/{name}?"]')
                assert frame.select_one('button[data-js-cetak]')['disabled'] == ''
            else:
                assert len(columns) == (5 if url.startswith('/pekerjaan') else 7 if 'diterima' in url else 6)
                assert frame.select_one('button[data-lk-cetak]')['disabled'] == ''
            assert not frame.select('[data-pemulihan],[data-koreksi-bahan]')
        assert await _sidik(pg) == before
        if os.environ.get('PHASE_OUT'):
            ukuran.update(role=role, all_public_tables_unchanged=True, heavy_readers_called=0,
                          html_response_bytes=len(r.content), host_encoded_bytes=len(str(host).encode()),
                          naive_equivalent_response_bytes=len(r.content)-ukuran['packed_encoded_host_bytes']+ukuran['naive_same_frames_host_bytes'])
            (Path(os.environ['PHASE_OUT'])/('registry-cost-'+role+'.json')).write_text(json.dumps(ukuran,indent=2)+'\n')


@pytest.mark.parametrize('sebab', ['sql', 'runtime'])
async def test_registry_opsional_gagal_tanpa_membocorkan_parameter(pg, lengkap, monkeypatch, caplog, sebab):
    from sqlalchemy.exc import SQLAlchemyError
    from app.web import kerangka_langsung as s
    from app.web import csrf
    async def tidak_tersedia(*a, **kw):
        error = SQLAlchemyError if sebab == 'sql' else RuntimeError
        raise error('SYNTHETIC_SQL_PARAMETER_SHOULD_NOT_BE_LOGGED')
    monkeypatch.setattr(s, 'susun_registry', tidak_tersedia)
    asli_dekorasi = s.lengkapi_dokumen
    async def dua_header(request, response):
        # Dua cookie fixture nonidentitas menguji header duplikat mentah,
        # bukan penerbitan kredensial atau perubahan kebijakan sesi native.
        response.raw_headers.extend([(b'set-cookie', b'fixture_registry_a=1; Path=/'),
                                     (b'set-cookie', b'fixture_registry_b=1; Path=/')])
        return await asli_dekorasi(request, response)
    monkeypatch.setattr(s, 'lengkapi_dokumen', dua_header)
    async with await _klien(pg, role='operator', gudang_id=lengkap['gudang']['g2']) as c:
        before = await _sidik(pg)
        # Kebijakan CSRF native tetap; nilai cookie tidak dicatat.
        c.cookies.delete(csrf.NAMA_COOKIE)
        r = await c.get('/kabar')
        assert r.status_code == 200 and 'no-store' in r.headers['cache-control']
        assert 'padi-kerangka-langsung' not in r.text
        cookies = r.headers.get_list('set-cookie')
        assert 'fixture_registry_a=1; Path=/' in cookies
        assert 'fixture_registry_b=1; Path=/' in cookies
        assert any(value.startswith(csrf.NAMA_COOKIE+'=') for value in cookies)
        logs = [x for x in caplog.records if x.name == s.__name__]
        assert logs and all(('SQLAlchemyError' if sebab == 'sql' else 'RuntimeError') in x.getMessage() for x in logs)
        assert all('SYNTHETIC_SQL_PARAMETER' not in x.getMessage() and not x.exc_info for x in logs)
        assert await _sidik(pg) == before


@pytest.mark.parametrize('failure', ['response503', 'exception503', 'runtime'])
async def test_jasa_opsional_gagal_tetap_mempertahankan_enam_kerangka(pg, lengkap, monkeypatch, failure, caplog):
    from fastapi import HTTPException
    from starlette.responses import Response
    from app.web import halaman_bertahap as h, kerangka_langsung as registry
    native = h.kerangka
    async def broken(request, akun, jenis, **kwargs):
        if jenis != 'jasa':
            return await native(request, akun, jenis, **kwargs)
        if failure == 'response503':
            return Response(status_code=503)
        if failure == 'exception503':
            raise HTTPException(503, 'SYNTHETIC_JASA_PARAMETER')
        raise RuntimeError('SYNTHETIC_JASA_PARAMETER')
    monkeypatch.setattr(h, 'kerangka', broken)
    async with await _klien(pg, role='admin') as client:
        before = await _sidik(pg)
        response = await client.get('/kabar')
        doc = BeautifulSoup(response.text, 'html.parser')
        host = doc.select_one('#padi-kerangka-langsung')
        assert response.status_code == 200 and host
        assert set(json.loads(host.string)['frames']) == set(registry.LITERAL)
        assert await _sidik(pg) == before
    assert 'SYNTHETIC_JASA_PARAMETER' not in caplog.text


@pytest.mark.parametrize('code', [401, 403])
async def test_jasa_opsional_izin_berubah_tidak_dijadikan_frame_sukses(pg, lengkap, monkeypatch, code):
    from fastapi import HTTPException
    from app.web import halaman_bertahap as h
    native = h.kerangka
    async def denied(request, akun, jenis, **kwargs):
        if jenis == 'jasa':
            raise HTTPException(code, 'Synthetic context changed')
        return await native(request, akun, jenis, **kwargs)
    monkeypatch.setattr(h, 'kerangka', denied)
    async with await _klien(pg, role='admin') as client:
        before = await _sidik(pg)
        response = await client.get('/kabar')
        assert response.status_code == 200
        assert not BeautifulSoup(response.text, 'html.parser').select('#padi-kerangka-langsung')
        assert await _sidik(pg) == before


async def test_anggaran_frame_filter_tetap_dua_walau_jasa_opsional():
    from app.web.kerangka_langsung import LITERAL, sah_rujukan
    base = {'versi':2,'penyandian':'baris-1','potongan':['frame'],
            'frames':{url:[0] for url in LITERAL}}
    base['frames'].update({'/pekerjaan?tab=tindakan&cari=A':[0],
                           '/pekerjaan?tab=berjalan&cari=A':[0]})
    assert sah_rujukan(base)
    base['frames']['/jasa']=[0]
    assert sah_rujukan(base)
    del base['frames']['/jasa']
    base['frames']['/pekerjaan?tab=berjalan&cari=B']=[0]
    assert not sah_rujukan(base)
    del base['frames']['/pekerjaan?tab=berjalan&cari=B']
    base['frames']['/jasa?status=berjalan']=[0]
    assert not sah_rujukan(base)
