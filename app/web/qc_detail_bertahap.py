"""Struktur baca detail QC. Data dan batas lot tetap milik handler native."""
from functools import lru_cache
from pathlib import Path
import re
from fastapi import HTTPException
from app.web.detail_qc import KATEGORI, TAB

PROTOTYPE = '__QC_REF__'


def memakai(request, jenis):
    from app.web.portal.scope import is_customer_read
    return (jenis in KATEGORI and not is_customer_read(request)
            and not getattr(request.state, 'menyusun_kerangka_langsung', False)
            and not any(k not in {'tab_qc','putaran','kembali_qc','kembali_jasa','kembali_stok','kembali_kerja'} for k in request.query_params)
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('X-Pindah') != '1'
                 and request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


@lru_cache(maxsize=1)
def aset():
    root=Path(__file__).resolve().parents[2]
    values=[]
    for name,folder in [('laporan-riwayat.css','hmu_tampilan'),('laporan-kontrol.css','hmu_tampilan'),
                        ('riwayat.css','app/web'),('riwayat-sosoh-desain.css','app/web'),
                        ('riwayat-qc-desain.css','app/web'),('qc-detail.css','app/web')]:
        code=(root/folder/'static'/name).read_text()
        if '</style' in code.lower() or re.search(r'@import|url\s*\(',code,re.I):
            raise ValueError('Aset detail QC tidak mandiri')
        values.append((name,code))
    native=(root/'app/web/static/riwayat-qc-desain.js').read_text()
    controller=(root/'app/web/static/qc-detail-kerangka.js').read_text()
    if any('</script' in code.lower() for code in [native,controller]) or sum(len(s.encode()) for _,s in values)+len(native.encode())+len(controller.encode())>196608:
        raise ValueError('Batas aset detail QC tidak sesuai')
    return dict(styles=values,native=native,controller=controller)


async def kerangka(request,akun,jenis,referensi,*,navigasi=None):
    from app.web.qc_bertahap import boleh
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    from app.web.laporan_navigasi import siapkan
    from app.web.tampilan import render
    from app.web.layar_riwayat import QC_PAGES
    from app.web.detail_qc import konteks
    if jenis not in KATEGORI or not await boleh(akun.user,jenis):
        raise HTTPException(403,'Riwayat QC ini tidak tersedia untuk peran Anda.')
    context=dict(await konteks_kerangka(request,akun) if navigasi is None else navigasi)
    await siapkan(request,context)
    # Gunakan parser tab/tautan baca existing; rounds kosong tidak dirender
    # sebagai data atau jumlah, dan tidak membuka catatan QC.
    nav=konteks(request,jenis,{'rounds':[]})
    context.update(layar='riwayat_qc',judul=QC_PAGES[jenis][0],jenis=jenis,
                   qc_ref=referensi,qc_tab=nav['qc_tab'],
                   qc_tabs=TAB,qc_aset=aset(),qc_context=penanda_konteks(request,akun),
                   kembali=nav['kembali'])
    response=render(request,'qc_detail_bertahap.html',**context)
    # Batasi ke atribut tombol. Controller inline juga memakai selector
    # data-lk-cetak; penggantian teks global akan merusak kode itu.
    response.body=re.sub(rb'(<button\b[^>]*?)(\sdata-lk-cetak)(?=[\s=>])',
                         rb'\1 disabled aria-describedby="qc-detail-status"\2',response.body)
    response.headers['content-length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store'
    return response
