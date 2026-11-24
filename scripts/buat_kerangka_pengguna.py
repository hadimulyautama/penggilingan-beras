"""Five inert native user layouts; no identity/configuration/domain reads."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-pengguna-ui-runtime.js',ROOT/'app/web/pengguna.py',ROOT/'app/web/portal/admin.py',ROOT/'app/web/security.py'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
    native=module('native_users_pure',ROOT/'app/web/pengguna_baca_native.py')
    source=module('native_users_labels',ROOT/'app/web/pengguna_baca_schema.py')
    pool=module('native_users_pool',ROOT/'scripts/buat_kerangka_ui.py')
    breadcrumb=module('native_users_breadcrumb',ROOT/'app/web/breadcrumb.py')
    chrome=module('native_users_chrome',ROOT/'app/web/native_detail_chrome.py')
    refs=source.load(ROOT);inputs.update(ROOT/p for p in source.SOURCES)
    base=ROOT/'hmu_tampilan/templates/base.html';inputs.add(base)
    bar=chrome.kontrol_bar(base.read_text(),laporan=False)
    env=Environment(loader=ChoiceLoader([pool.SourceLoader(p/'templates',inputs) for p in (ROOT/'app/web',ROOT/'hmu_tampilan')]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Hanya aset pengguna lokal')
        path=next(p/'static'/name for p in (ROOT/'app/web',ROOT/'hmu_tampilan') if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for variant in source.VARIANTS:
        path='/pengguna' if variant in {'staf','staf-super'} else '/pengguna/1' if variant=='staf-detail' else '/pengguna/pelanggan' if variant=='pelanggan' else '/pengguna/pelanggan/1'
        spec=native.spesifikasi(path)
        spec.update(variant=variant,title=refs['titles'][variant],nama='__PADI_NAMA__' if variant=='staf-detail' else '',customer=variant!='staf',roles=refs['roles'],columns=refs['columns'],stamp='__PADI_STAMP__')
        template=env.get_template('pengguna_baca_native.html')
        raw=''.join(template.blocks['isi'](template.new_context(dict(PENGGUNA_BACA=spec,VERSI='__PADI_CAP__'))))
        doc=BeautifulSoup(raw,'html.parser')
        if doc.select('form,[name],input[type=hidden],[data-post],[data-kirim]'):raise ValueError('Bentuk pengguna tidak boleh berisi penulis/kunci akun')
        if any(not n.has_attr('disabled') or n.has_attr('value') for n in doc.select('input,select,textarea') if not n.has_attr('data-pengguna-cari')):raise ValueError('Nilai pengguna belum diketahui')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Gaya pengguna perlu review')
            style=doc.new_tag('style');style.string=pool.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            script=asset(node['src'])
            if 'document.currentScript' in script:raise ValueError('Program pengguna perlu binding native')
            node.attrs.clear();node.string=script.replace('</script','<\\/script')
        crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(path,dict(kembali=spec['kembali']),spec['title']))
        variants[variant]=dict(title=spec['title'],html=str(doc),breadcrumb=crumb,bar=bar,kembali=spec['kembali'])
    styles,scripts,sr,jr={},{},{},{}
    for component in variants.values():
        doc=BeautifulSoup(component['html'],'html.parser')
        for selector,values,refs_,attr in [('style',styles,sr,'data-users-style'),('script:not([type])',scripts,jr,'data-users-script')]:
            for node in doc.select(selector):node[attr]=pool.intern_text(values,refs_,node.string or '');node.clear()
        component['html']=str(doc)
        if len(component['html'].encode())>65536:raise ValueError('Bentuk pengguna melewati batas')
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=digest,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Bentuk pengguna publik tanpa identitas, akun, token atau nilai izin. */\nwindow.PadiKerangkaPenggunaData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-pengguna-ui-runtime.js').read_text()).encode()
    if len(payload)>262144:raise ValueError('Paket pengguna melewati batas')
    meta=dict(versi=1,sumber=digest,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-pengguna-ui.js','kerangka-pengguna-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Paket pengguna basi: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload))
