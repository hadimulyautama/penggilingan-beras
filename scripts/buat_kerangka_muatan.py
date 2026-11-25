"""Compile inert native Muatan columns/controls, never outbound rows or editor."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/muatan_kerangka.py',ROOT/'app/web/muatan.py',
        ROOT/'app/web/selesai_muatan.py',ROOT/'app/web/api.py',ROOT/'app/peran.py',
        ROOT/'app/web/templates/catat_muatan.html',ROOT/'app/web/templates/_lembar_muatan.html',
        ROOT/'app/web/static/muat-ringkas.js',ROOT/'hmu_tampilan/templates/base.html',
        ROOT/'app/web/static/kerangka-muatan-ui-runtime.js'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
    helper=module('muat_public_pool',ROOT/'scripts/buat_kerangka_ui.py')
    breadcrumb=module('muat_public_breadcrumb',ROOT/'app/web/breadcrumb.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    template=env.get_template('muatan_kerangka.html');styles,scripts,srefs,jrefs={},{},{},{}
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only reviewed local program allowed')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={};parts={}
    for mode in ('read','record'):
        context=dict(MUAT_SHELL={'alamat':'/muatan','stamp':'__PADI_STAMP__','can_record':mode=='record'},VERSI='__PADI_CAP__')
        doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))),'html.parser')
        if doc.select('form,input,select,textarea,[name],[data-post],[data-kirim],[data-editor-perintah],[data-lembar-muatan],[data-catat-muatan],#lembar-awal,iframe'):
            raise ValueError('Pending Muatan cannot initialize native data/editor/actions')
        if any(not n.has_attr('disabled') for n in doc.select('button:not([data-muat-native-retry])')):
            raise ValueError('Pending controls must be inert')
        for n in doc.select('link[rel=stylesheet]'):
            css=asset(n['href'])
            if '@import' in css or 'url(' in css or '</style' in css.lower():raise ValueError('Native CSS needs review')
            style=doc.new_tag('style');style.string=css;n.replace_with(style)
        for n in doc.select('script[src]'):
            text=asset(n['src'])
            if 'document.currentScript' in text:raise ValueError('Script binding needs native review')
            n.attrs.clear();n.string=text.replace('</script','<\\/script')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-muat-style'),('script:not([type])',scripts,jrefs,'data-muat-script')]:
            for n in doc.select(selector):n[attr]=helper.intern_text(pool,refs,n.string or '');n.clear()
        parts[mode]=str(doc)
    crumbs={p:env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/muatan',{'PENGIRIMAN_URL':p},'Catat muatan')) for p in ('/muatan','/barang-keluar')}
    variants['/muatan']=dict(title='Catat muatan',brand='Catat muatan',**parts,breadcrumbs=crumbs)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,scripts=scripts,styles=styles)
    payload=('/* Muatan invariant layout; exact native guard stays private. */\nwindow.PadiKerangkaMuatanData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-muatan-ui-runtime.js').read_text()).encode()
    if len(payload)>131072:raise ValueError('Muatan structure program exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,payload in zip(('kerangka-muatan-ui.js','kerangka-muatan-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if a.check:
            if path.read_bytes()!=payload:raise AssertionError('Native Muatan package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
