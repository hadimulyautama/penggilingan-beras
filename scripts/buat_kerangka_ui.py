"""Build public, data-free UI components from native partials; no app/DB import."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode,urlsplit

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,FileSystemLoader,StrictUndefined
from starlette.requests import Request

ROOT=Path(__file__).resolve().parents[1]
CAP='__PADI_CAP__'


class SourceLoader(FileSystemLoader):
    def __init__(self,path,inputs):
        super().__init__(str(path));self.inputs=inputs

    def get_source(self,environment,template):
        result=super().get_source(environment,template)
        self.inputs.add(Path(result[1]))
        return result


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-ui-runtime.js'}
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([SourceLoader(p/'templates',inputs) for p in roots]),
                    autoescape=True,undefined=StrictUndefined)
    def data_forbidden(*args,**kwargs):
        raise AssertionError('Blueprint must not format record data')
    env.filters.update(jam=data_forbidden)
    spec=importlib.util.spec_from_file_location('native_breadcrumb',ROOT/'app/web/breadcrumb.py')
    breadcrumb=importlib.util.module_from_spec(spec);spec.loader.exec_module(breadcrumb)
    inputs.add(ROOT/'app/web/breadcrumb.py')
    request=Request({'type':'http','method':'GET','path':'/barang-keluar',
        'scheme':'http','server':('ui.invalid',80),'headers':[],
        'query_string':urlencode({'q':'__PADI_SEARCH__','status':'__PADI_STATUS__',
            'sejak':'__PADI_DATE__','pelanggan_id':'__PADI_CUSTOMER__'}).encode()})

    def asset(path):
        u=urlsplit(path)
        assert not u.scheme and not u.netloc and u.path.startswith('/static/')
        name=u.path.removeprefix('/static/')
        assert name and '/' not in name and '\\' not in name
        p=next(p/'static'/name for p in roots if (p/'static'/name).is_file())
        inputs.add(p)
        return p.read_text()

    variants={}
    for key,admin in [('pengiriman-admin',True),('pengiriman-operator',False)]:
        context=dict(request=request,VERSI=CAP,PORTAL_READ_ONLY=False,
            tab_pengiriman='keluar',BOLEH_PERINTAH=admin,BOLEH_MUAT=not admin,
            pencarian='__PADI_SEARCH__',status_filter='__PADI_STATUS__',sejak_filter='__PADI_DATE__',
            n_perintah='…',n_dimuat='…',riwayat=[],daftar_keluar=[],pengiriman_memuat=True,
            SHELL=dict(stamp='__PADI_STAMP__',data_url='__PADI_DATA_URL__'))
        template=env.get_template('pengiriman_bertahap.html')
        html=''.join(template.blocks['isi'](template.new_context(context)))
        doc=BeautifulSoup(html,'html.parser')
        root=doc.select_one('[data-halaman-bertahap][data-kind="pengiriman"]')
        assert root and not doc.select('#formulir-sesi,input[name="_csrf"],form[method="post"],[data-post],[data-kirim]')
        css=[]
        for link in doc.select('link[rel="stylesheet"]'):
            text=asset(link['href'])
            assert '@import' not in text and '</style' not in text.lower()
            css.append(text);link.decompose()
        style=doc.new_tag('style',attrs={'data-kerangka-ui-style':'pengiriman'})
        style.string='\n'.join(css);root.insert(0,style)
        for node in doc.select('script[src]'):
            text=asset(node['src'])
            assert 'document.currentScript' not in text
            node.attrs.clear();node.string=text.replace('</script','<\\/script')
        for node in root.select('[data-bk-cetak]'):
            node['disabled']='';node['aria-describedby']='shell-cetak-alasan'
        for node in root.select('.bk-chip'):
            if '__PADI_STATUS__' in node.get_text():node['data-ui-status']=''
            if '__PADI_DATE__' in node.get_text():node['data-ui-date']=''
        html=str(doc)
        assert 'ui.invalid' not in html and len(html.encode())<=524288
        assert len(doc.select('thead th'))==11
        crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(
            '/barang-keluar',{'PENGIRIMAN_URL':'/barang-keluar'},'Barang Keluar'))
        variants[key]=dict(family='pengiriman',path='/barang-keluar',title='Barang Keluar',
                           html=html,breadcrumb=crumb)
    # STATUS is a product literal, never imported through the app/DB runtime.
    source=ROOT/'app/services/jasa_pelanggan.py';inputs.add(source)
    statuses=next(ast.literal_eval(node.value) for node in ast.parse(source.read_text()).body
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='STATUS' for t in node.targets))
    context=dict(VERSI=CAP,tapis='__PADI_STATUS__',cari='__PADI_SEARCH__',
        STATUS_PILIHAN=statuses,JASA_SHELL=dict(stamp='__PADI_STAMP__',url='__PADI_DATA_URL__',filtered=False))
    template=env.get_template('jasa_bertahap.html')
    doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))),'html.parser')
    root=doc.select_one('[data-jasa-bertahap]');assert root and not root.select('h1')
    css=[]
    for link in doc.select('link[rel="stylesheet"]'):
        text=asset(link['href']);assert '@import' not in text and '</style' not in text.lower()
        css.append(text);link.decompose()
    style=doc.new_tag('style',attrs={'data-kerangka-ui-style':'jasa'});style.string='\n'.join(css);root.insert(0,style)
    for node in doc.select('script[src]'):
        text=asset(node['src']);assert 'document.currentScript' not in text
        node.attrs.clear();node.string=text.replace('</script','<\\/script')
    for node in root.select('[data-js-cetak]'):
        node['disabled']='';node['aria-describedby']='jasa-cetak-alasan'
    scope=root.select_one('.js-cakupan');assert scope;scope['data-ui-jasa-status']=''
    crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/jasa',{},'Pesanan Jasa'))
    variants['jasa-admin']=dict(family='jasa',path='/jasa',title='Pesanan Jasa',html=str(doc),breadcrumb=crumb,
        statuses=[key for key,_ in statuses])
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=digest,variants=variants)
    runtime=(ROOT/'app/web/static/kerangka-ui-runtime.js').read_text()
    payload=('/* Generated native UI only. Regenerate with scripts/buat_kerangka_ui.py. */\n'
             +'window.PadiKerangkaUIData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'
             +runtime).encode()
    assert len(payload)<=1572864
    metadata=dict(versi=1,sumber=digest,aset_sha256=hashlib.sha256(payload).hexdigest(),
                  variants=list(variants),inputs=hashes)
    return payload,(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    outputs=zip(('kerangka-ui.js','kerangka-ui.meta.json'),build())
    for name,payload in outputs:
        path=ROOT/'app/web/static'/name
        if args.check:
            assert path.read_bytes()==payload,'Generated UI asset differs: '+name
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')


if __name__=='__main__':main()
