"""Kabar structure: no notification rows, status writes or history watermark."""
from urllib.parse import parse_qsl,urlencode

def deskripsi(path,query=''):
    if path!='/kabar' or len(query)>2048:return None
    try:pairs=parse_qsl(query,keep_blank_values=True,max_num_fields=5)
    except ValueError:return None
    q=dict(pairs)
    if len(q)!=len(pairs) or set(q)-{'tab','jenis','batas','sampai','sebelum'}:return None
    for key,minimum,maximum,default in [('batas',1,100,'30'),('sampai',0,2147483647,None),('sebelum',1,2147483647,None)]:
        value=q.get(key,default)
        if value is not None and (not value.isascii() or not value.isdigit() or not minimum<=int(value)<=maximum):return None
    address=path+('?' +query if query else '')
    tabs=[]
    for key,label in [('', 'Semua'),('belum','Belum dibaca')]:
        values={**q,'tab':key,'batas':'30'};values.pop('sebelum',None)
        tabs.append(dict(key=key,label=label,href='/kabar?'+urlencode(values)))
    return dict(alamat=address,tab='belum' if q.get('tab')=='belum' else '',tabs=tabs)

async def dokumen(request,akun):
    spec=deskripsi(request.url.path,request.url.query)
    if (request.method!='GET' or spec is None or request.headers.get('X-Pindah')=='1'
        or not (request.headers.get('X-Kerangka-Halaman')=='1' or request.headers.get('Sec-Fetch-Mode')=='navigate' and request.headers.get('Sec-Fetch-Dest') in {'document','empty'})
        or akun is None or getattr(request.state,'akun',None) is not akun
        or getattr(request.state,'portal_scope',None) is not None
        or getattr(akun,'harus_ganti_sandi',None) is not False):return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):return None
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    from app.web.tampilan import render
    response=render(request,'kabar_kerangka.html',**await konteks_kerangka(request,akun),
        layar='kabar',KABAR_SHELL={**spec,'stamp':penanda_konteks(request,akun)+'|'+spec['alamat']})
    response.headers['Cache-Control']='private, no-store';return response
