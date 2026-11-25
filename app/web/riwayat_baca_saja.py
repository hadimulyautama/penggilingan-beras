"""Klasifikasi presentasi History native; bukan izin atau status transaksi."""
from starlette.requests import Request


def riwayat_baca_saja(request, akun, *, jenis, process_id, boleh_koreksi):
    """Hanya dokumen internal tanpa pintu editor yang boleh tanpa marker.

    Caller GET asli telah memeriksa sesi, lokasi dan proses. Unknown, Portal,
    feedback/aksi/filter maupun bentuk akun yang tak lengkap tetap memakai
    veto editor lama. Tidak ada pembacaan state draf atau perubahan izin.
    """
    if (not isinstance(request, Request) or akun is None
            or jenis not in ('giling', 'sosoh')
            or type(process_id) is not int or not 0 < process_id <= 2147483647
            or boleh_koreksi is not False
            or request.method != 'GET'
            or request.url.path != f'/riwayat-{jenis}/{process_id}'
            or request.scope.get('query_string') != b''
            or getattr(request.state, 'akun', None) is not akun
            or getattr(request.state, 'portal_scope', None) is not None
            or getattr(akun, 'user', None) is None
            or getattr(akun, 'harus_ganti_sandi', None) is not False
            or getattr(akun, 'is_admin', None) is not False):
        return False
    return True
