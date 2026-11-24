"""Compile native Settings structure only; no application runtime or data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]

def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-pengaturan-ui-runtime.js'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    helper=module('settings_public_helpers',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('settings_native_spec',ROOT/'app/web/pengaturan_menu_kerangka.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Local program only')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path)
        return path.read_text()
    flags={k:True for k in ('tuan','TAMPILAN_INDUK','sesi_pendek','blok_kelola','blok_perusahaan','kelola_darurat','blok_lihat_sebagai','blok_kerja_gudang','blok_setelan','blok_mode_uji','mode_uji_tersedia')}
    variants={};console='https://console.invalid/console'
    for path in ('/pengaturan','/pengaturan/sesi'):
        spec=native.spesifikasi(path,flags=flags,console_url=console);spec['stamp']='__PADI_STAMP__'
        t=env.get_template('pengaturan_menu_kerangka.html')
        html=''.join(t.blocks['isi'](t.new_context(dict(PG_MENU_SHELL=spec,VERSI='__PADI_CAP__'))))
        doc=BeautifulSoup(html,'html.parser')
        if doc.select('form,input,[name],[data-post],[data-kirim]'):raise ValueError('No writes in public Settings')
        for node in doc.select('link[rel=stylesheet]'):
            css=asset(node['href'])
            if '@import' in css or '</style' in css.lower():raise ValueError('CSS requires review')
            style=doc.new_tag('style');style.string=helper.compact_css_comments(css);node.replace_with(style)
        for node in doc.select('script[src]'):
            js=asset(node['src'])
            if 'document.currentScript' in js:raise ValueError('Script binding requires review')
            node.attrs.clear();node.string=js.replace('</script','<\\/script')
        if path=='/pengaturan':
            for group in spec['groups']:
                node=doc.select_one('#pg-menu-'+group['id']).find_parent('section',class_='pg-grup')
                node['data-settings-group']=group['id']
                for i,door in enumerate(node.select('.pg-pintu')):
                    if door.find_parent('details') is None:door['data-settings-door']=str(i)
        variants[path]=dict(title=spec['title'],html=str(doc))
    styles,scripts,srefs,jrefs={},{},{},{}
    for v in variants.values():
        doc=BeautifulSoup(v['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-settings-style'),('script:not([type])',scripts,jrefs,'data-settings-script')]:
            for node in doc.select(selector):
                node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        v['html']=str(doc)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Public native Settings structure, no account or session values. */\nwindow.PadiKerangkaPengaturanData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-pengaturan-ui-runtime.js').read_text()).encode()
    if len(payload)>262144:raise ValueError('Settings structure budget exceeded')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');a=ap.parse_args()
    for name,payload in zip(('kerangka-pengaturan-ui.js','kerangka-pengaturan-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if a.check:
            if path.read_bytes()!=payload:raise AssertionError('Settings generated package stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
