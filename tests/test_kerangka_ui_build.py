"""Public structure compiler; no application session or database."""
import gzip, importlib.util, json
from pathlib import Path
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ui_compiler',ROOT/'scripts/buat_kerangka_ui.py')
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)


def test_compiler_is_deterministic_and_committed_asset_is_current():
    first=compiler.build();assert first==compiler.build()
    for name,payload in zip(('kerangka-ui.js','kerangka-ui.meta.json'),first):
        assert (ROOT/'app/web/static'/name).read_bytes()==payload
    assert len(gzip.compress(first[0],mtime=0))<45000


def test_blueprints_use_native_columns_and_only_authorized_layout_variants():
    script,meta=compiler.build()
    data=json.loads(script.decode().split('window.PadiKerangkaUIData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])=={'pengiriman-admin','pengiriman-operator','jasa-admin','akun-pribadi','laporan-katalog'}|{f'stok-{tab}-{mutu}-{owner}' for tab in ('bahan','produk','karung') for mutu in (0,1) for owner in (0,1)}
    columns=[]
    for name,variant in data['variants'].items():
        doc=BeautifulSoup(variant['html'],'html.parser')
        assert not doc.select('.halaman-memuat,[data-detail-keluar],input[name=_csrf],form[method=post]')
        if name!='akun-pribadi':assert not doc.select('h1')
        assert not doc.select('script[src],link[rel=stylesheet]')
        if name=='laporan-katalog':
            assert len(doc.select('a[data-laporan]'))==13
            assert not doc.select('h1,table,form,input')
            assert doc.select_one('[data-laporan-katalog-kerangka]')
            continue
        if name=='akun-pribadi':
            assert doc.select_one('[data-pengaturan-akun-kerangka]')
            assert not doc.select('input[name],input[value],form[action],form[method],input[type=password]')
            continue
        assert all(form.get('method')=='get' for form in doc.select('form'))
        for style in doc.select('[data-ui-style-ref]'):
            assert style['data-ui-style-ref'] in data['styles'] and not style.get_text()
        for script in doc.select('[data-ui-script-ref]'):
            assert script['data-ui-script-ref'] in data['scripts'] and not script.get_text()
        if name.startswith('stok-'):
            assert doc.select_one('[data-ui-stock-public]')
            assert all(n.has_attr('disabled') for n in doc.select('[data-sk-cetak],select[name=gudang],select[name=pelanggan_id]'))
            assert not doc.select('select[name=gudang] option:not([value=""]),select[name=pelanggan_id] option:not([value=""])')
            assert all(not n.has_attr('href') for n in doc.select('[data-ui-stock-tab]'))
            continue
        if name=='jasa-admin':
            assert doc.select_one('[data-jasa-bertahap][aria-label="Pesanan Jasa"]')
            assert all(n.has_attr('disabled') for n in doc.select('[data-js-cetak]'))
            assert doc.select_one('input[name=cari]')
            assert not doc.select('a.jasa-pelanggan')
            continue
        assert all(node.has_attr('disabled') for node in doc.select('[data-bk-cetak]'))
        assert bool(doc.select('a[href="/barang-keluar/baru"]'))==name.endswith('-admin')
        assert len(doc.select('thead th'))==11
        columns.append([n.get_text(' ',strip=True) for n in doc.select('thead th')])
        assert doc.select_one('style[data-kerangka-ui-style]')
    assert columns[0]==columns[1]
