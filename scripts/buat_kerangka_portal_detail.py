"""Compile only reviewed, data-free native customer detail presentation."""
import argparse,ast,hashlib,importlib.util,json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader,StrictUndefined,nodes
ROOT=Path(__file__).resolve().parents[1]


def closed_giling_schema():
    """Literal native closed-reader labels after its actual customer maps.

    No application import, record, Jinja business-expression evaluation or
    synthetic process. Both label maps are parsed from the real projection;
    deleting/changing the closed native source makes compilation fail.
    """
    source=(ROOT/'app/web/templates/riwayat_giling_detail.html').read_text()
    tree=Environment().parse(source)
    tabs=[]
    for loop in tree.find_all(nodes.For):
        if not isinstance(loop.target,nodes.Tuple):continue
        if [n.name for n in loop.target.items]!=['id','label']:continue
        try:value=loop.iter.as_const()
        except nodes.Impossible:continue
        if len(value)==5 and value[0][0]=='ringkasan':tabs.append(value)
    if len(tabs)!=1:raise ValueError('Review closed Giling native five-tab source')
    maps=[]
    for file,function in [('app/web/portal/presentation.py','bahasa_pelanggan'),('app/web/portal/detail.py','ringkas')]:
        module=ast.parse((ROOT/file).read_text())
        fn=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name==function)
        assignments=[n for n in fn.body if isinstance(n,ast.Assign) and len(n.targets)==1
                     and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='labels']
        if len(assignments)!=1:raise ValueError('Review customer label-map source')
        value=ast.literal_eval(assignments[0].value)
        if not isinstance(value,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in value.items()):raise ValueError('Review customer label-map shape')
        maps.append(value)
    def projected(label):
        for mapping in maps:label=mapping.get(label,label)
        return label
    doc=BeautifulSoup(source,'html.parser')
    def panel(key):
        result=doc.select_one('#rhs-panel-'+key)
        if result is None:raise ValueError('Review native closed Giling panel')
        return result
    def heading(key):
        result=panel(key).select_one('h2')
        if result is None:raise ValueError('Review native closed Giling heading')
        return projected(result.get_text(' ',strip=True))
    def fields(key):
        group=panel(key).select_one('dl.riwayat-detail__facts')
        if group is None:raise ValueError('Review native closed Giling fields')
        # The real customer projection removes this internal identity row.
        return [projected(n.get_text(' ',strip=True)) for n in group.select('dt')
                if n.get_text(' ',strip=True)!='ID jasa']
    columns=[projected(n.get_text(' ',strip=True)) for n in panel('bahan').select('.riwayat-detail__table-head span')]
    mass=[n.get_text(' ',strip=True) for n in panel('ringkasan').select('.rhs-mass>div>span')]
    if len(columns)!=3 or len(mass)!=3:raise ValueError('Review native closed Giling columns')
    qc=BeautifulSoup((ROOT/'app/web/templates/_qc_gabah_asal.html').read_text(),'html.parser').select_one('h2')
    jeda=BeautifulSoup((ROOT/'hmu_tampilan/templates/_riwayat_jeda.html').read_text(),'html.parser')
    if qc is None or jeda.select_one('h2') is None:raise ValueError('Review closed Giling source sections')
    return dict(tabs=[(key,projected(label)) for key,label in tabs[0]],
        summary_title=heading('ringkasan'),mass=mass,bahan_title=heading('bahan'),columns=columns,
        result_title=heading('hasil'),result_fields=fields('hasil'),history_title=heading('riwayat'),
        history_fields=fields('riwayat'),qc_title=projected(qc.get_text(' ',strip=True)),
        pause_title=projected(jeda.h2.get_text(' ',strip=True)),
        pause_fields=[projected(n.get_text(' ',strip=True)) for n in jeda.select('.jeda-riwayat__catatan dl dt')])

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
    closed=closed_giling_schema()
    if closed['tabs']!=m.TABS['giling-riwayat']:raise ValueError('Closed Giling source tabs changed')
    native_styles='\n'.join((ROOT/'app/web/static'/name).read_text() for name in ('riwayat.css','riwayat-sosoh-desain.css'))
    if '@import' in native_styles.lower() or '</style' in native_styles.lower():raise ValueError('Review closed Giling style dependencies')
    for kind in m.TABS:
        if kind=='giling-riwayat':
            html=env.get_template('portal/detail_riwayat_giling_kerangka.html').render(tabs=m.TABS[kind],closed=closed,native_styles=native_styles)
        else:
            html=env.get_template('portal/detail_kerangka.html').render(kind=kind,tabs=m.TABS[kind],sections=m.SECTIONS[kind],tables=tables)
        s=BeautifulSoup(html,'html.parser')
        if len(s.select('[data-portal-detail-frame]'))!=1 or s.select('script,iframe,form,input,[name=_csrf],[data-post],[data-kirim]'):raise ValueError('Non-read-only detail structure')
        if len(s.select('[role=tab]'))!=len(m.TABS[kind]) or any(not n.has_attr('disabled') for n in s.select('[role=tab]')):raise ValueError('Unread tabs must remain unavailable')
        variants[kind]=html
    names=['app/web/portal/detail_kerangka.py','app/web/portal/detail_catalog.py','app/web/static/portal-detail-kerangka.js','app/web/templates/portal/detail_kerangka.html','scripts/buat_kerangka_portal_detail.py',
        'app/services/proses_aktif.py','app/web/templates/detail_giling.html','app/web/templates/barang_masuk_detail_lama.html','app/web/portal/detail.py','app/web/portal/transaksi_detail.py','app/web/portal/proses_ringkas.py','app/web/templates/portal/_inti_proses_ringkas.html','app/web/templates/portal/_penerimaan_qc.html',
        'app/web/templates/portal/detail_riwayat_giling_kerangka.html','app/web/templates/riwayat_giling_detail.html','app/web/templates/_qc_gabah_asal.html','hmu_tampilan/templates/_riwayat_jeda.html',
        'app/web/static/riwayat.css','app/web/static/riwayat-sosoh-desain.css',
        'app/web/portal/presentation.py','app/web/portal/identitas_proses.py','app/web/templates/portal/riwayat.html','app/web/templates/portal/_daftar_catatan.html','app/web/portal/riwayat_daftar.py']
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
