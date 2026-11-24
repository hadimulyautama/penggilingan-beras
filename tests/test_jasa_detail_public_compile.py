"""Public compiler can run with all app imports forbidden; no runtime/DB."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).parents[1]


def test_public_compiler_is_source_only_and_generated_outputs_are_current():
    code=r'''
import importlib.abc,importlib.util,json,sys
from pathlib import Path
from bs4 import BeautifulSoup
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):
   raise AssertionError('Compiler attempted application runtime import: '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_jasa_detail.py')
spec=importlib.util.spec_from_file_location('public_jasa_compiler',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
payload,meta=m.build()
assert payload==Path('app/web/static/kerangka-jasa-detail-ui.js').read_bytes()
assert meta==Path('app/web/static/kerangka-jasa-detail-ui.meta.json').read_bytes()
raw=payload.decode().split('window.PadiKerangkaJasaDetailData=',1)[1].split(';\n',1)[0]
data=json.loads(raw)
assert list(data['variants'])==['ringkasan','penerimaan','proses','stok','pengambilan']
for component in data['variants'].values():
 doc=BeautifulSoup(component['html'],'html.parser')
 assert len(doc.select('.jasa-detail-tab>a'))==5
 assert not doc.select('form,input[name],input[type=hidden],[data-post],[data-kirim],script[src],link[rel=stylesheet]')
 assert '/jasa/pelanggan/1' not in component['html']
 assert doc.select_one('h1').get_text()=='Identitas pelanggan belum dibaca'
 assert all(n.has_attr('disabled') for n in doc.select('[data-js-cetak]'))
assert len(data['styles'])<5 and len(data['scripts'])<5
assert len(payload)<=524288
print('SOURCE_ONLY_PUBLIC_5_TABS_PASS')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'SOURCE_ONLY_PUBLIC_5_TABS_PASS' in result.stdout
