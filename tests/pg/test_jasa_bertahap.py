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
        # This helper verifies the data-free manifest's finite shape. The
        # role/facility oracle is test_kerangka_ui_manifest's explicit matrix.
        variants=dict(shape['varians'])
        if 'giling' in variants:assert variants.pop('giling')=='giling-proses'
        assert variants in ({'pengiriman':'pengiriman-admin','jasa':'jasa-admin','akun':'akun-pribadi','laporan':'laporan-katalog'},{'pengiriman':'pengiriman-operator','akun':'akun-pribadi','laporan':'laporan-katalog'},{'akun':'akun-pribadi','laporan':'laporan-katalog'})
        from app.web.kerangka_ui import aset
        assert shape['sumber']==aset()['sumber']
        ui_matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-kerangka-ui" '
            r'data-konteks="[^"]+" data-cap="[^"]+">([^<]*)</script>',html))
        assert len(ui_matches)==1 and ui_matches[0].start()==end
        assert json.loads(ui_matches[0][1])==shape
        end=ui_matches[0].end()
    history_hosts=doc.select('#padi-riwayat-kerangka')
    assert len(history_hosts)<=1
    if history_hosts:
        history=history_hosts[0]
        assert history.name=='script' and history.get('type')=='application/json'
        assert set(history.attrs)=={'type','id','data-konteks','data-cap'}
        assert not history.find_parent(class_='bingkai')
        shape=json.loads(history.string)
        from app.web.riwayat_kerangka_langsung import valid
        assert valid(shape)
        assert shape['konteks']==history['data-konteks']==registry['konteks']
        assert shape['cap']==history['data-cap']==registry['cap']
        assert shape['sesi']==registry['sesi']
        assert set(shape)=={'versi','cap','konteks','sesi','sumber','targets','menu'}
        assert not any(key in shape for key in ('html','frames','potongan','rows','totals'))
        history_matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-riwayat-kerangka" '
            r'data-konteks="[^"]+" data-cap="[^"]+">([^<]*)</script>',html))
        assert len(history_matches)==1 and history_matches[0].start()==end
        assert json.loads(history_matches[0][1])==shape
        end=history_matches[0].end()
    settings_hosts=doc.select('#padi-pengaturan-kerangka')
    assert len(settings_hosts)<=1
    if settings_hosts:
        settings=settings_hosts[0]
        assert settings.name=='script' and settings.get('type')=='application/json'
        assert set(settings.attrs)=={'type','id','data-konteks','data-cap'}
        assert not settings.find_parent(class_='bingkai')
        shape=json.loads(settings.string)
        assert set(shape)=={'versi','cap','konteks','sesi','sumber','groups','advanced','recovery','short','console'}
        assert shape['versi']==1
        assert all(shape[k]==registry[k] for k in ('cap','konteks','sesi'))
        assert shape['konteks']==settings['data-konteks'] and shape['cap']==settings['data-cap']
        assert all(type(shape[k]) is bool for k in ('advanced','recovery','short'))
        assert set(shape['groups'])<={'akun','fasilitas','operasional','pengguna','sistem'}
        assert {'akun','fasilitas','pengguna','sistem'}<=set(shape['groups'])
        for group,flags in shape['groups'].items():
            assert isinstance(flags,list) and len(flags) in {'akun':{3},'fasilitas':{5,6},'operasional':{4},'pengguna':{2},'sistem':{3,4}}[group]
            assert all(type(flag) is bool for flag in flags)
        from app.web.pengaturan_kerangka_langsung import aset,valid_console
        assert shape['sumber']==aset()['sumber']
        assert shape['console']=='' or valid_console(shape['console'])
        assert len(shape['groups']['fasilitas'])==(6 if shape['console'] else 5)
        matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-pengaturan-kerangka" '
            r'data-konteks="[^\"]+" data-cap="[^\"]+">([^<]*)</script>',html))
        assert len(matches)==1 and matches[0].start()==end
        assert json.loads(matches[0][1])==shape
        end=matches[0].end()
    document_hosts=doc.select('#padi-dokumen-kerangka')
    assert len(document_hosts)<=1
    if document_hosts:
        document=document_hosts[0]
        assert document.name=='script' and document.get('type')=='application/json'
        assert set(document.attrs)=={'type','id','data-konteks','data-cap'}
        assert not document.find_parent(class_='bingkai')
        shape=json.loads(document.string)
        assert set(shape)=={'versi','sumber','cap','konteks','sesi','laporan','kabar'}
        assert type(shape['kabar']) is bool
        assert shape['versi']==1 and all(shape[k]==registry[k] for k in ('cap','konteks','sesi'))
        assert shape['konteks']==document['data-konteks'] and shape['cap']==document['data-cap']
        assert set(shape['laporan'])=={'targets','choices','rentang'}
        from app.web.dokumen_kerangka_langsung import aset
        meta=aset();assert shape['sumber']==meta['sumber']
        assert len(set(shape['laporan']['targets']))==len(shape['laporan']['targets'])>0
        assert set('/laporan/'+code for code in shape['laporan']['targets'])<=set(meta['variants'])
        assert set(shape['laporan']['targets'])<=set(shape['laporan']['choices'])
        from app.web.laporan import _daftar,PERIODE
        assert set(shape['laporan']['choices'])<=set(l.kode.removeprefix('tahap_') for l in _daftar())
        assert set(shape['laporan']['rentang'])=={key for key,_ in PERIODE if key!='khusus'}
        from datetime import date
        for value in shape['laporan']['rentang'].values():
            assert set(value)=={'dari','sampai'} and date.fromisoformat(value['dari'])<=date.fromisoformat(value['sampai'])
        matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-dokumen-kerangka" '
            r'data-konteks="[^\"]+" data-cap="[^\"]+">([^<]*)</script>',html))
        assert len(matches)==1 and matches[0].start()==end and json.loads(matches[0][1])==shape
        end=matches[0].end()
    sosoh_hosts=doc.select('#padi-sosoh-kerangka')
    assert len(sosoh_hosts)<=1
    if sosoh_hosts:
        host=sosoh_hosts[0]
        assert host.name=='script' and host.get('type')=='application/json'
        assert set(host.attrs)=={'type','id','data-konteks','data-cap'}
        assert not host.find_parent(class_='bingkai')
        shape=json.loads(host.string)
        assert set(shape)=={'versi','sumber','cap','konteks','sesi','layout','hasil'}
        assert shape['versi']==1 and all(shape[k]==registry[k] for k in ('cap','konteks','sesi'))
        assert shape['konteks']==host['data-konteks'] and shape['cap']==host['data-cap']
        from app.web.sosoh_kerangka_langsung import aset,descriptor
        assert shape['sumber']==aset()['sumber']
        assert descriptor(shape['hasil'],layout=shape['layout'],source=shape['sumber'],registry=registry)==shape
        matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-sosoh-kerangka" '
            r'data-konteks="[^\"]+" data-cap="[^\"]+">([^<]*)</script>',html))
        assert len(matches)==1 and matches[0].start()==end and json.loads(matches[0][1])==shape
        end=matches[0].end()
    master_hosts=doc.select('#padi-pengaturan-master-kerangka')
    assert len(master_hosts)<=1
    if master_hosts:
        host=master_hosts[0]
        assert host.name=='script' and host.get('type')=='application/json'
        assert set(host.attrs)=={'type','id','data-konteks','data-cap'}
        assert not host.find_parent(class_='bingkai')
        shape=json.loads(host.string)
        assert set(shape)=={'versi','sumber','cap','konteks','sesi','allowed'}
        assert shape['versi']==1 and shape['allowed'] is True
        assert all(shape[k]==registry[k] for k in ('cap','konteks','sesi'))
        assert shape['konteks']==host['data-konteks'] and shape['cap']==host['data-cap']
        from app.web.pengaturan_master_kerangka import aset
        assert shape['sumber']==aset()['sumber']
        matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-pengaturan-master-kerangka" '
            r'data-konteks="[^\"]+" data-cap="[^\"]+">([^<]*)</script>',html))
        assert len(matches)==1 and matches[0].start()==end and json.loads(matches[0][1])==shape
        end=matches[0].end()
    alat_hosts=doc.select('#padi-pengaturan-alat-kerangka')
    assert len(alat_hosts)<=1
    if alat_hosts:
        host=alat_hosts[0]
        assert host.name=='script' and host.get('type')=='application/json'
        assert set(host.attrs)=={'type','id','data-konteks','data-cap'}
        assert not host.find_parent(class_='bingkai')
        shape=json.loads(host.string)
        assert set(shape)=={'versi','sumber','cap','konteks','sesi','targets'}
        assert shape['versi']==1 and shape['targets']==['/pengaturan/alat']
        assert all(shape[k]==registry[k] for k in ('cap','konteks','sesi'))
        assert shape['konteks']==host['data-konteks'] and shape['cap']==host['data-cap']
        from app.web.pengaturan_alat_kerangka import aset
        assert shape['sumber']==aset()['sumber']
        matches=list(re.finditer(
            r'\n<script type="application/json" id="padi-pengaturan-alat-kerangka" '
            r'data-konteks="[^\"]+" data-cap="[^\"]+">([^<]*)</script>',html))
        assert len(matches)==1 and matches[0].start()==end and json.loads(matches[0][1])==shape
        end=matches[0].end()
    end = _akhir_host_registry_lengkap(doc, html, start, registry)
    assert html.count('</body>') == 1 and html[end:].startswith('\n</body>')
    return html[:start] + html[end + 1:]


