"""Navigasi baca detail QC; seluruh angka tetap disediakan layanan asal."""
import re
from urllib.parse import urlencode, urlsplit

KATEGORI = {'gabah-basah':'QC gabah basah', 'gabah-kering':'QC gabah kering',
            'pk-hasil-giling':'QC PK hasil giling', 'pk-luar':'QC PK luar'}
TAB = ('ringkasan', 'putaran', 'perhitungan', 'asal')
ASAL = (r'/(?:riwayat-qc/[\w-]+|pekerjaan|stok(?:/pk/detail)?|stok-pk-jasa|'
        r'barang-masuk(?:/\d+)?|jasa(?:/pelanggan/\d+)?|'
        r'riwayat-(?:giling|pengeringan|sosoh|transfer)(?:/\d+)?|'
        r'proses-aktif/(?:giling|pengeringan|pendinginan|sosoh)/[\w-]+)')


def konteks(request, jenis, kartu):
    q = dict(request.query_params)
    tab = q.get('tab_qc', 'ringkasan')
    if tab not in TAB:
        tab = 'ringkasan'
    try:
        nomor = int(q.get('putaran', len(kartu['rounds'])))
    except (ValueError, TypeError):
        nomor = len(kartu['rounds'])
    nomor = min(max(nomor, 1), len(kartu['rounds']))

    def halaman(tab=None, putaran=None):
        params = dict(q)
        if tab is not None: params['tab_qc'] = tab
        if putaran is not None: params['putaran'] = putaran
        return request.url.path + ('?' + urlencode(params) if params else '')

    # Konteks hanya tautan baca, bukan izin atau identitas pemilik.
    kembali = f'/riwayat-qc/{jenis}'
    for key in ('kembali_qc','kembali_jasa','kembali_stok','kembali_kerja'):
        nilai = q.get(key, '')
        try: u = urlsplit(nilai)
        except ValueError: continue
        if not u.scheme and not u.netloc and re.fullmatch(ASAL, u.path):
            kembali = nilai
            break
    # Referer hanya memulihkan halaman baca asal pada host yang sama.
    # Identitas data tetap berasal dari kode/ID dan scope backend.
    if kembali == f'/riwayat-qc/{jenis}':
        try: asal = urlsplit(request.headers.get('referer', ''))
        except ValueError: asal = None
        path = asal.path if asal else ''
        if path.startswith('/pelanggan/') and getattr(request.state, 'portal_scope', None):
            path = path[len('/pelanggan'):]
        if asal and asal.netloc == request.url.netloc and re.fullmatch(ASAL, path):
            kembali = path + ('?' + asal.query if asal.query else '')
            q['kembali_qc'] = kembali
    catatan = None
    for i, r in reversed(list(enumerate(kartu['rounds'], 1))):
        for label, nilai in r['detail']:
            if label == 'Catatan lab' and nilai and nilai != '':
                catatan = dict(teks=nilai, nomor=r['nomor'], posisi=i, waktu=r['waktu'])
                break
        if catatan: break
    return dict(qc_tab=tab, qc_nomor=nomor, qc_halaman=halaman,
                qc_kategori=KATEGORI[jenis], qc_catatan=catatan,
                qc_data_lama=any(label == 'Asal catatan' for r in kartu['rounds'] for label, _ in r['detail']),
                kembali=kembali)
