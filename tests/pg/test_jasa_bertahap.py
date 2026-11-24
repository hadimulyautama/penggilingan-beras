"""Negosiasi kerangka Jasa terpisah dari legacy; memakai dunia sintetis native."""
import hashlib,json,re
import pytest
from sqlalchemy import text
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien

pytestmark=pytest.mark.asyncio


def _tanpa_host_registry(html):
    """Hanya lepaskan tambahan inert persis; HTML native tidak dinormalisasi."""
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(html, 'html.parser')
    hosts = doc.select('#padi-kerangka-langsung')
    assert len(hosts) == 1
    host = hosts[0]
    assert host.name == 'script' and host.get('type') == 'application/json'
    assert set(host.attrs) == {'type', 'id', 'data-konteks', 'data-cap'}
    assert not host.find_parent(class_='bingkai')
    frames, sessions = doc.select('.bingkai'), doc.select('#formulir-sesi')
    assert len(frames) == len(sessions) == 1 and sessions[0] in frames[0].descendants
    registry = json.loads(host.string)
    assert set(registry) == {'versi', 'penyandian', 'konteks', 'cap', 'sesi', 'potongan', 'frames'}
    assert registry['versi'] == 2 and registry['penyandian'] == 'baris-1'
    assert registry['konteks'] == host['data-konteks'] == frames[0]['data-pindah-konteks']
    assert registry['cap'] == host['data-cap'] == doc.html['data-versi']
    assert registry['sesi'] == sessions[0]['data-token']
    assert all(isinstance(registry[k], str) and registry[k] for k in ('konteks', 'cap', 'sesi'))
    # Enam alamat yang disetujui: empat lama +default dan Perlu tindakan.
    # Tetap exact-set, bukan menerima tujuan baru yang tidak ditinjau.
    assert set(registry['frames']) == {'/barang-masuk', '/barang-masuk?status=belum',
                                     '/barang-masuk?status=diterima', '/pekerjaan?tab=berjalan',
                                     '/pekerjaan', '/pekerjaan?tab=tindakan'}
    pieces = registry['potongan']
    assert isinstance(pieces, list) and 0 < len(pieces) <= 16384
    assert all(isinstance(piece, str) and piece for piece in pieces)
    for refs in registry['frames'].values():
        assert isinstance(refs, list) and 0 < len(refs) <= 16384
        assert all(type(i) is int and 0 <= i < len(pieces) for i in refs)
        assert sum(len(pieces[i]) for i in refs) <= 524288
    # Komentar baris pertama template meninggalkan tepat satu newline awal.
    # Host produksi mempunyai urutan atribut ini dan tojson meng-escape '<'.
    # Ambil host lengkap dari sumber, bukan serialisasi ulang/trim HTML native.
    matches = list(re.finditer(
        r'\n<script type="application/json" id="padi-kerangka-langsung" '
        r'data-konteks="[^"]+" data-cap="[^"]+">([^<]*)</script>', html))
    assert len(matches) == 1 and json.loads(matches[0][1]) == registry
    start, end = matches[0].span()
    stocks = doc.select('#padi-stok-kerangka')
    assert len(stocks) <= 1
    if stocks:
        stock = stocks[0]
        assert stock.name == 'script' and stock.get('type') == 'application/json'
        assert set(stock.attrs) == {'type', 'id', 'data-konteks', 'data-cap'}
        assert not stock.find_parent(class_='bingkai')
        shape = json.loads(stock.string)
        assert set(shape) == {'versi','penyandian','konteks','cap','sesi','potongan','frames'}
        assert shape['versi'] == 1 and shape['penyandian'] == 'baris-1'
        assert shape['konteks'] == stock['data-konteks'] == registry['konteks']
        assert shape['cap'] == stock['data-cap'] == registry['cap']
        assert shape['sesi'] == registry['sesi']
        assert set(shape['frames']) in ({'bahan'},{'bahan','produk','karung'})
        assert isinstance(shape['potongan'],list) and 0<len(shape['potongan'])<=16384
        assert all(isinstance(p,str) and p for p in shape['potongan'])
        for tab,refs in shape['frames'].items():
            assert isinstance(refs,list) and 0<len(refs)<=16384
            assert all(type(i) is int and 0<=i<len(shape['potongan']) for i in refs)
            assert sum(len(shape['potongan'][i]) for i in refs)<=524288
            frame=BeautifulSoup(''.join(shape['potongan'][i] for i in refs),'html.parser')
            assert frame.select_one('.bingkai')['data-pindah-alamat']=='/stok?tab='+tab+'&pemilik=semua'
            assert frame.select_one('.bingkai')['data-pindah-konteks']==registry['konteks']
            assert frame.select_one('#formulir-sesi')['data-token']==registry['sesi']
            assert frame.html['data-versi']==registry['cap']
            assert frame.select_one('[data-halaman-bertahap][data-kind="stok"]')
        stock_matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-stok-kerangka" '
            r'data-konteks="[^"]+" data-cap="[^"]+">([^<]*)</script>',html))
        assert len(stock_matches)==1 and stock_matches[0].start()==end
        assert json.loads(stock_matches[0][1])==shape
        end=stock_matches[0].end()
    ui_hosts=doc.select('#padi-kerangka-ui')
    assert len(ui_hosts)<=1
    if ui_hosts:
        ui=ui_hosts[0]
        assert ui.name=='script' and ui.get('type')=='application/json'
        assert set(ui.attrs)=={'type','id','data-konteks','data-cap'}
        assert not ui.find_parent(class_='bingkai')
        shape=json.loads(ui.string)
        assert set(shape)=={'versi','sumber','konteks','cap','sesi','varians'}
        assert shape['versi']==1 and re.fullmatch('[0-9a-f]{64}',shape['sumber'])
        assert shape['konteks']==ui['data-konteks']==registry['konteks']
        assert shape['cap']==ui['data-cap']==registry['cap']
        assert shape['sesi']==registry['sesi']
        assert shape['varians'] in ({'pengiriman':'pengiriman-admin','jasa':'jasa-admin','akun':'akun-pribadi'},{'pengiriman':'pengiriman-operator','akun':'akun-pribadi'},{'akun':'akun-pribadi'})
        from app.web.kerangka_ui import aset
        assert shape['sumber']==aset()['sumber']
        ui_matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-kerangka-ui" '
            r'data-konteks="[^"]+" data-cap="[^"]+">([^<]*)</script>',html))
        assert len(ui_matches)==1 and ui_matches[0].start()==end
        assert json.loads(ui_matches[0][1])==shape
        end=ui_matches[0].end()
    assert html.count('</body>') == 1 and html[end:].startswith('\n</body>')
    return html[:start] + html[end + 1:]


