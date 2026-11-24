"""Private active-shipping provenance from the native DTO and native visible links.

No row query, no inferred actor, no business weights or fingerprint in metadata.
"""
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from app.web.pengiriman_detail_kerangka import ACTIVE,deskripsi,valid_meta
from app.web.giling_work_catalog import _visible

HOST='padi-pengiriman-detail-catalog'


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-pengiriman-detail-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=['read','command']
            or hashlib.sha256((folder/'kerangka-pengiriman-detail-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Active shipping package mismatch')
    return meta


def _address(href,source,origin):
    if not isinstance(href,str):return None
    u=urlsplit(urljoin(origin+source,href));base=urlsplit(origin)
    if (u.scheme,u.netloc)!=(base.scheme,base.netloc):return None
    if u.fragment and u.fragment not in ('panel-ringkasan','panel-barang','panel-tiket','panel-riwayat'):return None
    target=u.path+('?' +u.query if u.query else '')
    return target if deskripsi(u.path,u.query) else None


def _from_card(card,context):
    """Caller passes the actual existing kartu DTO; only display variant flags leave."""
    if not isinstance(card,dict):return None
    rec=card.get('rec')
    if rec is None or rec.status not in ACTIVE:return None
    actions=card.get('tombol')
    if not isinstance(actions,list) or any(not isinstance(row,(tuple,list)) or len(row)!=4 for row in actions):return None
    meta=dict(id=rec.id,kode=rec.kode,status=rec.status,keadaan=card.get('keadaan'),
        jasa=card.get('jasa'),cepat=card.get('cepat'),bersama=bool(card.get('kiriman_bersama')),
        tiket=bool(rec.timbangan_transaksi_id),boleh_perintah=context.get('BOLEH_PERINTAH'),boleh_muat=context.get('BOLEH_MUAT'),
        actions=[dict(label=label,bagian='barang' if key=='tambah_barang_keluar' else 'ringkasan')
                 for key,_,label,_ in actions])
    return meta if valid_meta(meta) else None


def susun_data(source,body,context,*,origin,cap,konteks,sesi,sumber):
    if (not isinstance(body,bytes) or len(body)>8388608 or not isinstance(context,dict)
            or not all(type(v) is str and 0<len(v)<=2048 for v in (cap,konteks,sesi))
            or not isinstance(source,str) or len(source)>4096 or not isinstance(origin,str)
            or not isinstance(sumber,str) or len(sumber)!=64 or any(c not in '0123456789abcdef' for c in sumber)):
        return None
    u=urlsplit(source)
    if u.scheme or u.netloc or u.fragment:return None
    mode='list' if u.path=='/barang-keluar' else 'detail'
    if mode=='detail' and deskripsi(u.path,u.query) is None:return None
    if mode=='list':
        from urllib.parse import parse_qsl
        pairs=parse_qsl(u.query,keep_blank_values=True)
        if len(pairs)>5 or len(dict(pairs))!=len(pairs) or set(dict(pairs))-{'q','status','sejak','sebelum','pelanggan_id'}:return None
    cards=context.get('kartu')
    if not isinstance(cards,list) or len(cards)>550:return None
    records=[_from_card(card,context) for card in cards if isinstance(card,dict) and getattr(card.get('rec'),'status',None) in ACTIVE]
    if not records or len(records)>50 or any(r is None for r in records) or len({r['id'] for r in records})!=len(records):return None
    if mode=='detail' and (len(records)!=1 or records[0]['id']!=deskripsi(u.path,u.query)['id']):return None
    doc=BeautifulSoup(body,'html.parser');frames=doc.select('.bingkai');mains=doc.select('#isi-halaman');sessions=doc.select('#formulir-sesi')
    if (len(frames)!=1 or len(mains)!=1 or len(sessions)!=1 or frames[0] not in mains[0].parents or frames[0] not in sessions[0].parents
            or frames[0].get('data-pindah-alamat')!=source or frames[0].get('data-pindah-konteks')!=konteks
            or doc.html is None or doc.html.get('data-versi')!=cap or sessions[0].get('data-token')!=sesi):return None
    entries=[]
    for meta in records:
        targets=[]
        if mode=='list':
            rows=mains[0].select('.keluar-daftar tr.keluar-baris[data-detail-keluar]')
            for row in rows:
                target=_address(row.get('data-detail-keluar'),source,origin)
                if not target or deskripsi(*target.partition('?')[::2])['id']!=meta['id'] or not _visible(row):continue
                links=[a for a in row.select('td:first-child>a[href]') if _address(a.get('href'),source,origin)==target and _visible(a)]
                if len(links)!=1:return None
                code=links[0].find('small')
                if code is None or not code.get_text().startswith(meta['kode']+' · '):return None
                targets.append(target)
        else:
            article=mains[0].select_one('[data-detail-tab]');heading=article.select_one('#judul-perintah') if article else None
            if not article or not _visible(article) or heading is None or heading.get_text()!=meta['kode']:return None
            for link in article.select('.detail-kirim-tabs>a[href]'):
                target=_address(link.get('href'),source,origin)
                if target and _visible(link):targets.append(target)
        targets=list(dict.fromkeys(targets))
        if len(targets)!=(1 if mode=='list' else 4) or any(deskripsi(*t.partition('?')[::2])['id']!=meta['id'] for t in targets):return None
        entries.append(dict(meta=meta,targets=targets))
    return dict(versi=1,cap=cap,konteks=konteks,sesi=sesi,sumber=sumber,source_address=source,
                sumber_sha256=hashlib.sha256(source.encode()).hexdigest(),mode=mode,entries=entries)


def pasang(request,akun,response):
    if (request.method!='GET' or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None or getattr(akun,'harus_ganti_sandi',None) is not False
            or response.status_code!=200):return response
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):return response
    context=getattr(response,'context',None)
    if not isinstance(context,dict) or context.get('akun') is not akun:return response
    try:source=aset()['sumber']
    except (OSError,ValueError):return response
    from hmu_tampilan import CAP_ASET
    address=request.url.path+('?' +request.url.query if request.url.query else '')
    data=susun_data(address,response.body,context,origin=str(request.base_url).rstrip('/'),
        cap=CAP_ASET,konteks=context.get('PINDAH_KONTEKS'),sesi=context.get('CSRF'),sumber=source)
    marker=b'<!-- isi-halaman:akhir -->'
    if data is None or response.body.count(marker)!=1 or HOST.encode() in response.body:return response
    from jinja2.utils import htmlsafe_json_dumps
    raw=htmlsafe_json_dumps(data).encode()
    if len(raw)>262144:return response
    attrs=' '.join(f'{k}="{html.escape(v,quote=True)}"' for k,v in {'data-cap':CAP_ASET,'data-konteks':data['konteks'],
        'data-source-address':address,'data-source-sha':data['sumber_sha256']}.items())
    tag=f'<script type="application/json" id="{HOST}" {attrs}>'.encode()+raw+b'</script>'
    if len(response.body)+len(tag)>8388608:return response
    response.body=response.body.replace(marker,tag+marker,1);response.headers['content-length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie';return response
