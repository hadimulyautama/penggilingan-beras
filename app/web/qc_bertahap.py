"""Kerangka daftar QC; gerbang dan pembaca hasil tetap native."""
from functools import lru_cache
from pathlib import Path
import re
from fastapi import HTTPException, Request
from app.web.laporan_navigasi import QC as PILIHAN_QC

TUJUAN = {'qc-'+jenis: dict(path=path, jenis=jenis, label=label)
          for jenis, label, path, _ in PILIHAN_QC}
KOLOM = ['Batch / proses · waktu', 'Asal bahan', 'Nomor polisi',
         'Rata-rata QC', 'Putaran QC', '']


async def boleh(user, jenis):
    # Predicate yang sama dipakai handler lama dan pembentuk kerangka.
    # Jangan mengganti gerbang gabah/PK dengan kelompok menu G1/G2.
    from app.web.api import _is_gabah_operator, _is_g2_operator, _is_jenis_operator
    if jenis not in {v['jenis'] for v in TUJUAN.values()}:
        return False
    return await (_is_gabah_operator(user) if jenis in ('gabah-basah','gabah-kering')
        else _is_jenis_operator(user,'penggilingan') if jenis=='pk-hasil-giling'
        else _is_jenis_operator(user,'penyosohan') if jenis=='beras-hasil-sosoh'
        else _is_g2_operator(user))


def memakai(request, kind):
    from app.web.portal.scope import is_customer_read
    return (kind in TUJUAN and not is_customer_read(request)
        and not request.url.query and request.url.path==TUJUAN[kind]['path']
        and not getattr(request.state,'isi_halaman_bertahap',False)
        and not getattr(request.state,'menyusun_kerangka_langsung',False)
        and (request.headers.get('X-Kerangka-Halaman')=='1'
             or request.headers.get('X-Pindah')!='1'
             and request.headers.get('Sec-Fetch-Mode')=='navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


@lru_cache(maxsize=1)
def aset():
    root=Path(__file__).resolve().parents[2]
    result=[];total=0
    for name, folder, tag in (
        ('laporan-riwayat.css','hmu_tampilan','style'),
        ('laporan-kontrol.css','hmu_tampilan','style'),
        ('laporan-kontrol.js','hmu_tampilan','script'),
        ('riwayat.css','app/web','style'),
        ('riwayat-sosoh-desain.css','app/web','style'),
        ('riwayat-qc-desain.css','app/web','style'),
        ('qc-kerangka.js','app/web','script'),
        ('halaman-bertahap.js','app/web','script')):
        code=(root/folder/'static'/name).read_text();total+=len(code.encode())
        if not code or total>196608 or '</'+tag in code.lower():
            raise ValueError('Batas aset QC tidak sesuai')
        if tag=='style' and re.search(r'@import|url\s*\(',code,re.I):
            raise ValueError('Aset QC membutuhkan URL tambahan')
        result.append((name,code,tag))
    return tuple(result)


async def kerangka(request, akun, kind, *, navigasi=None):
    from app.web.halaman_bertahap import konteks_kerangka, penanda
    from app.web.laporan_navigasi import siapkan
    from app.web.layar_riwayat import QC_PAGES
    from app.web.tampilan import render
    config=TUJUAN[kind]
    if not await boleh(akun.user,config['jenis']):
        raise HTTPException(403,'Riwayat QC ini tidak tersedia untuk peran Anda.')
    context=dict(await konteks_kerangka(request,akun) if navigasi is None else navigasi)
    await siapkan(request,context)
    context.update(layar='riwayat_qc',jenis=config['jenis'],
        judul=('QC beras hasil sosoh' if config['jenis']=='beras-hasil-sosoh' else QC_PAGES[config['jenis']][0]),
        QC_KOLOM=KOLOM,SHELL=dict(kind=kind,stamp=penanda(request,akun,kind),
                                  data_url='/api/halaman-bertahap/'+kind))
    response=render(request,'qc_bertahap.html',**context)
    response.body=response.body.replace(b'data-lk-cetak',b'disabled aria-describedby="qc-baca-status" data-lk-cetak')
    if getattr(request.state,'frame_kerangka_langsung',False):
        html=response.body.decode()
        for name,code,tag in aset():
            pattern=(r'<link rel="stylesheet" href="/static/'+re.escape(name)+r'\?[^"<>]+">' if tag=='style'
                else r'<script src="/static/'+re.escape(name)+r'\?[^"<>]+" defer></script>')
            html,count=re.subn(pattern,lambda _: '<'+tag+' data-qc-aset-native="'+name+'">'+code+'</'+tag+'>',html)
            if count!=1:raise ValueError('Referensi aset QC tidak tunggal')
        response.body=html.encode()
    response.headers['content-length']=str(len(response.body));response.headers['Cache-Control']='private, no-store'
    return response


async def susun(request,akun,*,navigasi):
    from app.web.kerangka_langsung import kemas_frame
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE,baca_token
    from app.web import csrf
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    state={**request.scope.get('state',{}),'menyusun_kerangka_langsung':True,'frame_kerangka_langsung':True}
    frames={}
    for kind,config in TUJUAN.items():
        if not await boleh(akun.user,config['jenis']):continue
        path=config['path'];native=Request({**request.scope,'path':path,'raw_path':path.encode(),'query_string':b'','state':dict(state)})
        response=await kerangka(native,akun,kind,navigasi=navigasi)
        if response.status_code!=200 or len(response.body)>524288:return None
        frames[path]=response.body.decode()
    if not frames:return None
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None)
    result=dict(versi=1,cap=CAP_ASET,konteks=penanda_konteks(request,akun),
        sesi=csrf.untuk_sesi(nonce,baca_token(request.cookies.get(NAMA_COOKIE)),request.cookies.get('produksi_lihat','')),
        **kemas_frame(frames))
    return result if len(htmlsafe_json_dumps(result).encode())<=1572864 else None
