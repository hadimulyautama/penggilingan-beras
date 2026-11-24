"""Private line-link provenance from the already-read native parent only.

No guard/query shortcut, no lazy attribute read, no row/role from a URL.
"""
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
from bs4 import BeautifulSoup
from app.web.fasilitas_detail_kerangka import PARENT,VARIANTS,deskripsi,valid_entry

HOST='padi-fasilitas-detail-catalog'
LIMIT=32


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-fasilitas-detail-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=list(VARIANTS)
            or hashlib.sha256((folder/'kerangka-fasilitas-detail-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Facility detail public package mismatch')
    return meta


def _loaded(row):
    """Only native loaded columns; never trigger an ORM property/relationship."""
    try:return vars(row)
    except TypeError:return None


def _shown(node):
    return not any(n.has_attr('hidden') or n.has_attr('inert') or n.get('aria-hidden')=='true'
                   for n in [node,*node.parents] if getattr(n,'attrs',None) is not None)


def susun_data(source,body,context,*,cap,konteks,sesi,sumber):
    if (source!=PARENT or not isinstance(body,bytes) or len(body)>8388608 or not isinstance(context,dict)
            or not all(isinstance(x,str) and 0<len(x)<=2048 for x in (cap,konteks,sesi))
            or not isinstance(sumber,str) or len(sumber)!=64 or any(c not in '0123456789abcdef' for c in sumber)
            or not {'mode','detail','pengering','err','isian','lini','dryer'}<=context.keys()
            or context['mode']!='mesin' or context['detail'] is not None or context['pengering'] is not None
            or context['err']!='' or not isinstance(context['isian'],dict) or context['isian']
            or not isinstance(context['lini'],list) or not isinstance(context['dryer'],list)):
        return None
    doc=BeautifulSoup(body,'html.parser');frames=doc.select('.bingkai');mains=doc.select('#isi-halaman');sessions=doc.select('#formulir-sesi')
    if (len(frames)!=1 or len(mains)!=1 or len(sessions)!=1 or frames[0] not in mains[0].parents or frames[0] not in sessions[0].parents
            or frames[0].get('data-pindah-alamat')!=source or frames[0].get('data-pindah-konteks')!=konteks
            or doc.html is None or doc.html.get('data-versi')!=cap or sessions[0].get('data-token')!=sesi):return None
    headings=mains[0].select('[data-fasilitas]>h1')
    if len(headings)!=1 or headings[0].get_text()!='Mesin & line produksi':return None
    candidates=[]
    for link in mains[0].select('[data-fasilitas] .pg-grup a.pg-pintu[href]'):
        target=link.get('href');spec=deskripsi(target)
        if spec is None or not _shown(link):continue
        heading=link.select_one('.pg-pintu__isi strong')
        if heading is None:return None
        candidates.append((spec['id'],target,heading.get_text()))
        if len(candidates)==LIMIT:break
    if not candidates or len({row[0] for row in candidates})!=len(candidates):return None
    wanted={row[0] for row in candidates};lines={}
    for row in context['lini']:
        data=_loaded(row)
        if data is not None and type(data.get('id')) is int and data['id'] in wanted:
            if data['id'] in lines:return None
            if not {'id','nama','dryer_id'}<=data.keys():return None
            if data['dryer_id'] is not None and (type(data['dryer_id']) is not int or data['dryer_id']<=0):return None
            lines[data['id']]=data
    if set(lines)!=wanted:return None
    refs={r['dryer_id'] for r in lines.values() if r['dryer_id'] is not None};dryers={}
    for row in context['dryer']:
        data=_loaded(row)
        if data is not None and type(data.get('id')) is int and data['id'] in refs:
            if data['id'] in dryers or 'nama' not in data:return None
            dryers[data['id']]=data
    entries=[]
    for id_,target,label in candidates:
        line=lines[id_];dryer=dryers.get(line['dryer_id'])
        entry=dict(id=id_,label=dryer['nama'] if dryer is not None else line['nama'],variant='dryer' if dryer is not None else 'line',target=target)
        if not valid_entry(entry) or entry['label']!=label:return None
        entries.append(entry)
    return dict(versi=1,cap=cap,konteks=konteks,sesi=sesi,sumber=sumber,source_address=source,
        sumber_sha256=hashlib.sha256(source.encode()).hexdigest(),entries=entries)


def pasang(request,akun,response):
    if (request.method!='GET' or request.url.path!=PARENT or request.url.query
            or getattr(request.state,'akun',None) is not akun or getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False or response.status_code!=200):return response
    # FastAPI owns this endpoint object/dependency result; it is not a header,
    # role guess or an additional recovery/permission lookup.
    from app.web.fasilitas import daftar
    if request.scope.get('endpoint') is not daftar:return response
    context=getattr(response,'context',None)
    if not isinstance(context,dict) or context.get('akun') is not akun:return response
    try:meta=aset()
    except (OSError,ValueError):return response
    from hmu_tampilan import CAP_ASET
    data=susun_data(PARENT,response.body,context,cap=CAP_ASET,konteks=context.get('PINDAH_KONTEKS'),sesi=context.get('CSRF'),sumber=meta['sumber'])
    marker=b'<!-- isi-halaman:akhir -->'
    if data is None or response.body.count(marker)!=1 or HOST.encode() in response.body:return response
    from jinja2.utils import htmlsafe_json_dumps
    raw=htmlsafe_json_dumps(data).encode()
    if len(raw)>16384:return response
    attrs=' '.join(f'{k}="{html.escape(v,quote=True)}"' for k,v in {'data-cap':CAP_ASET,'data-konteks':data['konteks'],'data-source-address':PARENT,'data-source-sha':data['sumber_sha256']}.items())
    tag=f'<script type="application/json" id="{HOST}" {attrs}>'.encode()+raw+b'</script>'
    if len(response.body)+len(tag)>8388608:return response
    response.body=response.body.replace(marker,tag+marker,1);response.headers['content-length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie';return response
