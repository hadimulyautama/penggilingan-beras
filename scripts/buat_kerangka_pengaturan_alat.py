"""Compile the data-free native Alat hub, without importing app/runtime/DB."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/pengaturan_alat_kerangka.py',ROOT/'app/web/pengaturan.py',
        ROOT/'app/web/security.py',ROOT/'hmu_tampilan/templates/alat.html',ROOT/'app/web/static/kerangka-pengaturan-alat-ui-runtime.js'}
    helper_path=ROOT/'scripts/buat_kerangka_ui.py';inputs.add(helper_path)
    spec=importlib.util.spec_from_file_location('alat_public_pool',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    breadcrumb_path=ROOT/'app/web/breadcrumb.py';inputs.add(breadcrumb_path)
    spec=importlib.util.spec_from_file_location('alat_public_breadcrumb',breadcrumb_path);breadcrumb=importlib.util.module_from_spec(spec);spec.loader.exec_module(breadcrumb)
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    template=env.get_template('pengaturan_alat_kerangka.html')
    raw=''.join(template.blocks['isi'](template.new_context(dict(ALAT_SHELL={'alamat':'/pengaturan/alat','stamp':'__PADI_STAMP__'},VERSI='__PADI_CAP__'))))
    doc=BeautifulSoup(raw,'html.parser')
    if doc.select('form,input,select,textarea,[name],[data-post],[data-kirim],link[rel=stylesheet]'):raise ValueError('Alat hub is a fixed link layout only')
    for node in doc.select('script[src]'):
        name=node['src'].split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only local program assets')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);js=path.read_text()
        if 'document.currentScript' in js:raise ValueError('Script binding needs native review')
        node.attrs.clear();node.string=js.replace('</script','<\\/script')
    scripts,refs={},{}
    for node in doc.select('script:not([type])'):node['data-alat-script']=helper.intern_text(scripts,refs,node.string or '');node.clear()
    crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/pengaturan/alat',dict(kembali='/pengaturan'),'Pengaturan alat'))
    variants={'/pengaturan/alat':dict(title='Pengaturan alat',html=str(doc),breadcrumb=crumb)}
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles={},scripts=scripts)
    payload=('/* Public native Alat hub; super authority metadata stays private. */\nwindow.PadiKerangkaPengaturanAlatData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-pengaturan-alat-ui-runtime.js').read_text()).encode()
    if len(payload)>131072:raise ValueError('Alat hub package exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-pengaturan-alat-ui.js','kerangka-pengaturan-alat-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Alat hub package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
