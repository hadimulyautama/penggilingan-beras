"""First-click facility parent layouts only; source compiler imports no app runtime/DB."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]


def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/fasilitas.py',ROOT/'app/web/security.py',ROOT/'app/web/templates/fasilitas.html',ROOT/'app/web/templates/_fasilitas_form.html',ROOT/'app/web/templates/_fasilitas_parent_empty.html',ROOT/'app/web/pengaturan.py',ROOT/'hmu_tampilan/templates/gudang_pengaturan.html',ROOT/'app/web/templates/silo_pengaturan.html',ROOT/'app/web/static/kerangka-fasilitas-parent-ui-runtime.js'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
    helper=module('facility_parent_pool',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('facility_parent_spec',ROOT/'app/web/fasilitas_parent_kerangka.py')
    breadcrumb=module('facility_parent_breadcrumb',ROOT/'app/web/breadcrumb.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only local program assets')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    variants={}
    for address in native.TARGETS:
        shape=native.blueprint(address);title=shape['title']
        template=env.get_template('fasilitas_parent_kerangka.html')
        raw=''.join(template.blocks['isi'](template.new_context(dict(FP_SHELL=shape,VERSI='__PADI_CAP__',**{name:getattr(env.get_template('_fasilitas_parent_fields.html').module,name) for name in ('input','active','identity')}))))
        doc=BeautifulSoup(raw,'html.parser')
        if doc.select('form,[name],input[value],input[type=hidden],[data-post],[data-kirim],[data-simpan-alat],[data-pengaturan-form]'):raise ValueError('No writes/operation keys in pending line detail')
        if any(not n.has_attr('disabled') for n in doc.select('input,select,textarea')):raise ValueError('Pending fields must be disabled')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('Styles require native review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            js=asset(node['src'])
            if 'document.currentScript' in js:raise ValueError('Native script binding requires review')
            node.attrs.clear();node.string=js.replace('</script','<\\/script')
        crumb=env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(address,dict(kembali='/pengaturan'),title))
        variants[address]=dict(title=title,html=str(doc),breadcrumb=crumb)
    styles,scripts,srefs,jrefs={},{},{},{}
    for component in variants.values():
        doc=BeautifulSoup(component['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-facility-parent-style'),('script:not([type])',scripts,jrefs,'data-facility-parent-script')]:
            for node in doc.select(selector):node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        component['html']=str(doc)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* First-click native facility parents: no configuration or record values. */\nwindow.PadiKerangkaFasilitasParentData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-fasilitas-parent-ui-runtime.js').read_text()).encode()
    if len(payload)>262144:raise ValueError('Facility parent package exceeds bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,payload in zip(('kerangka-fasilitas-parent-ui.js','kerangka-fasilitas-parent-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=payload:raise AssertionError('Facility parent public package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
