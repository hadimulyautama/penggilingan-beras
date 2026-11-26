"""Kerangka daftar saja; isi/filter/otorisasi tetap GET native."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode
import re
from fastapi import Request
from app.web.retur_supplier_kerangka import pembaca
PATH='/riwayat-retur-supplier'

@lru_cache(maxsize=1)
def aset():
    root=Path(__file__).resolve().parents[2]
    files=[('laporan-riwayat.css','hmu_tampilan','style'),('laporan-kontrol.css','hmu_tampilan','style'),
           ('riwayat.css','app/web','style'),('riwayat-sosoh-desain.css','app/web','style'),
           ('riwayat-daftar-proses.css','app/web','style'),('retur_supplier.css','app/web','style'),
           ('riwayat_retur_supplier.css','app/web','style'),('daftar-retur-supplier-desain.css','app/web','style'),
           ('laporan-kontrol.js','hmu_tampilan','script'),('riwayat-daftar-proses.js','app/web','script'),
           ('daftar-retur-supplier-desain.js','app/web','script'),('retur-supplier-daftar-kerangka.js','app/web','script')]
    result=[];total=0
    for name,folder,tag in files:
        code=(root/folder/'static'/name).read_text();total+=len(code.encode())
        if not code or '</'+tag in code.lower() or total>196608 or tag=='style' and re.search(r'@import|url\s*\(',code,re.I):
            raise ValueError('Aset daftar retur tidak mandiri')
        result.append((name,code,tag))
    return result

def paket(body):
    html=body.decode()
    for name,code,tag in aset():
        pattern=(r'<link rel="stylesheet" href="/static/'+re.escape(name)+r'\?[^"<>]+">' if tag=='style' else r'<script src="/static/'+re.escape(name)+r'\?[^"<>]+"(?: defer)?></script>')
        html,n=re.subn(pattern,lambda _: '<'+tag+' data-rrs-aset="'+name+'">'+code+'</'+tag+'>',html)
        if n!=1:raise ValueError('Referensi aset daftar retur tidak tunggal')
    return re.sub(rb'(<button\b[^>]*?)(\sdata-lk-cetak)(?=[\s=>])',rb'\1 disabled aria-describedby="rrs-baca-status"\2',html.encode())

async def susun(request,akun,*,navigasi):
    from app.web.kerangka_langsung import kemas_frame
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE,baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from app.services.riwayat_retur_supplier import STATUS
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not pembaca(request,akun):return None
    state={**request.scope.get('state',{}),'menyusun_kerangka_langsung':True,'frame_kerangka_langsung':True}
    native=Request({**request.scope,'path':PATH,'raw_path':PATH.encode(),'query_string':b'','state':state})
    context=dict(navigasi);context.update(layar='riwayat_retur_supplier',data=None,error=None,statuses=STATUS,
        filter=dict(q='',awal='',akhir='',status='',supplier=None,gudang=None,penerimaan=None),konteks='',
        href=lambda **kw:PATH+'?'+urlencode({k:v for k,v in kw.items() if v not in ('',None)}),rrs_shell=True,rrs_context=penanda_konteks(request,akun))
    response=render(native,'riwayat_retur_supplier.html',**context)
    body=paket(response.body)
    if response.status_code!=200 or len(body)>524288:return None
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None)
    result=dict(versi=1,cap=CAP_ASET,konteks=penanda_konteks(request,akun),status=list(STATUS),
        sesi=csrf.untuk_sesi(nonce,baca_token(request.cookies.get(NAMA_COOKIE)),request.cookies.get('produksi_lihat','')),
        **kemas_frame({PATH:body.decode()}))
    return result if len(htmlsafe_json_dumps(result).encode())<=786432 else None