def _dokumen_registry_uji():
    from pathlib import Path
    from fastapi.templating import Jinja2Templates
    native = ('<html data-versi="cap-uji"><body><div class="bingkai" '
              'data-pindah-konteks="konteks-uji"><div id="isi-halaman">'
              '<p>Isi native tetap</p></div><div id="formulir-sesi" '
              'data-token="sesi-uji"></div></div>\n</body>\n</html>')
    registry = dict(versi=2, penyandian='baris-1', konteks='konteks-uji',
                    cap='cap-uji', sesi='sesi-uji', potongan=['<section></section>'],
                    frames={url: [0] for url in ('/barang-masuk', '/barang-masuk?status=belum',
                            '/barang-masuk?status=diterima', '/pekerjaan?tab=berjalan',
                            '/pekerjaan', '/pekerjaan?tab=tindakan')})
    templates = Jinja2Templates(directory=str(
        Path(__file__).resolve().parents[2] / 'app/web/templates'))
    host = templates.get_template('_kerangka_langsung_registry.html').render(registry=registry)
    assert host.startswith('\n<script') and host.endswith('</script>')
    return native, native.replace('</body>', host + '\n</body>'), host


async def test_oracle_hanya_melepas_host_inert_bukan_perbedaan_isi_native():
    native, full, _ = _dokumen_registry_uji()
    assert _tanpa_host_registry(full) == native
    berubah = full.replace('<p>Isi native tetap</p>', '<p>Isi native berubah</p>')
    with pytest.raises(AssertionError):
        assert _tanpa_host_registry(berubah) == native
    # Newline native sebelum host tidak boleh ikut terbuang atau disamarkan.
    with pytest.raises(AssertionError):
        assert _tanpa_host_registry(full.replace('\n\n<script', '\n<script')) == native


