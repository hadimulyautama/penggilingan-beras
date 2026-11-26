"""Rincian perintah eksplisit; kerangka netral tidak membaca record/saldo."""
from functools import lru_cache
from pathlib import Path
import re

PROTOTYPE = '/barang-keluar/2147483647?rincian_perintah=1'
KEYS = {'rincian_perintah','q','status','sejak','sebelum','tab_detail','kembali','kembali_kerja'}

def alamat_kerangka(raw):
    from urllib.parse import urlsplit, parse_qs
    if not isinstance(raw,str) or len(raw)>4096 or '\\' in raw or any(ord(c)<32 for c in raw):return False
    try:u=urlsplit(raw);q=parse_qs(u.query,keep_blank_values=True)
    except ValueError:return False
    m=re.fullmatch(r'/barang-keluar/([1-9]\d{0,9})',u.path)
    return bool(not(u.scheme or u.netloc or u.fragment) and m and int(m[1])<=2147483647
                and q.get('rincian_perintah')==['1'] and not(set(q)-KEYS)
                and all(len(v)==1 for v in q.values())
                and q.get('tab_detail',['ringkasan'])[0] in ('ringkasan','barang','tiket','riwayat'))

async def pembaca(request,akun):
    from app.web.retur_supplier_kerangka import pembaca as internal
    from app.web.api import _is_g2_operator
    from app.peran import can_see_financials
    return internal(request,akun) and (can_see_financials(akun.user) or await _is_g2_operator(akun.user))

@lru_cache(maxsize=1)
def aset():
    root=Path(__file__).resolve().parents[2]
    paths=['hmu_tampilan/static/pengiriman-retur.css','hmu_tampilan/static/pengiriman-kontrol.css',
           'app/web/static/detail_kirim_retur.css','app/web/static/status-pengiriman.css',
           'hmu_tampilan/static/catat-muatan.css','hmu_tampilan/static/verifikasi-pengiriman.css']
    css='\n'.join((root/p).read_text() for p in paths)
    tabs=(root/'app/web/static/detail_kirim_retur.js').read_text()
    verification=(root/'hmu_tampilan/static/verifikasi-pengiriman.js').read_text()
    reader=(root/'app/web/static/pengiriman-detail-kerangka.js').read_text()
    if '</style' in css.lower() or re.search(r'@import|url\s*\(',css,re.I) or any('</script' in s.lower() for s in (tabs,verification,reader)) or sum(len(s.encode()) for s in (css,tabs,verification,reader))>131072:raise ValueError('Aset rincian perintah di luar kontrak')
    return dict(css=css,tabs=tabs,verification=verification,reader=reader)

async def susun(request,akun,*,navigasi):
    from fastapi import Request
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE,baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not await pembaca(request,akun):return None
    state={**request.scope.get('state',{}),'menyusun_kerangka_langsung':True,'frame_kerangka_langsung':True}
    native=Request({**request.scope,'path':'/barang-keluar/2147483647','raw_path':b'/barang-keluar/2147483647','query_string':b'rincian_perintah=1','state':state})
    context={**navigasi,'layar':'barang_keluar','MENU_AKTIF':'barang_keluar','pkd_aset':aset(),
             'pkd_context':penanda_konteks(request,akun),'BOLEH_PERINTAH':False,'BOLEH_MUAT':False}
    body=render(native,'pengiriman_detail_kerangka.html',**context).body
    if len(body)>393216:return None
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None)
    result=dict(versi=1,cap=CAP_ASET,konteks=penanda_konteks(request,akun),
                sesi=csrf.untuk_sesi(nonce,baca_token(request.cookies.get(NAMA_COOKIE)),request.cookies.get('produksi_lihat','')),html=body.decode())
    return result if len(htmlsafe_json_dumps(result).encode())<=524288 else None
