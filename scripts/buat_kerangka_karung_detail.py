"""Data-free native karung source-list package; no application/DB/actor import."""
import argparse,hashlib,importlib.util,json,re
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-karung-detail-ui-runtime.js',ROOT/'app/web/karung_detail_native.py'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
    helper=module('karung_build_helpers',ROOT/'scripts/buat_kerangka_ui.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    chrome=module('karung_native_chrome',ROOT/'scripts/stock_sosoh_native_chrome.py').load(ROOT,env,inputs)
    for name in ['app/web/templates/karung_detail_sumber.html','app/web/templates/_kepemilikan_sumber_daftar.html','app/web/templates/_retur_supplier_navigasi.html','hmu_tampilan/templates/_stok.html']:
        inputs.add(ROOT/name)
    doc=BeautifulSoup(env.get_template('karung_detail_native.html').render(DETAIL_URL='__PADI_URL__',DETAIL_STAMP='__PADI_STAMP__',VERSI='__PADI_CAP__'),'html.parser')
    if len(doc.select('[data-karung-detail-native]'))!=1 or doc.select('form,input,select,textarea,[data-kod-awal],[data-kepemilikan-sumber],[data-post],[data-kirim]'):raise ValueError('Karung source-list must not initialize source editor')
    native_menu=env.loader.get_source(env,'_retur_supplier_navigasi.html')[0]
    menu=re.search(r'<template data-rsp-menu>(.*?)</template>',native_menu,re.S)
    if menu is None or '{{' in menu[1] or '{%' in menu[1]:raise ValueError('Native combined menu/Back needs review')
    css=ROOT/'app/web/static/retur-supplier-menu.css';inputs.add(css)
    style=doc.new_tag('style');style.string=css.read_text();doc.insert(0,style)
    for script in doc.select('script[src]'):
        name=script['src'].split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Native local read program required')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);text=path.read_text()
        if 'document.currentScript' in text:raise ValueError('Program binding requires review')
        script.attrs.clear();script.string=text.replace('</script','<\\/script')
    styles,scripts,srefs,jrefs={},{},{},{}
    for selector,pool,refs,attr in [('style',styles,srefs,'data-karung-style'),('script:not([type])',scripts,jrefs,'data-karung-script')]:
        for node in doc.select(selector):node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
    title='Detail karung kosong';component=dict(html=str(doc),title=title,menu_markup=menu[1],**chrome('/stok/karung/detail',dict(kembali='/stok?tab=karung'),title))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)};source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,component=component,styles=styles,scripts=scripts)
    payload=('/* Native source-list structure only; no source editor state. */\nwindow.PadiKerangkaKarungDetailData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-karung-detail-ui-runtime.js').read_text()).encode()
    if len(payload)>524288:raise ValueError('Karung source-list program size requires review')
    meta=dict(versi=1,sumber=source,aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-karung-detail-ui.js','kerangka-karung-detail-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Karung detail structure stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
