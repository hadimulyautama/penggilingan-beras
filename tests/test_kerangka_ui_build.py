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
    assert len(gzip.compress(first[0],mtime=0))<30000


def test_blueprints_use_native_columns_and_only_authorized_layout_variants():
    script,meta=compiler.build()
    data=json.loads(script.decode().split('window.PadiKerangkaUIData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])=={'pengiriman-admin','pengiriman-operator'}
    columns=[]
    for name,variant in data['variants'].items():
        doc=BeautifulSoup(variant['html'],'html.parser')
        assert not doc.select('h1,.halaman-memuat,[data-detail-keluar],input[name=_csrf],form[method=post]')
        assert not doc.select('script[src],link[rel=stylesheet]')
        assert all(form.get('method')=='get' for form in doc.select('form'))
        assert all(node.has_attr('disabled') for node in doc.select('[data-bk-cetak]'))
        assert bool(doc.select('a[href="/barang-keluar/baru"]'))==name.endswith('-admin')
        assert len(doc.select('thead th'))==11
        columns.append([n.get_text(' ',strip=True) for n in doc.select('thead th')])
        assert doc.select_one('style[data-kerangka-ui-style]')
    assert columns[0]==columns[1]
