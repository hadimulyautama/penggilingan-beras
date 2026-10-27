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
import ast
import re

AKAR = pathlib.Path(__file__).resolve().parents[1] / "app"

#: (berkas relatif terhadap app/, nomor baris) yang SENGAJA memakai
#: `pelanggan_id` secara langsung — masing-masing dengan alasannya sendiri,
#: BUKAN sebagai penentu "ini jasa atau bukan":
_KECUALI = {
    # Bounds-checking two account/contact identifiers, not classifying a
    # weighbridge ticket as jasa. The broad regex also sees kledo_id's None
    # check on this line; keep the exception exact and leave ticket guards intact.
    ("services/portal_accounts.py", "contact",
     'if not 0 < pelanggan_id < 2**31 or (kledo_id is not None and not 0 < kledo_id < 2**63):'),
    # Definisi kanonik: kaki kompatibilitas tiket lama, bukan pemanggil.
    ("penggilingan/gudang1/services/timbang_link.py", "adalah_jasa",
     'return bool(t.get("jasa")) or t.get("pelanggan_id") is not None \\'),
    # Resolusi identitas setelah tiket dipastikan jasa oleh pemanggilnya.
    ("penggilingan/gudang1/services/purchase.py", "pesanan_jasa_dari_tiket", 'if pelanggan_id is None:'),
    # Karung dimiliki pelanggan langsung, bukan memakai identitas tiket.
    ("penggilingan/inventory/packaging.py", "_pelanggan", 'if pelanggan_id is None:'),
    ("penggilingan/inventory/packaging.py", "_jasa_milik_pelanggan", 'if pelanggan_id is None:'),
    ("penggilingan/inventory/packaging.py", "_jasa_milik_pelanggan",
     'if isinstance(pelanggan_id, list) else Jasa.pelanggan_id == pelanggan_id)'),
    # Pengiriman membandingkan pembeli tiket dengan pembeli transaksi.
    ("services/barang_keluar.py", "_armada_dari_tiket",
     'if pelanggan_id is not None and tiket["pelanggan_id"] is not None and tiket["pelanggan_id"] != pelanggan_id:'),
    # Penulisan identitas tiket satu pelanggan setelah tiket bebas/valid.
    # Kiriman gabungan tidak diwakili salah satu pelanggan (parameter None).
    ("services/barang_keluar.py", "_armada_dari_tiket", 'if pelanggan_id is not None:'),
    ("web/internal.py", "_cocokkan_pengiriman_tiket",
     'if tiket["pelanggan_id"] is not None and rec.pelanggan_id is not None:'),
    # Detail menerima saringan pelanggan yang sudah disahkan rutenya;
    # bukan menetapkan kepemilikan dari sebuah tiket yang belum lengkap.
    ("web/layar_produk.py", "_detail_produk",
     'halaman = "/stok-produk-jasa" if pelanggan_id is not None else "/stok-produk"'),
    ("web/layar_produk.py", "_detail_produk",
     '{"pelanggan_id": pelanggan_id} if pelanggan_id is not None else {})})'),
    ("web/layar_produk.py", "_detail_produk",
     'owners = list(jasa_ids) if pelanggan_id is not None else [None]'),
    ("web/layar_produk.py", "_detail_produk",
     'layar="stok_produk_jasa" if pelanggan_id is not None else "stok_produk",'),
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
        fungsi = [n for n in ast.walk(ast.parse(berkas.read_text()))
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
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
            pemilik = [f for f in fungsi if f.lineno <= i <= f.end_lineno]
            nama_fungsi = max(pemilik, key=lambda f: f.lineno).name if pemilik else ""
            if (rel, nama_fungsi, tanpa_spasi) in _KECUALI:
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


def test_pengecualian_tetap_tepat_setelah_nomor_baris_bergeser(monkeypatch, tmp_path):
    f = tmp_path / "penggilingan/gudang1/services/purchase.py"
    f.parent.mkdir(parents=True)
    f.write_text("\n" * 30 + '''def pesanan_jasa_dari_tiket():
    if pelanggan_id is None:
        pass
    jasa = tiket.get("jasa_id") if tiket.get("pelanggan_id") else None
''')
    monkeypatch.setattr(__import__(__name__, fromlist=["AKAR"]), "AKAR", tmp_path)
    temuan = _temuan()
    assert len(temuan) == 1
    assert 'if tiket.get("pelanggan_id")' in temuan[0][2]


def test_pengecualian_armada_tidak_menyembunyikan_penentu_jasa_baru(monkeypatch,tmp_path):
    path=tmp_path/'services/barang_keluar.py';path.parent.mkdir(parents=True)
    path.write_text('''async def _armada_dari_tiket():
    if pelanggan_id is not None and tiket["pelanggan_id"] is not None and tiket["pelanggan_id"] != pelanggan_id:
        raise ValueError()
    if pelanggan_id is not None:
        pass
    jasa = tiket.get("jasa_id") if tiket.get("pelanggan_id") else None
''')
    monkeypatch.setattr(__import__(__name__,fromlist=['AKAR']),'AKAR',tmp_path)
    temuan=_temuan()
    assert len(temuan)==1 and 'if tiket.get("pelanggan_id") else None' in temuan[0][2]
