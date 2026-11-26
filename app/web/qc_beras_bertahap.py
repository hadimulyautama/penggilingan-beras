"""Kerangka baca QC beras; editor Admin dan portal tetap di jalur native."""
from functools import lru_cache
from pathlib import Path
import re
from fastapi import HTTPException

JENIS = 'beras-hasil-sosoh'
PROTOTYPE = '__QC_BERAS_REF__'
TAB = ('ringkasan', 'sampel', 'sesi', 'asal')
KOLOM = {
    'hasil': ('Jenis beras', 'Total aktual', 'Sesi menurut QC'),
    'sampel': ('Sampel', 'Jenis saat diambil', 'Waktu pengambilan',
               'Hasil pemeriksaan', 'Waktu isi lab', 'Pemetaan estimasi'),
    'sesi': ('Sesi', 'Estimasi waktu garapan', 'Durasi aktif estimasi',
             'Bobot sesi · estimasi', 'Sampel dan hasil QC'),
}


def pembaca(request, akun):
    from app.web.portal.scope import is_customer_read
    return not is_customer_read(request) and not akun.is_admin


def memakai(request, akun, jenis):
    return (jenis == JENIS and pembaca(request, akun)
            and not getattr(request.state, 'menyusun_kerangka_langsung', False)
            and all(k == 'tab_qc' and len(request.query_params.getlist(k)) == 1
                    for k in request.query_params)
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('X-Pindah') != '1'
                 and request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in {'document', 'empty'}))


@lru_cache(maxsize=1)
def aset():
    from app.web.qc_detail_bertahap import aset as aset_detail
    root = Path(__file__).resolve().parents[2]
    shared = aset_detail()
    css = (root/'hmu_tampilan/static/qc-sosoh.css').read_text()
    controller = (root/'app/web/static/qc-beras-kerangka.js').read_text()
    if '</style' in css.lower() or re.search(r'@import|url\s*\(', css, re.I) or '</script' in controller.lower():
        raise ValueError('Aset QC beras tidak mandiri')
    styles = [(n, c) for n, c in shared['styles'] if n != 'qc-detail.css'] + [('qc-sosoh.css', css)]
    if sum(len(c.encode()) for _, c in styles)+len(controller.encode())+len(shared['native'].encode()) > 196608:
        raise ValueError('Batas aset QC beras tidak sesuai')
    return dict(styles=styles, controller=controller, native=shared['native'])


async def kerangka(request, akun, referensi, *, navigasi=None):
    from app.web.qc_bertahap import boleh
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    from app.web.laporan_navigasi import siapkan
    from app.web.tampilan import render
    if not pembaca(request, akun) or not await boleh(akun.user, JENIS):
        raise HTTPException(403, 'Riwayat QC ini tidak tersedia untuk peran Anda.')
    context = dict(await konteks_kerangka(request, akun) if navigasi is None else navigasi)
    await siapkan(request, context)
    tab = request.query_params.get('tab_qc', 'ringkasan')
    context.update(layar='riwayat_qc', judul='QC beras hasil sosoh', jenis=JENIS,
                   qc_ref=referensi, qc_tab=tab if tab in TAB else 'ringkasan',
                   qc_kolom=KOLOM, qc_aset=aset(), qc_context=penanda_konteks(request, akun))
    response = render(request, 'qc_beras_bertahap.html', **context)
    # Cetak bergantung pada data yang sudah terbaca, bukan placeholder.
    response.body = re.sub(rb'(<button\b[^>]*?)(\sdata-lk-cetak)(?=[\s=>])',
        rb'\1 disabled aria-describedby="qc-beras-status"\2', response.body)
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    return response
