"""Beban tiap layar, dan apa yang dijalankan skripnya di layar yang salah.

Temuan QA UI-01, P-K-19, P-S-08 — 11 September 2026.

**UI-01.** `aksi.js` dimuat di enam layar dan SELALU menjalankan `muat()`,
yang memanggil dua endpoint termasuk yang terberat. Padahal hanya satu layar
yang punya wadah `#layar` untuk menampung hasilnya; di lima layar lain
hasilnya dibuang, lalu skripnya jatuh dengan "Cannot set properties of null".
Karena `pindah.js` menjalankan ulang skrip tiap perpindahan halaman DAN tiap
denyut, beban servernya kira-kira dua kali lipat dari yang diperlukan.

**P-K-19.** Bendera `disentuh` disetel saat orang menyentuh isian apa pun,
dan hanya direset saat halaman berpindah. Menutup lembar aksi tak
meresetnya, jadi sesudah menyentuh isian lalu membatalkan, segar-otomatis
MATI sampai orangnya pindah halaman — sepuluh denyut menghasilkan nol
permintaan.

**P-S-08.** Layar audit menghitung jumlah baris dengan memuat seluruh id-nya
ke memori, dan Kelola pengguna memuat seluruh tabel.
"""
from __future__ import annotations

import pathlib
import re

AKAR = pathlib.Path(__file__).resolve().parents[1] / "app"
AKSI_JS = (AKAR.parent / "hmu_tampilan/static/aksi.js").read_text()
PINDAH_JS = (AKAR.parent / "hmu_tampilan/static/pindah.js").read_text()


def js_kode(teks: str) -> str:
    """Sumber JS tanpa komentar.

    Pelajaran yang sudah tertulis di `tests/bantu.py::kode_saja`, kini untuk
    JavaScript: uji yang mencari POLA di dalam kode ikut menemukannya di
    dalam komentar yang MENJELASKAN pola itu — sehingga menulis penjelasan
    yang baik menjatuhkan ujinya sendiri.
    """
    teks = re.sub(r"/\*.*?\*/", "", teks, flags=re.S)
    return re.sub(r"(^|[^:])//.*$", r"\1", teks, flags=re.M)


# ─────────────────────────── UI-01 ───────────────────────────

def test_muat_hanya_jalan_bila_wadahnya_ada():
    """Katalog aksi hanya digambar di layar yang punya tempat untuknya."""
    assert "if ($(\"layar\"))" in AKSI_JS or "if (document.getElementById(\"layar\"))" in AKSI_JS, \
        "muat() masih dipanggil tanpa syarat"


def test_hanya_satu_template_yang_punya_wadah_layar():
    """Kalau suatu hari ada dua, syarat di atas berhenti menjelaskan apa pun
    dan harus ditinjau ulang — bukan didiamkan."""
    punya = [p.name for p in (AKAR / "web/templates").glob("*.html")
             if 'id="layar"' in p.read_text()]
    assert punya == ["aksi_lain.html"], punya


def test_aksi_js_tak_lagi_menyentuh_layar_yang_mungkin_tak_ada():
    """`$("layar").innerHTML` pada layar tanpa wadahnya melempar TypeError,
    dan TypeError menghentikan SELURUH skrip — termasuk pendengar tombol yang
    dipasang sesudahnya.

    Yang dicari: pemakaian LANGSUNG tanpa memeriksa dulu. Menyimpannya ke
    variabel lebih dahulu (`var wadah = $("layar"); if (wadah)`) justru
    bentuk yang benar.
    """
    assert '$("layar").innerHTML' not in js_kode(AKSI_JS)
    # Yang tersisa hanya di dalam `gambar()`, yang cuma dipanggil oleh
    # `muat()` — dan `muat()` sendiri sudah berpagar.
    # Menyimpannya ke variabel lebih dahulu tetap sah — yang dilarang adalah
    # memakainya langsung tanpa memeriksa. `gambar()` hanya dipanggil
    # `muat()`, yang sudah berpagar.
    langsung = [b.strip() for b in js_kode(AKSI_JS).splitlines()
                if '$("layar").' in b]
    assert not langsung, langsung


# ─────────────────────────── P-K-19 ───────────────────────────

def test_menutup_lembar_mereset_bendera_disentuh():
    """Tanpa ini, membatalkan sebuah lembar mematikan segar-otomatis sampai
    orangnya kebetulan berpindah halaman."""
    tutup = AKSI_JS[AKSI_JS.index("function tutupLembar()"):]
    tutup = tutup[:tutup.index("\n  }") + 4]
    assert "lupakanSentuhan" in tutup or "disentuh" in tutup, tutup


def test_pindah_menyediakan_cara_melupakan_sentuhan():
    assert "lupakanSentuhan" in PINDAH_JS


def test_kesegaran_data_terlihat_di_layar():
    """Operator yang tak tahu datanya sudah berapa lama tak diperbarui akan
    mengambil keputusan di atas angka yang sudah basi tanpa menyadarinya."""
    assert "diperbarui" in PINDAH_JS.lower()


# ─────────────────────────── P-S-08 ───────────────────────────

def test_audit_menghitung_di_sql_bukan_di_memori():
    """`len(semua id)` menarik seluruh baris tabel audit hanya untuk
    mengetahui jumlahnya — dan tabel itu yang paling cepat tumbuh."""
    sumber = (AKAR / "services/audit.py").read_text()
    assert "func.count" in sumber
    assert not re.search(r"semua = len\(", sumber)


def test_kelola_pengguna_tak_memuat_seluruh_tabel_users():
    sumber = (AKAR / "web/pengguna.py").read_text()
    assert "limit(" in sumber, "daftar orang belum dibatasi"
