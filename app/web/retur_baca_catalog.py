"""Bounded staff-return link provenance from native already-read DTOs only."""
from collections.abc import Mapping
from dataclasses import dataclass,field
import hashlib
import html
import re
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from app.web.retur_baca_kerangka import akun_native,aset,deskripsi

HOST='padi-retur-baca-catalog'
LIMIT=50


@dataclass(frozen=True)
class Reference:
    kind:str
    id:int
    code:str=field(repr=False)


def references(context):
    """No relationship/getattr/property lookup and no inferred resource ID."""
    result=[]
    if not isinstance(context,dict):return result
    recent=context.get('recent')
    if isinstance(recent,list) and len(recent)<=LIMIT:
        for row in recent:
            if isinstance(row,Mapping) and type(row.get('id')) is int and type(row.get('kode')) is str:
                result.append(Reference('receipt',row['id'],row['kode']))
    # Pure builder for the existing application native ticket link. Root has
    # not adopted a mutable application caller through this helper.
    row,ticket=context.get('rincian'),context.get('tiket_detail')
    try:loaded=vars(row)
    except TypeError:loaded={}
    if isinstance(ticket,dict) and type(loaded.get('timbangan_transaksi_id')) is int and type(ticket.get('kode')) is str:
        result.append(Reference('ticket',loaded['timbangan_transaksi_id'],ticket['kode']))
    return [r for r in result if r.kind in {'receipt','ticket'} and 0<r.id<=2147483647 and 0<len(r.code)<=200]


def _visible(node):
    return not any(n.has_attr('hidden') or n.has_attr('inert') or n.get('aria-hidden')=='true' for n in [node,*node.parents] if getattr(n,'attrs',None) is not None)


def _target(link,source,origin):
    value=link.get('href')
    if not isinstance(value,str):return None
    try:u=urlsplit(urljoin(origin+source,value));base=urlsplit(origin)
    except ValueError:return None
    if (u.scheme,u.netloc)!=(base.scheme,base.netloc) or u.fragment:return None
    value=u.path+('?' + u.query if u.query else '')
    return value if deskripsi(value) else None


def susun_data(source,body,offers,*,origin,cap,konteks,sesi,sumber):
    if (type(source) is not str or len(source)>4096 or type(body) is not bytes or len(body)>8388608
            or not all(type(v) is str and 0<len(v)<=2048 for v in (origin,cap,konteks,sesi))
            or type(sumber) is not str or len(sumber)!=64 or any(c not in '0123456789abcdef' for c in sumber)
            or not isinstance(offers,list) or not 0<len(offers)<=LIMIT):return None
    try:u=urlsplit(source)
    except ValueError:return None
    if u.scheme or u.netloc or u.fragment or not u.path.startswith('/') or u.path.startswith('//'):return None
    doc=BeautifulSoup(body,'html.parser');frames=doc.select('.bingkai');mains=doc.select('#isi-halaman');sessions=doc.select('#formulir-sesi')
    if (len(frames)!=1 or len(mains)!=1 or len(sessions)!=1 or frames[0] not in mains[0].parents or frames[0] not in sessions[0].parents
            or frames[0].get('data-pindah-alamat')!=source or frames[0].get('data-pindah-konteks')!=konteks
            or doc.html is None or doc.html.get('data-versi')!=cap or sessions[0].get('data-token')!=sesi):return None
    entries=[];seen=set()
    for ref in offers:
        if not isinstance(ref,Reference) or ref.kind not in {'receipt','ticket'} or type(ref.id) is not int or not 0<ref.id<=2147483647 or type(ref.code) is not str or not 0<len(ref.code)<=200:return None
        identity=(ref.kind,ref.id)
        if identity in seen:return None
        seen.add(identity)
        if ref.kind=='receipt':
            if deskripsi(source) is None or deskripsi(source)['kind']!='list':continue
            links=mains[0].select('[data-retur-receipts] td[data-sel="utama"] > a.tabel-standar__kode[href]')
        else:
            if not re.fullmatch(r'/retur/pengajuan/[1-9][0-9]*',u.path):continue
            links=mains[0].select('#panel-tiket a[href]')
        matches=[]
        for a in links:
            target=_target(a,source,origin);spec=deskripsi(target) if target else None
            if spec is None or spec['kind']!=ref.kind or spec['id']!=ref.id or not _visible(a) or a.get('target') or a.has_attr('download') or a.get('aria-disabled')=='true':continue
            if ref.kind=='receipt' and a.get_text()!=ref.code:return None
            if ref.kind=='ticket':
                card=a.find_parent('section');heading=card.find('h3') if card else None
                if a.get_text()!='Lihat tiket RTP terkait' or heading is None or heading.get_text()!=ref.code:return None
            matches.append(target)
        if len(matches)!=1:continue
        entries.append(dict(kind=ref.kind,id=ref.id,code=ref.code,target=matches[0]))
    if not entries:return None
    return dict(versi=1,sumber=sumber,cap=cap,konteks=konteks,sesi=sesi,source_address=source,sumber_sha256=hashlib.sha256(source.encode()).hexdigest(),entries=entries)


def pasang(request,akun,response):
    """Only the three declared complete native GET responses are adopted."""
    if not akun_native(request,akun) or response.status_code!=200 or 'text/html' not in response.headers.get('content-type',''):return response
    from app.web.layar_retur import halaman_retur,detail_retur
    from app.web.layar_retur_asal import tiket_retur
    if request.scope.get('endpoint') not in {halaman_retur,detail_retur,tiket_retur}:return response
    context=getattr(response,'context',None)
    if not isinstance(context,dict) or context.get('akun') is not akun:return response
    body=getattr(response,'body',None);marker=b'<!-- isi-halaman:akhir -->'
    if type(body) is not bytes or body.count(marker)!=1 or HOST.encode() in body:return response
    from hmu_tampilan import CAP_ASET
    try:
        meta=aset();source=request.url.path+('?' + request.url.query if request.url.query else '')
        data=susun_data(source,body,references(context),origin=str(request.base_url).rstrip('/'),cap=CAP_ASET,konteks=context.get('PINDAH_KONTEKS'),sesi=context.get('CSRF'),sumber=meta['sumber'])
    except (OSError,ValueError):return response
    if data is None:return response
    from jinja2.utils import htmlsafe_json_dumps
    raw=htmlsafe_json_dumps(data).encode()
    if len(raw)>32768:return response
    attrs=' '.join(k+'="'+html.escape(v,quote=True)+'"' for k,v in {'data-cap':data['cap'],'data-konteks':data['konteks'],'data-source-address':source,'data-source-sha':data['sumber_sha256']}.items())
    tag=('<script type="application/json" id="'+HOST+'" '+attrs+'>').encode()+raw+b'</script>'
    if len(body)+len(tag)>8388608:return response
    response.body=body.replace(marker,tag+marker,1);response.headers['content-length']=str(len(response.body));response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie';return response
