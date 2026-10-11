"""`pelanggan_id` TIDAK BOLEH dipakai sebagai PENENTU "ini jasa atau bukan".

Pesan kerja 13 (11 Oktober 2026): cacat ini sudah muncul TIGA KALI di tempat
berbeda — `adalah_jasa()` (2 Oktober 2026), `nama_pihak()` (2 Oktober 2026,
bentuk kembarnya), dan `berjalan.py:1204` (11 Oktober 2026, laporan lapangan
"kepemilikan berbeda" padahal pemiliknya sama). Ketiganya sebabnya SAMA:
pelanggan BARU yang diketik bebas di Pos Timbang belum punya baris
`pelanggan`, jadi `pelanggan_id` tetap NULL sampai `find_or_create_pelanggan`
mengisinya — jauh SESUDAH tiket itu lahir. Membaca `pelanggan_id is None`
sebagai "bukan jasa" salah untuk tepat kasus itu, dan salahnya DUA ARAH:
tiket jasa nama-bebas terbaca pabrik (barang orang lain bisa tercampur
dengan gabah pabrik), dan gabah pabrik yang kebetulan tak punya pemasok
(longgar) bisa terbaca jasa.

Penentu yang BENAR adalah `timbang_link.adalah_jasa(t)` (membaca `t.jasa`
lebih dulu), bukan menyusun ulang tesnya sendiri-sendiri di tiap pemanggil —
tiga situs ditemukan satu per satu, berbulan-bulan, justru karena tak ada
penjaga TINGKAT-SUMBER yang memindai `app/` untuk pola ini. Uji FUNGSI
(`tests/test_adalah_jasa.py`) tak cukup: ia menguji `adalah_jasa()` dengan
dict buatan, tapi tak pernah tahu ada pemanggil LAIN yang membangun ulang
tesnya sendiri dengan nama kolom yang sama.
"""
from __future__ import annotations

import pathlib
import re

AKAR = pathlib.Path(__file__).resolve().parents[1] / "app"

#: (berkas relatif terhadap app/, nomor baris) yang SENGAJA memakai
#: `pelanggan_id` secara langsung — masing-masing dengan alasannya sendiri,
#: BUKAN sebagai penentu "ini jasa atau bukan":
_KECUALI: set[tuple[str, int]] = {
    # `adalah_jasa()` SENDIRI — definisi kanoniknya. `pelanggan_id is not
    # None` di sini bukan "pemanggil lain yang menyusun ulang tesnya", ia
    # KAKI KEDUA yang disengaja: tiket LAMA (sebelum kolom `jasa` ada) tetap
    # harus terbaca benar lewat migrasi 0066/0041 yang membackfill dari sini.
    ("penggilingan/gudang1/services/timbang_link.py", 323),
    # `pesanan_jasa_dari_tiket()` — dipanggil HANYA sesudah pemanggilnya
    # sendiri sudah memastikan `adalah_jasa(tiket)` true (lihat gerbangnya di
    # `purchase.create_purchase_batch_dari_timbang`). Baris ini meresolusi
    # SIAPA pelanggannya (buat baris baru bila nama diketik bebas), bukan
    # memutuskan jasa-atau-bukan — pertanyaan yang sudah terjawab sebelum
    # fungsi ini dipanggil.
    ("penggilingan/gudang1/services/purchase.py", 215),
    # `packaging._pelanggan`/`_jasa_milik_pelanggan` — subsistem KARUNG,
    # keputusan pemilik 7 Oktober 2026: karung bukan barang yang "dikembalikan"
    # per pesanan seperti komoditas lain, jadi pemiliknya `pelanggan_id`
    # LANGSUNG, tanpa `Jasa` sama sekali (lihat catatan panjang CLAUDE.md
    # "Stok Karung & Karung Jasa"). Di sini `pelanggan_id` SENDIRI parameter
    # fungsinya (bukan `t.get("pelanggan_id")` dari sebuah tiket) — ia data
    # saringan, bukan penentu jasa.
    ("penggilingan/inventory/packaging.py", 182),
    ("penggilingan/inventory/packaging.py", 189),
    # Baris lanjutan closure yang SAMA — `isinstance(pelanggan_id, list)`
    # cuma memilih bentuk `IN` vs `==`, bukan jasa-atau-bukan.
    ("penggilingan/inventory/packaging.py", 193),
}

