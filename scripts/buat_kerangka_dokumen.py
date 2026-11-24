"""Compile twelve native report structures, no data or application runtime."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]

def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/static/kerangka-dokumen-ui-runtime.js'}
    def module(name,path):
        inputs.add(path);spec=importlib.util.spec_from_file_location(name,path)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    helper=module('doc_public_helpers',ROOT/'scripts/buat_kerangka_ui.py')
    native=module('doc_native_spec',ROOT/'app/web/laporan_detail_kerangka.py')
    heads=module('doc_native_headers',ROOT/'app/services/laporan_kepala.py')
    catalog=module('doc_native_catalog',ROOT/'scripts/kerangka_laporan_katalog.py')
    public=catalog.metadata(ROOT);inputs.update(ROOT/p for p in catalog.source_pins(ROOT))
    inputs.add(ROOT/'app/services/laporan_isi_tahap.py')
    roots=[ROOT/'app/web',ROOT/'hmu_tampilan']
    env=Environment(loader=ChoiceLoader([helper.SourceLoader(p/'templates',inputs) for p in roots]),autoescape=True,undefined=StrictUndefined)
    def asset(url):
        name=url.split('?')[0].removeprefix('/static/')
        if not name or '/' in name or '\\' in name:raise ValueError('Only native local program allowed')
        path=next(p/'static'/name for p in roots if (p/'static'/name).is_file());inputs.add(path);return path.read_text()
    reports=[dict(kode=v['kode'].removeprefix('tahap_'),nama=v['nama']) for v in public['daftar']]
    top=['penyosohan','penggilingan','pengeringan','transfer_pk']
    choices=[dict(**v,kelompok='Proses' if v['kode'] in top else 'Laporan lainnya') for v in sorted(reports,key=lambda v:top.index(v['kode']) if v['kode'] in top else len(top))]
    variants={}
    for report in reports:
        code=report['kode']
        if code=='transfer_pk':continue
        meta=native.metadata(code,kepala=heads.susun)
        context=dict(laporan=report,tahap=code,periode=public['periode'],periode_aktif='bulan_ini',dari='',sampai='',pilihan_laporan=choices,VERSI='__PADI_CAP__',DETAIL_META=meta,DETAIL_URL='/laporan/'+code,DETAIL_STAMP='__PADI_STAMP__')
        template=env.get_template('laporan_detail_kerangka.html')
        doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(context))),'html.parser')
        if doc.select('[data-post],[data-kirim],#laporan-data') or any(f.get('method')!='get' or f.get('action')!='/laporan/'+code for f in doc.select('form')):
            raise ValueError('Report structure must contain native GET filters only')
        for node in doc.select('script[src]'):
            text=asset(node['src'])
            if 'document.currentScript' in text:raise ValueError('Native script binding requires review')
            node.attrs.clear();node.string=text.replace('</script','<\\/script')
        if doc.select('link[rel=stylesheet]'):raise ValueError('Review new stylesheet request')
        variants['/laporan/'+code]=dict(title=meta['nama'],html=str(doc),columns=len(meta['kolom']))
    styles,scripts,srefs,jrefs={},{},{},{}
    for v in variants.values():
        doc=BeautifulSoup(v['html'],'html.parser')
        for selector,pool,refs,attr in [('style',styles,srefs,'data-document-style'),('script:not([type])',scripts,jrefs,'data-document-script')]:
            for node in doc.select(selector):
                node[attr]=helper.intern_text(pool,refs,node.string or '');node.clear()
        v['html']=str(doc)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants,styles=styles,scripts=scripts)
    payload=('/* Public report structure only, no report data. */\nwindow.PadiKerangkaDokumenData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/kerangka-dokumen-ui-runtime.js').read_text()).encode()
    if len(payload)>524288:raise ValueError('Native document package exceeds size bound')
    meta=dict(versi=1,sumber=source,variants=list(variants),aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');a=ap.parse_args()
    for name,payload in zip(('kerangka-dokumen-ui.js','kerangka-dokumen-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if a.check:
            if path.read_bytes()!=payload:raise AssertionError('Generated report structure stale: '+name)
        else:path.write_bytes(payload)
        print(name,len(payload),'bytes')
if __name__=='__main__':main()
