"""Settings program is reproducible, data-free and derived from native slots."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined
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
        assert set(item)=={'title','html','breadcrumb','mobile'}
        doc=BeautifulSoup(item['html'],'html.parser')
        assert len(doc.select('[data-pengaturan-menu-kerangka]'))==1
        assert not doc.select('form,input,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]')
        assert doc.select_one('[data-pengaturan-menu-status]') and doc.select_one('[data-pengaturan-menu-retry]')
        assert all(x.has_attr('disabled') or x.has_attr('hidden') for x in doc.select('button'))
    index=BeautifulSoup(data['variants']['/pengaturan']['html'],'html.parser')
    assert [n['data-settings-group'] for n in index.select('[data-settings-group]')]==['akun','fasilitas','operasional','pengguna','sistem']
    assert [len(n.select('[data-settings-door]')) for n in index.select('[data-settings-group]')]==[3,6,4,2,4]


def generated():
    payload=(ROOT/'app/web/static/kerangka-pengaturan-ui.js').read_text()
    return json.loads(payload.split('window.PadiKerangkaPengaturanData=',1)[1].split(';\n',1)[0])


def native_environment():
    return Environment(loader=ChoiceLoader([FileSystemLoader(str(ROOT/p)) for p in ('app/web/templates','hmu_tampilan/templates')]),
                       autoescape=True,undefined=StrictUndefined)


def chrome_signature(html):
    doc=BeautifulSoup(html,'html.parser')
    nav=doc.select('nav.desktop-breadcrumb')
    back=doc.select('a.desktop-back')
    assert len(nav)==len(back)==1, 'Native breadcrumb and explicit desktop Back are both required'
    trail=[]
    for li in nav[0].select('ol>li'):
        item=li.select_one('a[href],[aria-current=page]');assert item
        trail.append((item.name,item.get_text(' ',strip=True),item.get('href'),item.get('aria-current')))
    return trail,(back[0].get('href'),back[0].get('aria-label'),back[0].get_text(' ',strip=True))


@pytest.mark.parametrize('path',['/pengaturan','/pengaturan/sesi'])
def test_compiled_chrome_is_native_target_breadcrumb_back_control_and_title(path):
    env=native_environment();template=env.get_template('pengaturan.html')
    title=''.join(template.blocks['judul'](template.new_context({}))).strip()
    assert 'judul' not in env.get_template('pengaturan_fasilitas.html').blocks
    spec=importlib.util.spec_from_file_location('settings_native_trail',ROOT/'app/web/breadcrumb.py')
    native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    expected=env.get_template('_breadcrumb.html').render(rantai=native.susun(path,{},title))
    component=generated()['variants'][path]
    assert component['title']==title
    assert chrome_signature(component['breadcrumb'])==chrome_signature(expected)
    assert chrome_signature(component['breadcrumb'])[1][0]==('/' if path=='/pengaturan' else '/pengaturan')
    base=(ROOT/'hmu_tampilan/templates/base.html').read_text()
    start=base.index('  {% if not kembali or LAPORAN_NAV %}',base.index('<header class="bar"'))
    end=base.index('  <span class="bar__merek"',start)
    control=env.from_string(base[start:end]).render(kembali=None,LAPORAN_NAV=None)
    assert BeautifulSoup(component['mobile'],'html.parser')==BeautifulSoup(control,'html.parser')
    assert BeautifulSoup(component['mobile'],'html.parser').select_one('#buka-laci.bar__menu[aria-controls=laci]')
    # Native index has no H1; the native session body has its own heading,
    # distinct from the inherited document-title block above.
    pending=BeautifulSoup(component['html'],'html.parser')
    label_spec=importlib.util.spec_from_file_location('settings_native_labels_test',ROOT/'app/web/pengaturan_navigasi.py')
    labels=importlib.util.module_from_spec(label_spec);label_spec.loader.exec_module(labels)
    assert [n.get_text(' ',strip=True) for n in pending.select('h1')]==([] if path=='/pengaturan' else [labels.HALAMAN['sesi'][1]])


def test_missing_desktop_back_negative_rejects_the_old_bare_link_shape():
    component=generated()['variants']['/pengaturan']
    broken=BeautifulSoup(component['breadcrumb'],'html.parser')
    broken.select_one('a.desktop-back').decompose()
    with pytest.raises(AssertionError,match='desktop Back'):
        chrome_signature(str(broken))
    with pytest.raises(AssertionError,match='desktop Back'):
        chrome_signature('<a href="/pengaturan">Pengaturan</a>')


def test_native_chrome_sources_are_pinned_and_no_runtime_bare_crumb_replacement_remains():
    manifest=json.loads((ROOT/'app/web/static/kerangka-pengaturan-ui.meta.json').read_text())
    assert {'app/web/breadcrumb.py','hmu_tampilan/templates/_breadcrumb.html',
            'hmu_tampilan/templates/base.html','hmu_tampilan/templates/pengaturan.html',
            'app/web/templates/pengaturan_fasilitas.html','app/web/pengaturan_navigasi.py'}<=manifest['inputs'].keys()
    runtime=(ROOT/'app/web/static/kerangka-pengaturan-ui-runtime.js').read_text()
    assert "control.innerHTML=component.mobile" in runtime
    assert "trail.innerHTML=component.breadcrumb" in runtime
    assert "doc.title=component.title+" in runtime
    assert "crumb.replaceChildren(a)" not in runtime


def test_chrome_compiler_cannot_import_app_models_or_database():
    code=r'''
import importlib.abc,importlib.util,sys
class NoApplication(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith(('app.','hmu_core','hmu_identitas','sqlalchemy')):
   raise AssertionError('Public compiler imported runtime: '+fullname)
sys.meta_path.insert(0,NoApplication())
s=importlib.util.spec_from_file_location('settings_public_compiler','scripts/buat_kerangka_pengaturan.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.build()
'''
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
