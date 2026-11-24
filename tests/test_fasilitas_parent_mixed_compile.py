"""Source compiler includes pending-only mixed bootstrap; no PG/browser/Git."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).parents[1]


def test_source_only_package_contains_visual_property_before_get_reader():
    # Build in memory so Root/peer-owned generated files are not overwritten.
    code=r'''
import hashlib,importlib.abc,importlib.util,json,sys
from pathlib import Path
from bs4 import BeautifulSoup
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):raise AssertionError('Product runtime import '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_fasilitas_parent.py');s=importlib.util.spec_from_file_location('facility_parent_mixed_source',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
payload,meta=m.build()
assert payload==Path('app/web/static/kerangka-fasilitas-parent-ui.js').read_bytes()
assert meta==Path('app/web/static/kerangka-fasilitas-parent-ui.meta.json').read_bytes()
data=json.loads(payload.decode().split('window.PadiKerangkaFasilitasParentData=',1)[1].split(';\n',1)[0])
metadata=json.loads(meta)
path='app/web/static/fasilitas-parent-native.js'
assert metadata['inputs'][path]==hashlib.sha256(Path(path).read_bytes()).hexdigest()
scripts=[source for source in data['scripts'].values() if 'function preparePending(root)' in source]
assert len(scripts)==1
source=scripts[0]
assert "root.matches('[data-fasilitas-parent-kerangka]')" in source
assert "input[type=checkbox][aria-checked=mixed]:disabled" in source
assert 'input.indeterminate=true' in source
assert 'preparePending(root);core.mount(config)' in source
assert 'input.checked=' not in source
for target,variant in data['variants'].items():
 doc=BeautifulSoup(variant['html'],'html.parser')
 roots=doc.select('[data-fasilitas-parent-kerangka]')
 assert len(roots)==1
 root=roots[0]
 assert root['data-url']==target and root['data-stamp']=='__PADI_STAMP__'
 assert root['data-record-ready']=='0'
 status=root.select_one('[data-fp-status]');retry=root.select_one('[data-fp-retry]')
 assert status is not None and status['role']=='status' and status['aria-live']=='polite'
 assert retry is not None and retry['type']=='button' and retry.has_attr('hidden')
 refs=doc.select('script[data-facility-parent-script]')
 assert len(refs)==2 and all(n['data-facility-parent-script'] in data['scripts'] for n in refs)
runtime=Path('app/web/static/kerangka-fasilitas-parent-ui-runtime.js').read_text()
assert "frameBound(document,ctx,cap,token,location.pathname+location.search)" in runtime
assert "frameBound(doc,ctx,cap,token,'/barang-masuk')" in runtime
assert "root.dataset.stamp=ctx+'|'+target" in runtime
for target in ('/pengaturan/mesin','/pengaturan/jenis-proses'):
 doc=BeautifulSoup(data['variants'][target]['html'],'html.parser')
 boxes=doc.select('input[type=checkbox]')
 assert len(boxes)==1 and boxes[0].has_attr('disabled') and boxes[0]['aria-checked']=='mixed' and not boxes[0].has_attr('checked')
assert len(payload)<=262144
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
