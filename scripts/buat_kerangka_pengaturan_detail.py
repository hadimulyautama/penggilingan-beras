"""Source-only six-route Settings compiler; no app imports or configured data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-pengaturan-detail-ui-runtime.js',ROOT/'app/web/pengaturan.py',
        ROOT/'hmu_tampilan/templates/pengaturan.html',ROOT/'hmu_tampilan/templates/_pengaturan_formulir.html',ROOT/'hmu_tampilan/templates/_daftar_akses.html'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
    helper=module('detail_settings_pool',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('detail_settings_shape',ROOT/'app/web/pengaturan_detail_kerangka.py')
    source=module('detail_settings_references',ROOT/'app/web/pengaturan_detail_schema.py')
    breadcrumb=module('detail_settings_breadcrumb',ROOT/'app/web/breadcrumb.py')
    refs=source.load(ROOT);inputs.update(ROOT/p for p in source.SOURCES)
    if native.PATHS!=source.PATHS or native.VARIANTS!=source.VARIANTS:raise ValueError('Native schema declarations require review')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only local program assets')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for variant in source.VARIANTS:
        kind='peran' if variant.startswith('peran-') else 'sistem' if variant.startswith('sistem-') else variant
        flags=dict(tuan=variant!='sistem-umum',peran='gudang' if variant=='peran-gudang' else 'lihat',**refs)
        spec=native.spesifikasi('/pengaturan/'+kind,native=flags)
        if spec['variant']!=variant:raise ValueError('Variant condition mismatch')
        template=env.get_template('pengaturan_detail_kerangka.html')
        raw=''.join(template.blocks['isi'](template.new_context(dict(PG_DETAIL_SHELL={**spec,'stamp':'__PADI_STAMP__'},VERSI='__PADI_CAP__'))))
        doc=BeautifulSoup(raw,'html.parser')
        if doc.select('form,[name],input[type=hidden],[data-post],[data-kirim],[aria-checked]'):raise ValueError('No writes or assumed configuration state')
        if any(not n.has_attr('disabled') or n.has_attr('value') for n in doc.select('input,select,textarea')):raise ValueError('Unknown fields must stay disabled and valueless')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Styles require review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            js=asset(node['src'])
            if 'document.currentScript' in js:raise ValueError('Script binding requires review')
            node.attrs.clear();node.string=js.replace('</script','<\\/script')
        crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(spec['alamat'],{},'Pengaturan'))
        variants[variant]=dict(title='Pengaturan',html=str(doc),breadcrumb=crumb)
    styles,scripts,srefs,jrefs={},{},{},{}
    for component in variants.values():
        doc=BeautifulSoup(component['html'],'html.parser')
        for selector,pool,refs_,attr in [('style',styles,srefs,'data-settings-detail-style'),('script:not([type])',scripts,jrefs,'data-settings-detail-script')]:
            for node in doc.select(selector):node[attr]=helper.intern_text(pool,refs_,node.string or '');node.clear()
        component['html']=str(doc)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    references={k:refs[k] for k in ('columns','processes')}
    data=dict(versi=1,sumber=digest,variants=variants,styles=styles,scripts=scripts,references=references)
    payload=('/* Native Settings detail structure only; configured values remain unread. */\nwindow.PadiKerangkaPengaturanDetailData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-pengaturan-detail-ui-runtime.js').read_text()).encode()
    if len(payload)>262144:raise ValueError('Settings detail package exceeds bound')
    meta=dict(versi=1,sumber=digest,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),references=references,inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-pengaturan-detail-ui.js','kerangka-pengaturan-detail-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Settings detail generated package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
