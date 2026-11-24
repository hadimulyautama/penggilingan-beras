"""Compile public five-tab Jasa layout only; no app/DB/runtime import."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-jasa-detail-ui-runtime.js',
        ROOT/'app/web/jasa_detail_catalog.py',ROOT/'app/web/layar_jasa.py',ROOT/'app/services/jasa_pelanggan.py'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
    helper=module('jasa_public_pool_helpers',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('jasa_detail_public_spec',ROOT/'app/web/jasa_detail_kerangka.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only local native program assets')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for tab,_ in native.TABS:
        spec=native.deskripsi('/jasa/pelanggan/1','tab='+tab)
        spec.update(alamat='__PADI_DATA_URL__',stamp='__PADI_STAMP__',kembali='__PADI_BACK__',
            filter_pesanan=True,pesanan_cari='__PADI_ORDER_SEARCH__',rincian_cari='__PADI_DETAIL_SEARCH__')
        spec['tabs']=[dict(key=k,label=n,href='__PADI_TAB_'+k+'__',active=k==tab) for k,n in native.TABS]
        template=env.get_template('jasa_detail_kerangka.html')
        raw=''.join(template.blocks['isi'](template.new_context(dict(JASA_DETAIL_SHELL=spec,VERSI='__PADI_CAP__'))))
        doc=BeautifulSoup(native.kunci_cetak(raw.encode()),'html.parser')
        if doc.select('form,input[name],input[type=hidden],[data-post],[data-kirim]') or '/jasa/pelanggan/1' in str(doc):raise ValueError('Public layout may not contain customer/action data')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Stylesheet requires native review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            js=asset(node['src'])
            if 'document.currentScript' in js:raise ValueError('Native script binding requires review')
            node.attrs.clear();node.string=js.replace('</script','<\\/script')
        for link,(key,_) in zip(doc.select('.jasa-detail-tab>a'),native.TABS):link['data-jd-tab']=key
        filters=doc.select_one('.jasa-pesanan-filter')
        if filters:
            filters['data-jd-order-filter']='';filters.select_one('input')['data-jd-order-search']='';filters.select_one('select')['data-jd-order-status']=''
        for node in doc.select('input[aria-label="Cari catatan pelanggan"]'):node['data-jd-detail-search']=''
        variants[tab]=dict(title='Pesanan Jasa',html=str(doc))
    styles,scripts,srefs,jrefs={},{},{},{}
    for variant in variants.values():
        doc=BeautifulSoup(variant['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-jd-style'),('script:not([type])',scripts,jrefs,'data-jd-script')]:
            for node in doc.select(selector):
                node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        variant['html']=str(doc)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Data-free native Jasa customer layouts, private provenance is separate. */\nwindow.PadiKerangkaJasaDetailData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-jasa-detail-ui-runtime.js').read_text()).encode()
    if len(payload)>524288:raise ValueError('Jasa detail public package exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-jasa-detail-ui.js','kerangka-jasa-detail-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Jasa detail generated package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
