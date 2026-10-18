"""Cap halaman untuk klien HTTP sintetis (browser membacanya dari formulir)."""
from app.web import csrf, security


def cap_formulir(c):
    # Fixture lama memasang cookie tanpa domain; Set-Cookie dari aplikasi
    # menghasilkan cookie berdomain. Yang terakhir diterima mewakili sesi
    # halaman baru, sama dengan request yang sudah melewati render halaman.
    def nilai(nama):
        nilai = [k.value for k in c.cookies.jar if k.name == nama]
        return nilai[-1] if nilai else ''
    return csrf.untuk_sesi(nilai(csrf.NAMA_COOKIE),
        security.baca_token(nilai(security.NAMA_COOKIE)), nilai('produksi_lihat'))
