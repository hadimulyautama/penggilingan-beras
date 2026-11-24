"""Compile active READ shipping layout/provenance only; no app/model/DB boot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/pengiriman_detail_catalog.py',ROOT/'app/web/layar_keluar.py',
            ROOT/'app/web/templates/_pengiriman_detail_tab.html'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
    helper=module('shipping_public_pool',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('shipping_public_spec',ROOT/'app/web/pengiriman_detail_kerangka.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Local program assets only')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for command in (False,True):
        # Schema placeholders, never fake record/actor/weight/count or route ID.
        spec=dict(alamat='__PADI_DATA_URL__',stamp='__PADI_STAMP__',kembali='__PADI_BACK__',tab='ringkasan',
            meta=dict(kode='__PADI_CODE__',keadaan='__PADI_STATE__',jasa=False,cepat=False,bersama=False,actions=[],boleh_perintah=command),
            tabs=[dict(key=k,label=n,href='__PADI_TAB_'+k+'__',active=k=='ringkasan') for k,n in native.TABS])
        template=env.get_template('pengiriman_detail_kerangka.html')
        raw=''.join(template.blocks['isi'](template.new_context(dict(PD=spec,VERSI='__PADI_CAP__'))));doc=BeautifulSoup(raw,'html.parser')
        if doc.select('form,input,select,textarea,[data-post],[data-kirim]') or '/barang-keluar/1' in str(doc):raise ValueError('Public shipping layout contains record/action state')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Native CSS requires review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            js=asset(node['src'])
            if 'document.currentScript' in js:raise ValueError('Script binding requires review')
            node.attrs.clear();node.string=js.replace('</script','<\\/script')
        variants['command' if command else 'read']=dict(html=str(doc))
    styles,scripts,srefs,jrefs={},{},{},{}
    for variant in variants.values():
        doc=BeautifulSoup(variant['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-pd-style'),('script:not([type])',scripts,jrefs,'data-pd-script')]:
            for node in doc.select(selector):node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        variant['html']=str(doc)
    runtime_path=ROOT/'app/web/static/kerangka-pengiriman-detail-ui-runtime.js';inputs.add(runtime_path)
    runtime=runtime_path.read_text();adapter=asset('/static/pengiriman-detail-native.js')
    start=adapter.index(' function address(value,origin){')+len(' function address(value,origin){')
    end=adapter.index('\n function holdActions(',start)
    address_body=adapter[start:end].strip().removesuffix('}').rstrip()
    marker='/*__PADI_NATIVE_READ_ADDRESS__*/'
    if runtime.count(marker)!=1 or not address_body.endswith('return {u,id:Number(m[1]),tab:q.get(\'tab_detail\')||\'ringkasan\'};'):
        raise ValueError('Read allowlist extraction changed; review required')
    runtime=runtime.replace(marker,address_body)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Public data-free active shipping layouts. */\nwindow.PadiKerangkaPengirimanDetailData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+runtime).encode()
    if len(payload)>524288:raise ValueError('Active shipping package exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-pengiriman-detail-ui.js','kerangka-pengiriman-detail-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Shipping detail package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
