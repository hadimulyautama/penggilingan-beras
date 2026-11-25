"""Bounded presentation catalog from already-authorized DTOs and native links.

No SQL, no extra native read, no request-supplied identities. A catalog is a
presentation hint, not a grant. The next GET always repeats native ownership.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from bs4 import BeautifulSoup
from .detail_kerangka import deskripsi

ROOT=Path(__file__).resolve().parents[3]
NAMES={'portal/beranda.html','portal/jasa.html','portal/masuk.html','portal/riwayat.html',
       'detail_giling.html','riwayat_giling_detail.html','barang_masuk_detail_lama.html'}


def closed_giling_heading():
    """Same native pure identity and completed-title projection, no reader/SQL."""
    from .identitas_proses import identitas
    title=identitas('giling')['judul']
    return 'Hasil '+title[0].lower()+title[1:]

@lru_cache(maxsize=1)
def aset():
    p=ROOT/'app/web/static';m=json.loads((p/'kerangka-portal-detail-ui.meta.json').read_text())
    if m.get('versi')!=1 or hashlib.sha256((p/'kerangka-portal-detail-ui.js').read_bytes()).hexdigest()!=m.get('aset_sha256'):raise ValueError('Portal detail package mismatch')
    return m


def entries(name,ctx,content,scope):
    """Pure collection over the exact DTO projection; never enumerate scope IDs."""
    if name not in NAMES:return []
    s=BeautifulSoup(content,'html.parser');out=[]
    def add(href,code,heading,title,anchor):
        d=deskripsi(href)
        if d is None or not anchor or not all(isinstance(v,str) and v for v in (code,heading,title)) or len(code)>100 or max(len(heading),len(title))>180:return
        if anchor.get('href')!=href:return
        key=(d['kind'],d['resource'])
        item=next((e for e in out if (e['kind'],e['resource'])==key),None)
        if item and (item['code'],item['heading'],item['title'])!=(code,heading,title):return
        if item is None:
            item=dict(kind=d['kind'],resource=d['resource'],code=code,heading=heading,title=title,targets=[]);out.append(item)
        if href not in item['targets'] and len(item['targets'])<12:item['targets'].append(href)
    if name in {'portal/beranda.html','portal/jasa.html'}:
        for row in (ctx.get('progres') or [])[:50]:
            if row.get('jenis')!='giling' or row.get('kode') not in scope.codes:continue
            href=row.get('href');d=deskripsi(href)
            if not d or d['kind']!='giling' or d['resource']!=row['kode']:continue
            for card in s.select('[data-kode-proses]'):
                if card.get('data-kode-proses')!=row['kode']:continue
                heading=card.select_one('h2,.pelanggan-proses-judul')
                if not heading or heading.get_text(' ',strip=True)!=row.get('judul'):continue
                a=next((a for a in card.select('a[href]') if a['href']==href),None)
                add(href,row['kode'],row['judul'],row['kode'],a)
    elif name=='portal/riwayat.html':
        from .navigation import portal_url
        for row in (ctx.get('catatan') or {}).get('rows',[])[:25]:
            if row.get('jenis')!='giling' or row.get('kode') not in scope.codes:continue
            original=row.get('href')
            if not isinstance(original,str) or len(original)>4096:continue
            href=portal_url(original);d=deskripsi(href)
            if (not d or d['kind']!='giling-riwayat'
                or int(d['resource']) not in scope.resources.get('milling_process',())):continue
            for card in s.select('.pelanggan-catatan-baris[data-jenis="giling"]'):
                code=card.select_one('.pelanggan-kode');heading=card.select_one('h2')
                if (not code or code.get_text(' ',strip=True)!=row['kode'] or not heading
                    or heading.get_text(' ',strip=True)!=row.get('judul')):continue
                a=next((a for a in card.select('a.pelanggan-catatan-buka[href]') if a['href']==href),None)
                add(href,row['kode'],closed_giling_heading(),row['kode'],a)
    elif name=='portal/masuk.html':
        for row in (ctx.get('daftar_masuk') or {}).get('riwayat',[])[:25]:
            ident=row.get('id')
            if type(ident) is not int or ident not in scope.resources.get('timbangan_transaksi',()):continue
            href='/pelanggan'+row['href'] if row.get('href','').startswith('/barang-masuk/') else row.get('href','')
            d=deskripsi(href)
            if not d or d['kind']!='penerimaan' or d['resource']!=str(ident):continue
            for a in s.select('a.masuk-baris[href]'):
                code=a.select_one('.masuk-identitas small')
                goods=a.select_one('.masuk-jenis')
                if (a['href']!=href or not code or code.get_text(' ',strip=True)!=row['kode']
                    or not goods or goods.get_text(' ',strip=True)!=(row.get('jenis_nama') or row.get('jenis_kode'))):continue
                heading=row.get('jenis_nama') or {'gabah_basah':'Gabah basah','gabah_kering':'Gabah kering','pk':'PK','beras':'Beras','broken':'Broken'}.get(row.get('jenis'),row.get('jenis_kode'))
                if heading in {'PK','Beras PK'}:heading='Beras pecah kulit (PK)'
                add(href,row['kode'],heading,'Portal pelanggan',a)
    elif name=='riwayat_giling_detail.html':
        k=ctx.get('k');inti=ctx.get('portal_inti_proses') or {}
        ident=getattr(k,'id',None);code=getattr(k,'kode',None)
        if (ctx.get('jenis')!='giling' or type(ident) is not int
            or ident not in scope.resources.get('milling_process',()) or code not in scope.codes
            or inti.get('status')!='Selesai' or inti.get('kode')!=code):return []
        root=s.select_one('[data-riwayat-giling].pelanggan-detail');h=root.find('h1') if root else None
        if not h:return []
        title=ctx.get('page_title') or ctx.get('breadcrumb_detail') or 'Portal pelanggan'
        for a in root.select('.rhs-tabs a[role=tab][href]'):
            d=deskripsi(a['href'])
            if d and (d['kind'],d['resource'])==('giling-riwayat',str(ident)):
                add(a['href'],code,h.get_text(' ',strip=True),title,a)
    else:
        root=s.select_one('.pelanggan-proses-detail-ringkas' if name=='detail_giling.html' else '.penerimaan-detail')
        h=root.find('h1') if root else None
        if not h:return []
        if name=='detail_giling.html':
            d=ctx.get('d') or {};code=d.get('kode');inti=ctx.get('portal_inti_proses') or {}
            if d.get('jenis')!='giling' or code not in scope.codes or not inti.get('ringkas_aktif') or inti.get('judul')!='Penggilingan gabah':return []
            kind='giling';resource=code;title=ctx.get('page_title') or ctx.get('breadcrumb_detail') or 'Portal pelanggan'
        else:
            t=ctx.get('tiket') or {};ident=t.get('id');code=t.get('kode')
            if type(ident) is not int or ident not in scope.resources.get('timbangan_transaksi',()):return []
            kind='penerimaan';resource=str(ident);title=ctx.get('page_title') or ctx.get('breadcrumb_detail') or 'Portal pelanggan'
        for a in root.select('a[role=tab][href]'):
            d=deskripsi(a['href'])
            if d and (d['kind'],d['resource'])==(kind,resource):add(a['href'],code,h.get_text(' ',strip=True),title,a)
    return out


def dekorasi(request,name,ctx,content):
    if name not in NAMES:return content
    from .scope import ReadScope
    from .auth import csrf_context
    from hmu_tampilan import CAP_ASET
    scope=getattr(request.state,'portal_scope',None)
    source=getattr(request.state,'portal_native_address',None)
    if not isinstance(scope,ReadScope) or request.state.akun.user is not scope.reader or not isinstance(source,str) or not source.startswith('/pelanggan'):return content
    data=entries(name,ctx,content,scope)
    if not data:return content
    try:m=aset()
    except (OSError,ValueError,KeyError,TypeError):return content
    body=dict(versi=1,sumber=m['sumber'],cap=CAP_ASET,akun=str(scope.reader.account_id),sesi=csrf_context(request),address=source,entries=data)
    raw=json.dumps(body,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('&','\\u0026')
    if len(raw)>65536:return content
    # Inert private JSON follows the authorized content and survives native
    # main replacement. It contains only identities already visible there.
    return content+'<script type="application/json" id="padi-portal-detail-catalog">'+raw+'</script>'
