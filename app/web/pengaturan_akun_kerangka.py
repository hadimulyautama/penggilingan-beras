"""Usulan kerangka Akun saya; belum terpasang pada handler/registry.

Root wajib menjalankan ``butuh_akun`` lagi untuk GET isi dan memakai reader
``pengaturan.halaman_pengaturan`` asli. Ini bentuk, bukan izin atau snapshot.
Tidak menyediakan kontrak kredensial, perubahan peran, atau penyimpanan.
"""
from __future__ import annotations

from urllib.parse import urlsplit

ALAMAT = '/pengaturan/akun'
JENIS = 'pengaturan-akun'


def spesifikasi(path: str, query: str = '') -> dict | None:
    """Jangan mengambil alih hasil POST native, error, atau target bebas."""
    if path != ALAMAT or query:
        return None
    return dict(kind=JENIS, title='Nama & kata sandi',
                alamat=ALAMAT, kembali='/pengaturan',
                sandi='/ganti-sandi?kembali_pengaturan=/pengaturan/akun')


def data_url_sah(url: str) -> bool:
    """URL baca dipasok integrator, tidak diterima dari input request."""
    if not isinstance(url, str):
        return False
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    return not (u.scheme or u.netloc or u.query or u.fragment) and u.path == (
        '/api/halaman-bertahap/' + JENIS)


async def kerangka(request, akun, konteks):
    """Sesudah dependency akun native; tanpa pembacaan referensi/domain.

    Identity equality adalah assertion integrasi, bukan pengganti butuh_akun.
    ``konteks`` memuat navigasi asli dan SHELL stamp/data_url dari integrator.
    """
    spec = spesifikasi(request.url.path, request.url.query)
    if (spec is None or request.method != 'GET'
            or getattr(request.state, 'portal_scope', None) is not None
            or getattr(request.state, 'akun', None) is not akun
            or akun is None):
        return None
    shell = konteks.get('SHELL', {})
    if (not isinstance(shell.get('stamp'), str) or not shell['stamp']
            or not data_url_sah(shell.get('data_url'))):
        return None
    from app.web.tampilan import render
    response = render(request, 'pengaturan_akun_kerangka.html',
                      **{**konteks, 'layar': 'pengaturan',
                         'AKUN_KERANGKA': {**spec, 'stamp': shell['stamp'],
                                           'data_url': shell['data_url']}})
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