def _akhir_host_registry_lengkap(doc, html, start, registry):
    """Validasi keluarga tambahan yang finite; lepaskan byte host render asli saja."""
    from app.web.tampilan import templates
    identity = {k: registry[k] for k in ('cap', 'konteks', 'sesi')}
    existing = {
        'stok': 'padi-stok-kerangka', 'ui': 'padi-kerangka-ui',
        'riwayat': 'padi-riwayat-kerangka', 'pengaturan': 'padi-pengaturan-kerangka',
        'dokumen': 'padi-dokumen-kerangka', 'sosoh': 'padi-sosoh-kerangka',
        'master': 'padi-pengaturan-master-kerangka', 'alat': 'padi-pengaturan-alat-kerangka',
    }
    values = {'registry': registry}
    for key, id_ in existing.items():
        nodes = doc.select('#' + id_)
        assert len(nodes) <= 1
        if nodes:
            values[key] = json.loads(nodes[0].string)  # sudah divalidasi di atas
    families = [
        ('pengaturan_detail', 'padi-pengaturan-detail-kerangka', {'targets', 'columns', 'processes'}),
        ('pengguna', 'padi-pengguna-kerangka', {'targets'}),
        ('beranda', 'padi-beranda-kerangka', {'references'}),
        ('muatan', 'padi-muatan-kerangka', {'permission'}),
        ('fasilitas_parent', 'padi-fasilitas-parent-kerangka', {'targets'}),
        ('retur_baca', 'padi-retur-baca-kerangka', {'targets'}),
    ]
    common = {'versi', 'sumber', 'cap', 'konteks', 'sesi'}
    for key, id_, extra in families:
        nodes = doc.select('#' + id_)
        assert len(nodes) <= 1
        if not nodes:
            continue
        node = nodes[0]
        assert node.name == 'script' and node.get('type') == 'application/json'
        assert set(node.attrs) == {'type', 'id', 'data-konteks', 'data-cap'}
        assert not node.find_parent(class_='bingkai')
        value = json.loads(node.string)
        assert set(value) == common | extra and type(value['versi']) is int and value['versi'] == 1
        assert all(value[k] == identity[k] for k in identity)
        assert node['data-konteks'] == identity['konteks'] and node['data-cap'] == identity['cap']
        if key == 'pengaturan_detail':
            from app.web.pengaturan_detail_kerangka import aset
            meta = aset()
            assert value['sumber'] == meta['sumber']
            assert value['columns'] == meta['references']['columns']
            assert value['processes'] == meta['references']['processes']
            variants = {'peran': {'peran-lihat', 'peran-gudang'}, 'akses': {'akses'},
                'sebab-berhenti': {'sebab-berhenti'}, 'mutu': {'mutu'}, 'kledo': {'kledo'},
                'sistem': {'sistem-admin', 'sistem-umum'}}
            assert isinstance(value['targets'], dict) and value['targets']
            for path, variant in value['targets'].items():
                assert path.startswith('/pengaturan/') and path.removeprefix('/pengaturan/') in variants
                assert variant in variants[path.removeprefix('/pengaturan/')]
        elif key == 'pengguna':
            from app.web.pengguna_baca_native import _bound_permission
            assert _bound_permission(value, identity)
        elif key == 'beranda':
            from app.web.beranda_kerangka import asset, descriptor
            assert value['sumber'] == asset()['sumber']
            assert descriptor(value['references'], registry=identity, source=value['sumber']) == value
        elif key == 'muatan':
            from app.web.muatan_kerangka import asset, descriptor
            assert value['sumber'] == asset()['sumber']
            assert descriptor(value['permission'], registry=identity, source=value['sumber']) == value
        elif key == 'fasilitas_parent':
            from app.web.fasilitas_parent_kerangka import aset, TARGETS
            assert value['sumber'] == aset()['sumber'] and value['targets'] == list(TARGETS)
            assert 'alat' in values  # guard sumber yang sama wajib hadir
        elif key == 'retur_baca':
            from app.web.retur_baca_kerangka import aset
            assert value['sumber'] == aset()['sumber'] and value['targets'] == ['/retur']
        values[key] = value
    catalogs = doc.select('[data-pengguna-native-catalog]')
    assert len(catalogs) <= 1
    if catalogs:
        node = catalogs[0]
        assert node.name == 'script' and node.get('type') == 'application/json'
        assert set(node.attrs) == {'type', 'data-pengguna-native-catalog', 'data-source-address', 'data-source-sha'}
        assert not node.find_parent(class_='bingkai') and 'pengguna' in values
        value = json.loads(node.string)
        assert node['data-source-address'] == value['source_address'] == doc.select_one('.bingkai')['data-pindah-alamat']
        assert node['data-source-sha'] == value['source_sha256']
        from app.web.pengguna_baca_native import katalog
        assert katalog(html[:start], source_address=value['source_address'], permission=values['pengguna']) == value
        values['pengguna_catalog'] = value
    # Template ini memiliki whitespace finite antarkeluarga. Cocokkan seluruh
    # byte suffix, termasuk urutan, atribut dan newline; jangan trim/serialize
    # ulang HTML native atau melepas script yang tidak diketahui.
    rendered = templates.get_template('_kerangka_langsung_registry.html').render(**values)
    assert html[start:start + len(rendered)] == rendered
    return start + len(rendered)


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
    assert host.startswith('\n<script') and host.count('<script') == 1
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
        full = full.replace(host, host + '\n')
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