@pytest.mark.parametrize('kasus', ['di-dalam-frame', 'ganda', 'shape-salah', 'newline-salah'])
async def test_oracle_menolak_host_di_luar_kontrak(kasus):
    native, full, host = _dokumen_registry_uji()
    if kasus == 'di-dalam-frame':
        full = native.replace('<p>Isi native tetap</p>', host + '<p>Isi native tetap</p>')
    elif kasus == 'ganda':
        full = full.replace('</body>', host + '\n</body>')
    elif kasus == 'shape-salah':
        full = full.replace('"versi": 2', '"versi": 1')
    else:
        full = full.replace('</script>\n</body>', '</script>\n\n</body>')
    with pytest.raises(AssertionError):
        _tanpa_host_registry(full)


async def _sidik(pg):
    async with pg() as db:
        names=(await db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).all()
        result={}
        for name in names:
            rows=(await db.scalars(text('SELECT row_to_json(x)::text FROM "'+name+'" x ORDER BY row_to_json(x)::text'))).all()
            result[name]=hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        return result

@pytest.mark.parametrize('role,gudang,code',[(P.ADMIN,None,200),(P.SUPERADMIN,None,200),(P.OPERATOR,'g1',403),(P.OPERATOR,'g2',403)])
async def test_renderer_eksplisit_dan_API_mempertahankan_legacy(pg,stok_lengkap,role,gudang,code):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(gudang)) as c:
        before=await _sidik(pg)
        full=await c.get('/jasa?status=berjalan')
        background=await c.get('/jasa?status=berjalan',headers={'X-Pindah':'1'})
        shell=await c.get('/jasa?status=berjalan',headers={'X-Pindah':'1','X-Kerangka-Halaman':'1'})
        data=await c.get('/api/halaman-bertahap/jasa?status=berjalan')
        assert full.status_code==background.status_code==shell.status_code==data.status_code==code
        if code==200:
            assert 'id="padi-kerangka-langsung"' not in background.text
            assert 'id="padi-kerangka-langsung"' not in data.json()['html']
            assert _tanpa_host_registry(full.text)==background.text==data.json()['html']
            assert full.text.count('class="kartu jasa-pelanggan"')==2
            assert 'data-jasa-bertahap' not in full.text
            assert 'data-jasa-bertahap' in shell.text
            assert '5.000' not in shell.text and 'Jumlah pelanggan belum dibaca.' in shell.text
            assert 'disabled aria-describedby="jasa-detail-alasan"' in shell.text
            assert 'no-store' in shell.headers['cache-control']
        else:
            assert 'Bu Sri' not in data.text and 'data-jasa-bertahap' not in shell.text
        assert await _sidik(pg)==before


@pytest.mark.parametrize('alamat',['/barang-masuk','/pekerjaan','/pekerjaan?tab=tindakan'])
async def test_oracle_tetap_menolak_kerangka_wajib_yang_hilang(alamat):
    from bs4 import BeautifulSoup
    native, full, _ = _dokumen_registry_uji()
    host = BeautifulSoup(full, 'html.parser').select_one('#padi-kerangka-langsung')
    registry = json.loads(host.string)
    del registry['frames'][alamat]
    encoded = json.dumps(registry).replace('<', '\\u003c')
    missing = full.replace(host.string, encoded)
    with pytest.raises(AssertionError):
        _tanpa_host_registry(missing)
    # Kontrol normal tetap membuktikan hanya host inert dilepas, isi native sama.
    assert _tanpa_host_registry(full) == native
