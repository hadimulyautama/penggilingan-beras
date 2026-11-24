"""Native audit structure only. Undo/audit data is never read or cached here."""
import ast
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import parse_qsl
ROOT=Path(__file__).resolve().parents[2]

def alamat(path,query=''):
    if path!='/audit' or len(query)>2048:return None
    try:pairs=parse_qsl(query,keep_blank_values=True,max_num_fields=3)
    except ValueError:return None
    if len(dict(pairs))!=len(pairs) or set(dict(pairs))-{'rentang','kelompok','cari'}:return None
    values=dict(pairs);choices=metadata()
    if any(values.get(key,default) not in {row[0] for row in choices[name]} for key,name,default in [('rentang','RENTANG','48j'),('kelompok','KELOMPOK','semua')]):return None
    return path+('?' +query if query else '')

@lru_cache(maxsize=1)
def metadata():
    tree=ast.parse((ROOT/'app/services/audit.py').read_text())
    choices={}
    for n in tree.body:
        if isinstance(n,ast.Assign):
            for target in n.targets:
                if isinstance(target,ast.Name) and target.id in {'RENTANG','KELOMPOK'}:
                    choices[target.id]=[(ast.literal_eval(row.elts[0]),ast.literal_eval(row.elts[1]),None) for row in n.value.elts]
    if set(choices)!={'RENTANG','KELOMPOK'}:raise ValueError('Audit native choices changed')
    source=(ROOT/'hmu_tampilan/templates/audit.html').read_text()
    match=re.search(r'<thead>.*?</thead>',source,re.S)
    if match is None or any(x in match[0] for x in ('{{','{%','<input','<button','<a ')):raise ValueError('Audit headers require review')
    return dict(family='audit',kind='audit',title='Audit aktivitas',source_template='audit.html',header=match[0],columns=re.findall(r'<th\b[^>]*>(.*?)</th>',match[0]),**choices)

async def dokumen(request,akun):
    if (request.method!='GET' or alamat(request.url.path,request.url.query) is None
        or request.headers.get('X-Pindah')=='1'
        or not (request.headers.get('X-Kerangka-Halaman')=='1' or request.headers.get('Sec-Fetch-Mode')=='navigate' and request.headers.get('Sec-Fetch-Dest') in {'document','empty'})):
        return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request) or getattr(request.state,'portal_scope',None) is not None:return None
    # Native dependency is also re-used when called outside the native handler.
    from app.web.security import butuh_admin
    await butuh_admin(akun)
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    from app.web.laporan_navigasi import siapkan
    from app.web.tampilan import render
    context=await konteks_kerangka(request,akun);await siapkan(request,context)
    meta=metadata();address=alamat(request.url.path,request.url.query)
    response=render(request,'audit_kerangka.html',**context,AUDIT_META=meta,
        AUDIT_URL=address,AUDIT_STAMP=penanda_konteks(request,akun)+'|'+address,
        rentang=request.query_params.get('rentang','48j'),kelompok=request.query_params.get('kelompok','semua'),
        cari=request.query_params.get('cari',''),RENTANG=meta['RENTANG'],KELOMPOK=meta['KELOMPOK'])
    response.headers['Cache-Control']='private, no-store'
    return response