#: `pelanggan_id` dibandingkan ke `None` dengan operator Python `is`/`is not`
#: — BEDA dari `.is_(None)` SQLAlchemy (pemeriksaan kolom di kueri, bukan
#: keputusan Python). Pola inilah yang dua kali melahirkan cacat lapangan.
_POLA_IS_NONE = re.compile(r"pelanggan_id[^\n]{0,40}\bis\s+(not\s+)?None\b")

#: Ternary satu baris yang memakai `pelanggan_id` sebagai KONDISI —
#: persis bentuk `berjalan.py:1204` sebelum pesan kerja 13:
#: `(X if t.get("pelanggan_id") else Y)`.
_POLA_TERNARY = re.compile(r"\bif\b[^\n]*\bpelanggan_id\b[^\n]*\belse\b")


def _temuan() -> list[tuple[str, int, str]]:
    hasil: list[tuple[str, int, str]] = []
    for berkas in sorted(AKAR.rglob("*.py")):
        if "__pycache__" in berkas.parts:
            continue
        rel = str(berkas.relative_to(AKAR))
        dalam_docstring = False
        for i, baris in enumerate(berkas.read_text().splitlines(), start=1):
            tanda = baris.count('"""') + baris.count("'''")
            # Toggle KASAR: baris dengan jumlah tanda kutip-tiga GANJIL
            # membuka/menutup sebuah docstring. Prosa yang mengutip pola ini
            # (seperti paragraf di atas, dan catatan panjang di
            # `timbang_link.py`) tak boleh ketahuan sebagai pelanggaran.
            mulai_dalam = dalam_docstring
            if tanda % 2 == 1:
                dalam_docstring = not dalam_docstring
            if mulai_dalam or dalam_docstring:
                continue
            tanpa_spasi = baris.strip()
            if tanpa_spasi.startswith("#"):
                continue
            if "pelanggan_id" not in baris:
                continue
            if not (_POLA_IS_NONE.search(baris) or _POLA_TERNARY.search(baris)):
                continue
            if (rel, i) in _KECUALI:
                continue
            hasil.append((rel, i, tanpa_spasi))
    return hasil


def test_pelanggan_id_tak_dipakai_sebagai_penentu_jasa():
    temuan = _temuan()
    assert not temuan, (
        "pelanggan_id dipakai sebagai PENENTU jasa-atau-bukan — salah untuk "
        "pelanggan baru yang diketik bebas (pelanggan_id-nya NULL sampai "
        "find_or_create_pelanggan mengisinya nanti). Pakai "
        "timbang_link.adalah_jasa(t). Kalau ini memang pemakaian yang sah "
        "(bukan penentu jasa), daftarkan di _KECUALI berikut alasannya:\n"
        + "\n".join(f"  {f}:{n}: {baris}" for f, n, baris in temuan)
    )


def test_penjaga_menangkap_bentuk_lama_sebelum_dibetulkan():
    """Uji mutasi — buktikan pemindainya SUNGGUH gagal pada baris yang
    melahirkan laporan lapangan, bukan cuma lolos karena polanya terlalu
    sempit (pelajaran `test_keputusan_lengkap.py`: "pola yang memindai teks
    persis berhenti bekerja tepat pada bentuk yang sedikit berbeda")."""
    contoh_lama = (
        'jasa_id=((t.get("jasa_id") or PEMILIK_BARU)\n'
        '         if t.get("pelanggan_id") else None)'
    )
    assert _POLA_TERNARY.search(contoh_lama), (
        "pemindai tak menangkap bentuk PERSIS laporan lapangan 11 Oktober "
        "2026 — polanya sendiri yang rusak")

    contoh_adalah_jasa_lama = 'return pelanggan_id is not None or jasa_id is not None'
    assert _POLA_IS_NONE.search(contoh_adalah_jasa_lama), (
        "pemindai tak menangkap bentuk `is not None` — polanya sendiri "
        "yang rusak")
