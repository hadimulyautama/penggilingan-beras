"""Compile native portal menu structure from reviewed presentation sources."""
import argparse,ast,hashlib,importlib.util,json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader,StrictUndefined
ROOT=Path(__file__).resolve().parents[1]

def literal(path,name):
    tree=ast.parse(path.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
    return ast.literal_eval(node.value)

def build():
    inputs={Path(__file__).resolve(),ROOT/'app/web/portal/kerangka.py',ROOT/'app/web/static/portal-kerangka.js',ROOT/'app/web/templates/portal/kerangka.html',ROOT/'app/services/kelompok_kerja.py',ROOT/'app/web/portal/beranda.py',ROOT/'app/web/portal/routes.py',ROOT/'app/web/templates/portal/pengambilan.html',ROOT/'app/web/templates/portal/_daftar_catatan.html',ROOT/'hmu_tampilan/templates/_daftar_penerimaan.html',ROOT/'hmu_tampilan/templates/_pengiriman_daftar.html',ROOT/'hmu_tampilan/static/pengiriman-retur.css',ROOT/'app/web/static/daftar_pengiriman.css',ROOT/'app/web/templates/_pengiriman_riwayat_daftar.html',ROOT/'app/web/portal/navigation.py'}
    for name in ('beranda','masuk','barang','jasa','riwayat','reports'):
        inputs.add(ROOT/'app/web/templates/portal'/f'{name}.html')
    spec=importlib.util.spec_from_file_location('portal_public_spec',ROOT/'app/web/portal/kerangka.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    env=Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),autoescape=True,undefined=StrictUndefined)
    # Constants are read from their native sources, never supplied as mock rows.
    kinds=literal(ROOT/'app/services/kelompok_kerja.py','JENIS_BARANG')
    processes=literal(ROOT/'app/web/portal/beranda.py','NAMA_PROSES')
    doc_tree=ast.parse((ROOT/'app/web/portal/routes.py').read_text());report=next(n for n in doc_tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='reports')
    doc_options=next(k.value for n in ast.walk(report) if isinstance(n,ast.Call) for k in n.keywords if k.arg=='pilihan')
    docs=ast.literal_eval(doc_options)
    # The status list is a literal Jinja for-iterator in the actual native page.
    from jinja2 import nodes
    tree=env.parse((ROOT/'app/web/templates/portal/pengambilan.html').read_text())
    status=next(n.iter.as_const() for n in tree.find_all(nodes.For) if isinstance(n.target,nodes.Tuple) and [x.name for x in n.target.items]==['value','label'])
    def text_headers(path,context):
        source=path.read_text();start=source.index('<thead>');end=source.index('</thead>',start)+len('</thead>')
        html=env.from_string(source[start:end]).render(**context)
        return [x.get_text(' ',strip=True) for x in BeautifulSoup(html,'html.parser').select('th')]
    active_headers=text_headers(ROOT/'hmu_tampilan/templates/_pengiriman_daftar.html',{'PORTAL_READ_ONLY':True})
    history_headers=text_headers(ROOT/'app/web/templates/_pengiriman_riwayat_daftar.html',{'PORTAL_READ_ONLY':True})
    dom=BeautifulSoup((ROOT/'hmu_tampilan/templates/_daftar_penerimaan.html').read_text(),'html.parser')
    receipt_headers=[n.get_text(strip=True) for n in dom.select('.masuk-kepala span')]
    labels={'jenis':'Jenis barang','cari':'Cari penerimaan','q':'Cari kode atau nama','status':'Status','sejak':'Sejak tanggal'}
    variants={};schemas={}
    for page,info in m.PAGES.items():
        c=dict(labels=dict(labels),options=[],tables={},columns=[],css='')
        if page=='/barang-masuk':c['options']=[('', 'Semua jenis'),*kinds];c['columns']=receipt_headers
        if page=='/riwayat-proses':c['labels']['jenis']='Jenis proses';c['options']=[('', 'Semua proses'),*[(k,v) for k,v in processes.items() if k!='pendinginan']]
        if page=='/laporan':c['labels']['jenis']='Jenis dokumen';c['options']=docs
        if page=='/barang-keluar':c['labels']['q']='Cari pengambilan';c['options']=status;c['tables']={'Pengambilan berjalan':active_headers,'Riwayat pengambilan':history_headers}
        if page=='/barang-keluar':
            c['css']='\n'.join((ROOT/p).read_text() for p in ('hmu_tampilan/static/pengiriman-retur.css','app/web/static/daftar_pengiriman.css'))
            if '@import' in c['css'] or '</style' in c['css'].lower():raise ValueError('Review portal CSS source')
        schemas[page]=c
        state=m.deskripsi('/pelanggan'+page)
        html=env.get_template('portal/kerangka.html').render(PORTAL_FRAME_SPEC=state,PORTAL_FRAME_SCHEMA=c)
        parsed=BeautifulSoup(html,'html.parser')
        if parsed.select('script,iframe,[name=_csrf],[data-post],[data-kirim],form[method=post]') or len(parsed.select('[data-portal-native-frame]'))!=1:raise ValueError('Portal structure contains active or unknown markup')
        variants[page]=html
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    source=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    data=dict(versi=1,sumber=source,schemas=schemas,variants=variants)
    payload=('/* Public native portal structure only. */\nwindow.PadiKerangkaPortalData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'+(ROOT/'app/web/static/portal-kerangka.js').read_text()).encode()
    if len(payload)>131072:raise ValueError('Portal structure program exceeds bound')
    meta=dict(versi=1,sumber=source,schemas=schemas,aset_sha256=hashlib.sha256(payload).hexdigest(),inputs=hashes)
    return payload,(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,data in zip(('kerangka-portal-ui.js','kerangka-portal-ui.meta.json'),build()):
        path=ROOT/'app/web/static'/name
        if args.check:
            if path.read_bytes()!=data:raise AssertionError('Portal structure stale: '+name)
        else:path.write_bytes(data)
        print(name,len(data),'bytes')
if __name__=='__main__':main()
