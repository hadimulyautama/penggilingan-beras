"""Build public, data-free UI components from native partials; no app/DB import."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import urlencode,urlsplit

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,FileSystemLoader,StrictUndefined
from starlette.requests import Request

ROOT=Path(__file__).resolve().parents[1]
CAP='__PADI_CAP__'


def compact_css_comments(text):
    """Compact only inert comment bodies; leave CSS tokens/spacing untouched.

    Keep the comment delimiter as /**/ so adjacent tokens cannot merge. All
    quoted strings, escapes and parenthesized contents (including URL/calc)
    are copied unchanged; this is deliberately not a CSS minifier.
    """
    out=[];i=0;quote='';depth=0
    while i<len(text):
        char=text[i]
        if char=='\\':
            out.append(text[i:i+2]);i+=2;continue
        if quote:
            out.append(char)
            if char==quote:quote=''
            i+=1;continue
        if char in {'\"', "'"}:
            quote=char;out.append(char);i+=1;continue
        if text.startswith('/*',i):
            end=text.find('*/',i+2)
            if end<0:raise ValueError('Unclosed CSS comment in public UI input')
            out.append(text[i:end+2] if depth else '/**/');i=end+2;continue
        if char=='(':depth+=1
        elif char==')':depth=max(0,depth-1)
        out.append(char);i+=1
    return ''.join(out)


def intern_text(pool, references, text):
    """Opaque short references; full SHA still deduplicates exact content.

    The runtime treats these as lookup keys, not hashes or authorization.
    Native input SHA/CAP and complete generated-asset SHA remain unchanged
    contracts in the manifest; deterministic numbering avoids repeated
    random 64-byte strings in public HTML across every layout variant.
    """
    digest=hashlib.sha256(text.encode()).hexdigest()
    if digest in references:
        key=references[digest]
        assert pool[key]==text, 'Public UI content hash collision'
        return key
    key=str(len(pool));references[digest]=key;pool[key]=text
    return key


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

    def css_asset(path, seen=()):
        # Resolve native local imports at build time. No request is needed
        # after a click, and remote/recursive/media imports stay unsupported.
        name=urlsplit(path).path
        assert name not in seen and len(seen)<8
        text=asset(path)
        pattern=r"@import\s+url\(['\"](/static/[^'\"]+)['\"]\);"
        text=re.sub(pattern,lambda match:css_asset(match[1],(*seen,name)),text)
        assert '@import' not in text and '</style' not in text.lower()
        return text

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
    # Account values/form tokens are intentionally absent from this block.
    context=dict(VERSI=CAP,AKUN_KERANGKA=dict(kind='pengaturan-akun',
        title='Nama & kata sandi',alamat='/pengaturan/akun',kembali='/pengaturan',
        sandi='/ganti-sandi?kembali_pengaturan=/pengaturan/akun',
        stamp='__PADI_STAMP__',data_url='/pengaturan/akun'))
    template=env.get_template('pengaturan_akun_kerangka.html')
    doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))),'html.parser')
    root=doc.select_one('[data-pengaturan-akun-kerangka]');assert root
    css=[]
    for link in doc.select('link[rel="stylesheet"]'):
        text=asset(link['href']);assert '@import' not in text and '</style' not in text.lower()
        css.append(text);link.decompose()
    style=doc.new_tag('style',attrs={'data-kerangka-ui-style':'akun'});style.string='\n'.join(css);root.insert(0,style)
    for node in doc.select('script[src]'):
        text=asset(node['src']);assert 'document.currentScript' not in text
        node.attrs.clear();node.string=text.replace('</script','<\\/script')
    assert not root.select('input[name],input[value],form[action],form[method],input[type=password]')
    crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/pengaturan/akun',{},'Pengaturan'))
    variants['akun-pribadi']=dict(family='akun',path='/pengaturan/akun',title='Pengaturan',html=str(doc),breadcrumb=crumb)
    spec=importlib.util.spec_from_file_location('public_stock_blueprint',ROOT/'scripts/stock_ui_blueprint.py')
    stock=importlib.util.module_from_spec(spec);spec.loader.exec_module(stock)
    inputs.update(stock.compiler_inputs())
    request=Request({'type':'http','method':'GET','path':'/stok',
        'scheme':'http','server':('ui.invalid',80),'headers':[],
        'query_string':urlencode({'cari':'__PADI_SEARCH__'}).encode()})
    for tab in ('bahan','produk','karung'):
      for mutu in (False,True):
       for owner in (False,True):
        context=stock.context(tab,mutu=mutu,ownership_layout=owner)
        context.update(request=request,VERSI=CAP)
        template=env.get_template('halaman_bertahap.html')
        html=''.join(template.blocks['isi'](template.new_context(context)))
        doc=BeautifulSoup(stock.prepare_markup(html),'html.parser')
        root=doc.select_one('[data-halaman-bertahap][data-kind="stok"]');root['data-ui-stock-public']=''
        css=[]
        for link in doc.select('link[rel="stylesheet"]'):
            text=asset(link['href']);assert '@import' not in text and '</style' not in text.lower()
            css.append(text);link.decompose()
        style=doc.new_tag('style',attrs={'data-kerangka-ui-style':'stok'});style.string='\n'.join(css);root.insert(0,style)
        control=doc.new_tag('script');control.string=asset('/static/kerangka-stok-controls.js').replace('</script','<\\/script')
        doc.select_one('script[src]').insert_before(control)
        for node in doc.select('script[src]'):
            text=asset(node['src']);assert 'document.currentScript' not in text
            node.attrs.clear();node.string=text.replace('</script','<\\/script')
        crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/stok?tab='+tab,{},'Stok'))
        variants[f'stok-{tab}-{int(mutu)}-{int(owner)}']=dict(family='stok',path='/stok',title='Stok',html=str(doc),breadcrumb=crumb,tab=tab)
    spec=importlib.util.spec_from_file_location('public_catalog',ROOT/'scripts/kerangka_laporan_katalog.py')
    catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)
    public=catalog.metadata(ROOT);inputs.update(ROOT/name for name in catalog.source_pins(ROOT))
    # Pending means no sidebar history choice is resolved from source/storage.
    # Native fresh GET supplies the actual actor's navigation. The catalog's
    # thirteen metadata-only links follow the verified uang=False contract.
    pending=dict(aktif='laporan',judul='Laporan periode',jenis='laporan',detail=False,
        panduan='lk-panduan',pilihan=[],boleh_alamat=['/laporan'],tab=[])
    context=dict(VERSI=CAP,KATALOG_STAMP='__PADI_STAMP__',KATALOG_NAV=pending,
                 KATALOG_NATIVE=''.join(env.get_template('laporan.html').blocks['isi'](
                     env.get_template('laporan.html').new_context(public))),TAMPILAN_INDUK=True)
    template=env.get_template('laporan_katalog_bertahap.html')
    doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))),'html.parser')
    root=doc.select_one('[data-laporan-katalog-kerangka]');assert root and not root.select('h1,table,form')
    css=[]
    for link in doc.select('link[rel="stylesheet"]'):
        text=asset(link['href']);assert '@import' not in text and '</style' not in text.lower()
        css.append(text);link.decompose()
    style=doc.new_tag('style',attrs={'data-kerangka-ui-style':'laporan'});style.string='\n'.join(css);root.insert(0,style)
    for node in doc.select('script[src]'):
        text=asset(node['src']);assert 'document.currentScript' not in text
        node.attrs.clear();node.string=text.replace('</script','<\\/script')
    crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/laporan',{},'Laporan periode'))
    catalog_codes=[row['kode'] for row in public['daftar']]
    variants['laporan-katalog']=dict(family='laporan',path='/laporan',title='Laporan periode',html=str(doc),breadcrumb=crumb,codes=catalog_codes)
    spec=importlib.util.spec_from_file_location('giling_public_spec',ROOT/'app/web/giling_native_html.py')
    giling=importlib.util.module_from_spec(spec);spec.loader.exec_module(giling)
    inputs.add(ROOT/'app/web/giling_native_html.py')
    layout=giling.deskripsi('/proses-aktif/giling/PADI_CODE_PLACEHOLDER')
    layout['stamp']='__PADI_STAMP__'
    context=dict(VERSI=CAP,GILING_KERANGKA=layout,kembali='/pekerjaan?tab=berjalan')
    template=env.get_template('giling_native_html.html')
    doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))),'html.parser')
    root=doc.select_one('[data-giling-native-html]');assert root and not root.select('form,input:not([disabled])')
    css=[]
    for link in doc.select('link[rel="stylesheet"]'):
        text=css_asset(link['href'])
        css.append(text);link.decompose()
    style=doc.new_tag('style',attrs={'data-kerangka-ui-style':'giling'});style.string='\n'.join(css);root.insert(0,style)
    for node in doc.select('script[src]'):
        text=asset(node['src']);assert 'document.currentScript' not in text
        node.attrs.clear();node.string=text.replace('</script','<\\/script')
    crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun('/proses-aktif/giling/PADI_CODE_PLACEHOLDER',{'breadcrumb_detail':'PADI_CODE_PLACEHOLDER'},'Penggilingan PADI_CODE_PLACEHOLDER'))
    variants['giling-proses']=dict(family='giling',path='/proses-aktif/giling/',title='Penggilingan',html=str(doc),breadcrumb=crumb)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    # Intern the actual CSS/readonly JS once, not once per layout variant.
    # Restore synchronously from this already-loaded public asset before swap.
    styles,scripts={},{}
    style_references,script_references={},{}
    for component in variants.values():
        doc=BeautifulSoup(component['html'],'html.parser')
        for selector,pool,references,attribute in [('style',styles,style_references,'data-ui-style-ref'),('script:not([type])',scripts,script_references,'data-ui-script-ref')]:
            for node in doc.select(selector):
                text=node.string or ''
                if selector=='style':text=compact_css_comments(text)
                key=intern_text(pool,references,text)
                node.clear();node[attribute]=key
        component['html']=str(doc)
    data=dict(versi=1,sumber=digest,variants=variants,styles=styles,scripts=scripts)
    runtime=(ROOT/'app/web/static/kerangka-ui-runtime.js').read_text()
    payload=('/* Generated native UI only. Regenerate with scripts/buat_kerangka_ui.py. */\n'
             +'window.PadiKerangkaUIData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'
             +runtime).encode()
    assert len(payload)<=1572864
    metadata=dict(versi=1,sumber=digest,aset_sha256=hashlib.sha256(payload).hexdigest(),
                  variants=list(variants),inputs=hashes,laporan_codes=catalog_codes)
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
