"""Read-only karung source-list structure, from existing authorized DTO links.

This family never starts the kepemilikan source editor or copies its initial
transaction JSON, actor, quantities, baseline, draft or pending storage state.
"""
from dataclasses import dataclass,field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl,urlencode
import hashlib,json
from html import escape

ROOT=Path(__file__).resolve().parents[2]
SELECTOR='table.karung-tabel .karung-tabel__status > a.btn[href]'
TITLE='Detail karung kosong'
BACK='/stok?tab=karung'


def address(value):
    if type(value) is not str or not value.startswith('/') or value.startswith('//') or len(value)>4096:return None
    try:u=urlsplit(value);pairs=parse_qsl(u.query,keep_blank_values=True,max_num_fields=6)
    except ValueError:return None
    if u.scheme or u.netloc or u.fragment or u.path!='/stok/karung/detail' or len(dict(pairs))!=len(pairs):return None
    q=dict(pairs)
    if set(q)-{'material','ukuran','merk','pemilik','sumber_page'}:return None
    material=q.get('material','');brand=q.get('merk','');size=q.get('ukuran','');owner=q.get('pemilik','pabrik');page=q.get('sumber_page','1')
    if not material or len(material)>128 or len(brand)>256 or not size.isascii() or not size.isdigit() or int(size)<=0 or int(size)>2147483647:return None
    if owner!='pabrik' and (not owner.isascii() or not owner.isdigit() or int(owner)<=0 or int(owner)>2147483647):return None
    if not page.isascii() or not page.isdigit() or int(page)<=0 or int(page)>2147483647:return None
    return (material,str(int(size)),brand,owner)


@dataclass(frozen=True)
class Reference:
    identity:tuple
    label:str=field(repr=False)


def references(context):
    """Already-read native Packaging DTOs, never a new DB/source lookup."""
    result=[]
    for row in context.get('karung',()):
        if row.get('pemilik_tunggal') is not True:continue
        code,size,brand,owner=row.get('kode'),row.get('ukuran'),row.get('merk') or '',row.get('pemilik_id')
        if type(code) is not str or type(size) is not int or type(brand) is not str or owner is not None and type(owner) is not int:continue
        identity=(code,str(size),brand,str(owner) if owner else 'pabrik')
        if address('/stok/karung/detail?'+urlencode(dict(zip(('material','ukuran','merk','pemilik'),identity)))) is None:continue
        result.append(Reference(identity,f'{code} · {size} kg · {brand or "Tanpa merek"}'))
    for group in context.get('daftar',()):result.extend(references(group))
    if context.get('stok_jasa'):result.extend(references(context['stok_jasa']))
    return result


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static';meta=json.loads((folder/'kerangka-karung-detail-ui.meta.json').read_text())
    if meta.get('versi')!=1 or hashlib.sha256((folder/'kerangka-karung-detail-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256'):raise ValueError('Karung detail structure program mismatch')
    return meta


def catalog(html,*,offers,source,cap,context,session):
    from bs4 import BeautifulSoup
    from app.web.giling_work_catalog import _visible
    if type(html) is not str or len(html.encode())>8*1024*1024 or type(source) is not str or len(source)>4096 or not all(type(v) is str and 0<len(v)<=512 for v in (cap,context,session)):return None
    u=urlsplit(source)
    if u.scheme or u.netloc or u.fragment or not u.path.startswith('/'):return None
    main=BeautifulSoup(html,'html.parser').select_one('#isi-halaman')
    if main is None:return None
    links=[a for a in main.select(SELECTOR) if _visible(a)]
    if len(links)>100:return None
    by_identity={}
    for offer in offers:
        if not isinstance(offer,Reference) or type(offer.label) is not str or not 0<len(offer.label)<=512:continue
        old=by_identity.get(offer.identity)
        if old and old.label!=offer.label:return None
        by_identity[offer.identity]=offer
    entries=[];seen=set()
    for a in links:
        target=a.get('href','');ident=address(target)
        if not ident or target in seen or a.get('target') or a.has_attr('download') or a.get('aria-disabled')=='true':continue
        offer=by_identity.get(ident)
        if offer is None:continue
        entries.append(dict(alamat=target,identity_label=offer.label));seen.add(target)
    if not 0<len(entries)<=50:return None
    envelope=dict(versi=1,sumber=aset()['sumber'],cap=cap,konteks=context,sesi=session,asal=source,asal_sha256=hashlib.sha256(source.encode()).hexdigest(),entries=entries)
    from jinja2.utils import htmlsafe_json_dumps
    return envelope if len(htmlsafe_json_dumps(envelope).encode())<=32768 else None


def finish(response,request,*,offers):
    """Decorate complete guarded native source lists; no direct double reader."""
    from app.web.portal.scope import is_customer_read
    if (not offers or request.method!='GET' or response.status_code!=200 or is_customer_read(request)
            or getattr(request.state,'portal_scope',None) is not None or 'text/html' not in response.headers.get('content-type','')):return response
    body=getattr(response,'body',b'');marker=b'<!-- isi-halaman:akhir -->'
    if not body or len(body)>8*1024*1024 or body.count(marker)!=1:return response
    from bs4 import BeautifulSoup
    doc=BeautifulSoup(body,'html.parser');frame=doc.select_one('.bingkai');form=doc.select_one('#formulir-sesi')
    cap=doc.html.get('data-versi','') if doc.html else '';context=frame.get('data-pindah-konteks','') if frame else '';token=form.get('data-token','') if form else ''
    source=request.url.path+('?' + request.url.query if request.url.query else '')
    try:envelope=catalog(body.decode(),offers=offers,source=source,cap=cap,context=context,session=token)
    except (ValueError,OSError):return response
    if envelope is None:return response
    from jinja2.utils import htmlsafe_json_dumps
    attrs=''.join(' '+name+'="'+escape(value,quote=True)+'"' for name,value in [('data-cap',cap),('data-konteks',context),('data-source-address',source),('data-source-sha',envelope['asal_sha256'])])
    host=('<script type="application/json" id="padi-karung-detail-catalog"'+attrs+'>'+str(htmlsafe_json_dumps(envelope))+'</script>').encode()
    response.body=body.replace(marker,host+marker,1);response.headers['Content-Length']=str(len(response.body));response.headers['Cache-Control']='private, no-store';return response
