"""Compile two inert master layouts from source only; no app imports/DB."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-pengaturan-master-ui-runtime.js',
        ROOT/'app/web/spesifikasi_beras.py',ROOT/'app/web/jenis_hasil_samping.py',
        ROOT/'app/web/templates/spesifikasi_beras.html',ROOT/'app/web/templates/jenis_hasil_samping.html'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
    helper=module('master_public_pool',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('master_public_spec',ROOT/'app/web/pengaturan_master_kerangka.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only local native program assets')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for path in native.PATHS:
        spec={**native.spesifikasi(path),'stamp':'__PADI_STAMP__'}
        template=env.get_template('pengaturan_master_kerangka.html')
        raw=''.join(template.blocks['isi'](template.new_context(dict(PG_MASTER_SHELL=spec,VERSI='__PADI_CAP__'))))
        doc=BeautifulSoup(raw,'html.parser')
        if doc.select('form,[name],input[type=hidden],[data-post],[data-kirim]'):raise ValueError('No writes in master layout')
        if any(not n.has_attr('disabled') or n.has_attr('value') for n in doc.select('input,select,textarea')):raise ValueError('Unread fields must be disabled and valueless')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Stylesheet needs native review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            js=asset(node['src'])
            if 'document.currentScript' in js:raise ValueError('Script binding needs native review')
            node.attrs.clear();node.string=js.replace('</script','<\\/script')
        variants[path]=dict(title=spec['title'],html=str(doc))
    styles,scripts,srefs,jrefs={},{},{},{}
    for variant in variants.values():
        doc=BeautifulSoup(variant['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-master-style'),('script:not([type])',scripts,jrefs,'data-master-script')]:
            for node in doc.select(selector):node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        variant['html']=str(doc)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Data-free master layouts; permission metadata is private. */\nwindow.PadiKerangkaPengaturanMasterData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-pengaturan-master-ui-runtime.js').read_text()).encode()
    if len(payload)>262144:raise ValueError('Master layout package exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-pengaturan-master-ui.js','kerangka-pengaturan-master-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Master layout package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
