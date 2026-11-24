"""Compile only invariant native Home regions, never rows or machine DTOs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/beranda_kerangka.py',ROOT/'app/main.py',
        ROOT/'app/services/beranda.py',ROOT/'app/web/layar.py',ROOT/'hmu_tampilan/templates/beranda.html',
        ROOT/'hmu_tampilan/templates/base.html',ROOT/'app/web/static/kerangka-beranda-ui-runtime.js'}
    hp=ROOT/'scripts/buat_kerangka_ui.py';inputs.add(hp)
    spec=importlib.util.spec_from_file_location('home_public_pool',hp);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    bp=ROOT/'app/web/breadcrumb.py';inputs.add(bp)
    spec=importlib.util.spec_from_file_location('home_public_breadcrumb',bp);breadcrumb=importlib.util.module_from_spec(spec);spec.loader.exec_module(breadcrumb)
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    template=env.get_template('beranda_kerangka.html')
    context=dict(HOME_SHELL={'alamat':'/','stamp':'__PADI_STAMP__','sapaan':'__PADI_GREETING__','tanggal':'__PADI_DATE__','scope':'__PADI_SCOPE__'},VERSI='__PADI_CAP__')
    raw=''.join(template.blocks['isi'](template.new_context(context)));doc=BeautifulSoup(raw,'html.parser')
    if doc.select('form,input,select,textarea,[name],[data-post],[data-kirim],link[rel=stylesheet],iframe'):
        raise ValueError('Home structure cannot initialize data, forms or actions')
    for n in doc.select('script[src]'):
        name=n['src'].split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only reviewed local program allowed')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);text=path.read_text()
        if 'document.currentScript' in text:raise ValueError('Script binding needs native review')
        n.attrs.clear();n.string=text.replace('</script','<\\/script')
    scripts,refs={},{}
    for n in doc.select('script:not([type])'):n['data-home-script']=helper.intern_text(scripts,refs,n.string or '');n.clear()
    crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/',{},'Beranda'))
    variants={'/':dict(title='Beranda',brand='PT Hadi Mulya Utama',html=str(doc),breadcrumb=crumb)}
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,scripts=scripts)
    payload=('/* Home invariant structure program; native greeting and scope stay private. */\nwindow.PadiKerangkaBerandaData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-beranda-ui-runtime.js').read_text()).encode()
    if len(payload)>131072:raise ValueError('Home structure program exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,payload in zip(('kerangka-beranda-ui.js','kerangka-beranda-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if a.check:
            if path.read_bytes()!=payload:raise AssertionError('Native Home package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
