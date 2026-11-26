"""Struktur detail baca; angka, cakupan dan tindakan tetap dari GET native."""
from functools import lru_cache
from pathlib import Path
import re
from fastapi import Request

PATH = '/riwayat-retur-supplier'
PROTOTYPE = '__RSD_ID__'
BLUEPRINT = {
    'ringkasan': [('Ringkasan retur', ['Diajukan', 'Keluar awal tercatat', 'Keluar efektif saat ini']),
                 ('Barang pada retur', ['Diajukan', 'Aktual dimuat', 'Keluar awal tercatat', 'Keluar efektif saat ini']),
                 ('Pencatatan & perubahan aktual', ['Pengaju', 'Waktu pengajuan', 'Catatan keluar', 'Metode verifikasi']),
                 ('Penerimaan & sumber', ['Supplier', 'Penerimaan asal', 'Tiket masuk asal', 'Nota pembelian'])],
    'timbang': [('Tiket retur terkini', ['Status tiket', 'Revisi terkini', 'Timbang I · kosong', 'Timbang II · bermuatan', 'Hasil akhir terkini']),
               ('Rekaman timbang saat pemeriksaan', ['Tiket', 'Revisi tiket saat pemeriksaan', 'Hasil timbang']),
               ('Verifikasi PadiFlow', ['Metode', 'Pemeriksa', 'Waktu']),
               ('Riwayat hasil pemeriksaan', ['Pemeriksaan', 'Hasil']),
               ('Koreksi tiket yang relevan', ['Perubahan bobot', 'Alasan'])],
    'stok': [('Mutasi barang & saldo historis', ['Catatan keluar', 'Jumlah keluar']),
             ('Rincian stok per barang', ['Stok fisik sebelum', 'Barang aktual keluar', 'Stok fisik sesudah', 'Stok tersedia sesudah transaksi'])],
    'jejak': [('Jejak pengajuan & penyelesaian', ['Pelaksana', 'Waktu', 'Alasan']),
              ('Dokumen & tautan', ['Penerimaan asal', 'Pengajuan', 'Tiket retur', 'Mutasi barang keluar'])],
}


def pembaca(request, akun):
    from app.web.portal.scope import is_customer_read
    from hmu_identitas import peran as P
    return (not is_customer_read(request) and not getattr(request.state, 'portal_scope', None)
            and (P.operator_saja(akun.user.role) or P.admin_keatas(akun.user.role)))


@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    styles = []
    for name, folder in [('laporan-riwayat.css', 'hmu_tampilan'), ('laporan-kontrol.css', 'hmu_tampilan'),
                         ('retur_supplier.css', 'app/web'), ('riwayat_retur_supplier.css', 'app/web'),
                         ('riwayat-sosoh-desain.css', 'app/web'), ('riwayat-retur-supplier-desain.css', 'app/web')]:
        code = (root/folder/'static'/name).read_text()
        if '</style' in code.lower() or re.search(r'@import|url\s*\(', code, re.I):
            raise ValueError('Aset riwayat retur tidak mandiri')
        styles.append((name, code))
    native = (root/'app/web/static/riwayat-retur-supplier-desain.js').read_text()
    controller = (root/'app/web/static/retur-supplier-kerangka.js').read_text()
    if any('</script' in x.lower() for x in (native, controller)) or sum(len(x.encode()) for _, x in styles)+len(native.encode())+len(controller.encode()) > 196608:
        raise ValueError('Batas aset riwayat retur tidak sesuai')
    return dict(styles=styles, native=native, controller=controller)


async def susun(request, akun, *, navigasi):
    from app.web.kerangka_langsung import kemas_frame
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from app.web.riwayat_retur_supplier import TABS
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not pembaca(request, akun):
        return None
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True,
             'frame_kerangka_langsung': True}
    frames = {}
    for tab in BLUEPRINT:
        path = PATH+'/'+PROTOTYPE
        native = Request({**request.scope, 'path': path, 'raw_path': path.encode(),
                          'query_string': ('tab='+tab).encode(), 'state': dict(state)})
        context = dict(navigasi)
        context.update(layar='riwayat_retur_supplier_detail', kembali=PATH+'?',
                       rsd_tab=tab, rsd_tabs=TABS, rsd_blueprint=BLUEPRINT[tab],
                       rsd_aset=aset(), rsd_context=penanda_konteks(request, akun))
        response = render(native, 'retur_supplier_kerangka.html', **context)
        response.body = re.sub(rb'(<button\b[^>]*?)(\sdata-lk-cetak)(?=[\s=>])',
            rb'\1 disabled aria-describedby="rsd-baca-status"\2', response.body)
        if response.status_code != 200 or len(response.body) > 524288:
            return None
        frames[tab] = response.body.decode()
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')),
                  **kemas_frame(frames))
    return result if len(htmlsafe_json_dumps(result).encode()) <= 1572864 else None
