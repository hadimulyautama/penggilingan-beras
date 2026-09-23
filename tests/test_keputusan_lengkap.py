"""Setiap jenis keputusan yang DIKIRIM ke `b.meja` punya bloknya di layar.

Tiga kali dalam satu hari (23 September 2026) ditemukan pekerjaan yang ada di
DATA tetapi tak digambar di layar mana pun: tiket PK yang jenisnya tak dipetakan,
daftar asal silo yang sudah habis, dan — di sini — tiga dari enam jenis keputusan.

Yang ketiga paling lama tak terlihat. `keputusan.html` memegang daftar bloknya
sendiri, berisi tiga id aksi yang diketik tangan, sementara `berjalan.untuk()`
mengirim enam. Harga PK luar & mutu PK luar masih terbaca di aplikasi Meja;
`betulkan_bobot_giling` — korban P6-03 dan tiket yang direvisi sengaja — tak
terbaca di mana pun sejak ia lahir. Pekerjaan yang menahan uang, tak tertagih,
tanpa satu pun tanda.

Uji ini membaca SUMBERNYA: tiap `aksi="…"` yang benar-benar di-append ke
`b.meja`, lalu menuntut tiap satunya punya blok. Jenis ketujuh yang lahir nanti
menjatuhkan uji ini, bukan menghilang diam-diam.
"""
from __future__ import annotations

import inspect
import re

from app.services import berjalan as svc
from app.web.layar_keputusan import AKSI_DIKENAL, JENIS_KEPUTUSAN


def _aksi_yang_dikirim_ke_meja() -> set[str]:
    """Id aksi pada tiap `b.meja.append(Baris(...))` di seluruh `berjalan`.

    Dibaca dari sumbernya, bukan didaftar tangan: daftar tangan di dalam uji
    adalah salinan kedua yang bisa ketinggalan persis seperti yang di templat.
    """
    sumber = inspect.getsource(svc)
    keluar = set()
    for m in re.finditer(r"b\.meja\.append\(", sumber):
        # Cukup sampai penutup append-nya; `aksi=` selalu di dalamnya.
        potongan = sumber[m.end():m.end() + 1200]
        a = re.search(r'aksi="([a-z_]+)"', potongan)
        if a:
            keluar.add(a.group(1))
    return keluar


def test_tiap_jenis_yang_dikirim_punya_bloknya():
    dikirim = _aksi_yang_dikirim_ke_meja()
    # Premisnya: uji ini benar-benar menemukan sesuatu untuk diperiksa.
    assert len(dikirim) >= 6, f"pembaca sumber tak menemukan append: {dikirim}"

    hilang = dikirim - set(AKSI_DIKENAL)
    assert not hilang, (
        f"jenis keputusan tanpa blok di layar: {sorted(hilang)}. "
        "Tambahkan ke JENIS_KEPUTUSAN — pekerjaan yang tak tampil "
        "tak akan ada yang mencarinya.")

    # Ketiga yang dulu hilang disebut namanya, supaya perbaikannya tak
    # tergulung balik tanpa ada yang menyadarinya.
    for aksi in ("harga_pk_luar", "qc_pk_luar", "betulkan_bobot_giling"):
        assert aksi in AKSI_DIKENAL, aksi


def test_daftar_blok_tak_menyebut_jenis_yang_tak_pernah_dikirim():
    """Kebalikannya juga dijaga: blok yang tak pernah berisi apa-apa adalah
    judul yang menagih pekerjaan yang tak ada, dan tagihan semacam itu
    mengajari orang mengabaikan tagihan."""
    dikirim = _aksi_yang_dikirim_ke_meja()
    asing = set(AKSI_DIKENAL) - dikirim
    assert not asing, f"blok untuk jenis yang tak pernah dikirim: {sorted(asing)}"


def test_daftarnya_di_kode_bukan_di_templat():
    """Templat yang memegang daftarnya sendiri tak bisa diuji terhadap data —
    dan itulah yang membuat ketiga jenis hilang selama berminggu-minggu."""
    import pathlib

    tpl = (pathlib.Path(__file__).resolve().parents[1]
           / "app/web/templates/keputusan.html").read_text()
    assert "{% for aksi, judul in JENIS_KEPUTUSAN %}" in tpl
    for aksi, _ in JENIS_KEPUTUSAN:
        assert f'"{aksi}"' not in tpl, f"id aksi {aksi} diketik lagi di templat"


def test_ada_jaring_untuk_jenis_yang_belum_punya_blok():
    """Uji di atas menjaga saat build; jaring ini menjaga saat jalan. Keduanya
    perlu: yang satu menuntut orang menambah blok, yang lain memastikan kartunya
    tetap terlihat sebelum orang itu sempat."""
    import pathlib

    tpl = (pathlib.Path(__file__).resolve().parents[1]
           / "app/web/templates/keputusan.html").read_text()
    assert 'rejectattr("aksi", "in", AKSI_DIKENAL)' in tpl
    assert "Keputusan lain" in tpl
