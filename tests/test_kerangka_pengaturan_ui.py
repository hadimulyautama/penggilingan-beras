"""Settings program is reproducible, data-free and derived from native slots."""
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]

def test_generated_settings_package_and_inputs_are_exact():
    spec=importlib.util.spec_from_file_location('public_settings_compiler',ROOT/'scripts/buat_kerangka_pengaturan.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    payload,manifest=m.build();meta=json.loads(manifest)
    assert payload==(ROOT/'app/web/static/kerangka-pengaturan-ui.js').read_bytes()
    assert manifest==(ROOT/'app/web/static/kerangka-pengaturan-ui.meta.json').read_bytes()
    assert m.build()==(payload,manifest)
    assert hashlib.sha256(payload).hexdigest()==meta['aset_sha256']
    for name,sha in meta['inputs'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
    data=json.loads(payload.decode().split('window.PadiKerangkaPengaturanData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])=={'/pengaturan','/pengaturan/sesi'}
    for item in data['variants'].values():
        doc=BeautifulSoup(item['html'],'html.parser')
        assert len(doc.select('[data-pengaturan-menu-kerangka]'))==1
        assert not doc.select('form,input,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]')
        assert doc.select_one('[data-pengaturan-menu-status]') and doc.select_one('[data-pengaturan-menu-retry]')
        assert all(x.has_attr('disabled') or x.has_attr('hidden') for x in doc.select('button'))
    index=BeautifulSoup(data['variants']['/pengaturan']['html'],'html.parser')
    assert [n['data-settings-group'] for n in index.select('[data-settings-group]')]==['akun','fasilitas','operasional','pengguna','sistem']
    assert [len(n.select('[data-settings-door]')) for n in index.select('[data-settings-group]')]==[3,6,4,2,4]
