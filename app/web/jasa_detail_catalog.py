"""Private first-click provenance from already-read native Jasa HTML/context.

No queries, row lookup, parser-inferred counts or user/tenant selection. This
catalog is presentation provenance; each native data GET rechecks authority.
"""
from functools import lru_cache
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from app.web.jasa_detail_kerangka import deskripsi

HOST='padi-jasa-detail-catalog'


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-jasa-detail-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=['ringkasan','penerimaan','proses','stok','pengambilan']
            or hashlib.sha256((folder/'kerangka-jasa-detail-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Jasa detail public package mismatch')
    return meta


def _address(href,source):
    if not isinstance(href,str) or not href:return None
    u=urlsplit(urljoin('https://native.invalid'+source,href))
    if u.scheme!='https' or u.netloc!='native.invalid' or u.fragment:return None
    target=u.path+('?' +u.query if u.query else '')
    return target if deskripsi(u.path,u.query) is not None else None


def _record(row):
    if not isinstance(row,dict):return None
    pid,name,count=row.get('id'),row.get('nama'),row.get('pesanan_jumlah')
    if (type(pid) is not int or not 0<pid<=2147483647 or not isinstance(name,str)
            or not name or len(name)>200 or type(count) is not int or count<0):return None
    return dict(id=pid,label=name,filter=count>20,targets=[])


def _pid(address):
    path,_,query=address.partition('?')
    state=deskripsi(path,query)
    return state['pelanggan_id'] if state else None


def _shown(node):
    return not any(n.has_attr('hidden') or n.has_attr('inert') or n.get('aria-hidden')=='true'
                   for n in [node,*node.parents] if getattr(n,'attrs',None) is not None)


def private_host(data,cap):
    """Escape private JSON as inert text; never interpolate a customer as HTML."""
    raw=json.dumps(data,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    attrs=' '.join(f'{key}="{html.escape(value,quote=True)}"' for key,value in {
        'data-cap':data['cap'],'data-konteks':data['konteks'],'data-source-address':data['source_address'],'data-source-sha':data['sumber_sha256']}.items())
    return (f'<script type="application/json" id="{HOST}" {attrs}>{raw}</script>\n'
            f'<script src="/static/kerangka-jasa-detail-ui.js?v={html.escape(cap,quote=True)}" defer></script>\n').encode()


def susun_data(source,body,context,*,cap,konteks,sesi,sumber):
    """Pure bounded context-to-HTML binding, never a customer/role guess."""
    if (not isinstance(body,bytes) or len(body)>8388608 or not isinstance(context,dict)
            or not all(isinstance(x,str) and x for x in (source,cap,konteks,sesi,sumber))
            or len(source)>4096 or any(len(x)>2048 for x in (cap,konteks,sesi))
            or not re.fullmatch(r'[a-f0-9]{64}',sumber)):return None
    u=urlsplit(source)
    if u.scheme or u.netloc or u.fragment:return None
    mode='list' if u.path=='/jasa' else 'detail'
    spec=deskripsi(u.path,u.query) if mode=='detail' else None
    if mode=='detail' and spec is None:return None
    if mode=='list':
        from urllib.parse import parse_qsl
        pairs=parse_qsl(u.query,keep_blank_values=True)
        if len(pairs)>3 or len(dict(pairs))!=len(pairs) or set(dict(pairs))-{'status','cari','halaman'}:return None
        rows=context.get('kartu')
        if not isinstance(rows,list) or len(rows)>25:return None
    else:
        rows=[context.get('d')]
        if context.get('tab')!=spec['tab']:return None
    records=[_record(row) for row in rows]
    if any(r is None for r in records) or len({r['id'] for r in records})!=len(records):return None
    if mode=='detail' and records[0]['id']!=spec['pelanggan_id']:return None
    doc=BeautifulSoup(body,'html.parser');frames=doc.select('.bingkai');sessions=doc.select('#formulir-sesi');mains=doc.select('#isi-halaman')
    if (len(frames)!=1 or len(sessions)!=1 or len(mains)!=1
            or frames[0].get('data-pindah-konteks')!=konteks or frames[0].get('data-pindah-alamat')!=source
            or sessions[0].get('data-token')!=sesi or doc.html is None or doc.html.get('data-versi')!=cap):return None
    if frames[0] not in mains[0].parents or frames[0] not in sessions[0].parents:return None
    for record in records:
        if mode=='list':
            links=mains[0].select('.jasa-daftar>a.jasa-pelanggan[href]')
            for link in links:
                target=_address(link.get('href'),source)
                heading=link.select_one('.baris h2')
                if target and _pid(target)==record['id'] and _shown(link):
                    if heading is None or heading.get_text()!=record['label']:return None
                    record['targets'].append(target)
        else:
            heading=mains[0].select_one('.jasa-kontrol h1')
            if heading is None or heading.get_text()!=record['label']:return None
            for link in mains[0].select('.jasa-detail-tab>a[href]'):
                target=_address(link.get('href'),source)
                if target and _pid(target)==record['id'] and _shown(link):record['targets'].append(target)
        record['targets']=list(dict.fromkeys(record['targets']))
        if len(record['targets'])!=(1 if mode=='list' else 5):return None
    if not records:return None
    return dict(versi=1,cap=cap,konteks=konteks,sesi=sesi,sumber=sumber,source_address=source,
        sumber_sha256=hashlib.sha256(source.encode()).hexdigest(),mode=mode,entries=records)


def pasang(request,akun,response):
    """Caller-only decoration after actual list/detail read; zero DB per row."""
    if (request.method!='GET' or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False or response.status_code!=200):return response
    from app.peran import can_see_financials
    if not can_see_financials(akun.user):return response
    context=getattr(response,'context',None)
    if not isinstance(context,dict) or context.get('akun') is not akun:return response
    try:meta=aset()
    except (OSError,ValueError):return response
    source=request.url.path+('?' +request.url.query if request.url.query else '')
    from hmu_tampilan import CAP_ASET
    data=susun_data(source,getattr(response,'body',None),context,cap=CAP_ASET,
        konteks=context.get('PINDAH_KONTEKS'),sesi=context.get('CSRF'),sumber=meta['sumber'])
    if data is None:return response
    marker=b'<!-- isi-halaman:akhir -->'
    if response.body.count(marker)!=1 or f'id="{HOST}"'.encode() in response.body:return response
    host=private_host(data,CAP_ASET)
    if len(response.body)+len(host)>8388608:return response
    response.body=response.body.replace(marker,host+marker,1)
    response.headers['content-length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response
