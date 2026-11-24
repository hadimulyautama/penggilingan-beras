"""Compile only reviewed, data-free native customer detail presentation."""
import argparse,ast,hashlib,importlib.util,json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]

def build():
    path=ROOT/'app/web/portal/detail_kerangka.py'
    spec=importlib.util.spec_from_file_location('portal_detail_spec',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    env=Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),autoescape=True,undefined=StrictUndefined)
    # Header arrays are literals of the real native Giling reader, not demo rows.
    source_tree=ast.parse((ROOT/'app/services/proses_aktif.py').read_text())
    logs={}
    for n in ast.walk(source_tree):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_log' and len(n.args)>7:
            if isinstance(n.args[6],ast.Constant) and n.args[6].value in ('Riwayat hasil giling','Riwayat QC hasil PK'):
                logs[n.args[6].value]=ast.literal_eval(n.args[7])
    if set(logs)!={'Riwayat hasil giling','Riwayat QC hasil PK'}:raise ValueError('Review native Giling log columns')
    tables=[('Riwayat hasil giling',logs['Riwayat hasil giling']),('Riwayat pemeriksaan hasil giling',logs['Riwayat QC hasil PK'])]
    variants={}
    for kind in m.TABS:
        html=env.get_template('portal/detail_kerangka.html').render(kind=kind,tabs=m.TABS[kind],sections=m.SECTIONS[kind],tables=tables)
        s=BeautifulSoup(html,'html.parser')
        if len(s.select('[data-portal-detail-frame]'))!=1 or s.select('script,iframe,form,input,[name=_csrf],[data-post],[data-kirim]'):raise ValueError('Non-read-only detail structure')
        if len(s.select('[role=tab]'))!=4 or any(not n.has_attr('disabled') for n in s.select('[role=tab]')):raise ValueError('Unread tabs must remain unavailable')
        variants[kind]=html
    names=['app/web/portal/detail_kerangka.py','app/web/portal/detail_catalog.py','app/web/static/portal-detail-kerangka.js','app/web/templates/portal/detail_kerangka.html','scripts/buat_kerangka_portal_detail.py',
        'app/services/proses_aktif.py','app/web/templates/detail_giling.html','app/web/templates/barang_masuk_detail_lama.html','app/web/portal/detail.py','app/web/portal/transaksi_detail.py','app/web/portal/proses_ringkas.py','app/web/templates/portal/_inti_proses_ringkas.html','app/web/templates/portal/_penerimaan_qc.html']
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,variants=variants)
    payload=('/* Public data-free customer detail structure. */\nwindow.PadiKerangkaPortalDetailData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/portal-detail-kerangka.js').read_text()).encode()
    if len(payload)>49152:raise ValueError('Detail structure program exceeds bound')
    meta=dict(versi=1,sumber=source,aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,indent=2)+'\n').encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,data in zip(('kerangka-portal-detail-ui.js','kerangka-portal-detail-ui.meta.json'),build()):
        f=ROOT/'app/web/static'/name
        if args.check:
            if f.read_bytes()!=data:raise AssertionError('Stale portal detail structure '+name)
        else:f.write_bytes(data)
        print(name,len(data),'bytes')
