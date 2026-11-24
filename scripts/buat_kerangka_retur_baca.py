"""Compile staff return read layouts from native labels; no app/DB/actor boot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined

ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/retur_baca_kerangka.py',ROOT/'app/web/retur_baca_catalog.py',ROOT/'app/web/layar_retur.py',ROOT/'app/web/layar_retur_asal.py'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    helper=module('retur_read_build_pool',ROOT/'scripts/buat_kerangka_ui.py')
    schema=module('retur_read_build_schema',ROOT/'app/web/retur_baca_kerangka.py')
    chrome=module('retur_read_chrome',ROOT/'scripts/stock_sosoh_native_chrome.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    compile_chrome=chrome.load(ROOT,env,inputs)
    originals={}
    for name in ['retur_daftar.html','retur_detail.html','retur_tiket.html','_detail_kirim_tabs.html','_barang_retur_kontrol.html','_retur_tiket_fakta.html']:
        originals[name]=env.loader.get_source(env,name)[0]
    for name in ['_pengiriman_kontrol.html','_pengiriman_tabs.html']:env.loader.get_source(env,name)
    for key,name,index in [('applications','retur_daftar.html',0),('receipts','retur_daftar.html',1),('items','retur_detail.html',0)]:
        tables=BeautifulSoup(originals[name],'html.parser').select('table thead')
        if len(tables)<=index or tuple(n.get_text() for n in tables[index].select('th'))!=schema.COLUMNS[key]:raise ValueError('Native return columns changed: '+key)
    tab_source=originals['_detail_kirim_tabs.html']
    if (any("('"+key+"','"+label+"')" not in tab_source for key,label in schema.TABS[:3])
            or schema.TABS[-1]!=('riwayat','Riwayat')
            or "('riwayat','Retur & riwayat' if jenis=='pengiriman' else 'Riwayat')" not in tab_source):raise ValueError('Native return detail tabs changed')
    base=(ROOT/'hmu_tampilan/templates/base.html').read_text()
    header=base[base.index('  {% if not kembali or LAPORAN_NAV %}'):base.index('  <span class="bar__merek"')]
    menu=env.from_string(header).render(kembali=None,LAPORAN_NAV=None)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Native local static asset required')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for kind,path,title in [('list','/retur','Barang Retur'),('receipt','/retur/1','Detail retur __PADI_CODE__'),('ticket','/retur/tiket/1','Tiket __PADI_CODE__')]:
        doc=BeautifulSoup(env.get_template('retur_baca_kerangka.html').render(kind=kind,columns=schema.COLUMNS,tabs=schema.TABS,VERSI='__PADI_CAP__'),'html.parser')
        # Reuse exact native control markup/geometry, but never initialize its
        # print/dialog controller before the fresh document. Native controllers
        # arrive once with data; pending controls explain their disabled state.
        for node in doc.select('script[src]'):
            if node['src'].split('?')[0]=='/static/pengiriman-kontrol.js':node.decompose()
        for node in doc.select('button:not([data-retur-baca-retry])'):
            node['disabled']='';node['aria-describedby']='retur-baca-reason'
        if len(doc.select('[data-retur-baca-native]'))!=1 or doc.select('form,input,select,textarea,[name],[data-detail-tab],[data-retur-form],[data-post],[data-kirim]'):raise ValueError('Read shape must not initialize return form')
        for link in doc.select('link[rel=stylesheet]'):
            css=asset(link['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Native CSS requires review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);link.replace_with(style)
        for script in doc.select('script[src]'):
            js=asset(script['src'])
            if 'document.currentScript' in js:raise ValueError('Read program binding needs review')
            script.attrs.clear();script.string=js.replace('</script','<\\/script')
        compiled=compile_chrome(path,{},title)
        variants[kind]=dict(html=str(doc),title=title,breadcrumb=compiled['breadcrumb'],header_menu=menu)
    styles,scripts,srefs,jrefs={},{},{},{}
    for variant in variants.values():
        doc=BeautifulSoup(variant['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-retur-style'),('script:not([type])',scripts,jrefs,'data-retur-script')]:
            for node in doc.select(selector):node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        variant['html']=str(doc)
    runtime=ROOT/'app/web/static/kerangka-retur-baca-ui-runtime.js';inputs.add(runtime)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Public native return read shapes; no record, transaction or role. */\nwindow.PadiKerangkaReturBacaData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+runtime.read_text()).encode()
    if len(payload)>524288:raise ValueError('Return read package needs size review')
    meta=dict(versi=1,sumber=source,variants=list(schema.VARIANTS),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,payload in zip(('kerangka-retur-baca-ui.js','kerangka-retur-baca-ui.meta.json'),build()):
        target=ROOT/'app/web/static'/name
        if args.check:
            if target.read_bytes()!=payload:raise AssertionError('Return read package stale: '+name)
        else:target.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
