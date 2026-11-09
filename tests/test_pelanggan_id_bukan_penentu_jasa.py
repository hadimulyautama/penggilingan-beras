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
    # Saldo rekening karung dan metadata kontak; bukan penentu jasa tiket.
    ("penggilingan/inventory/packaging.py","hitung_stok_kemasan",
     "rekening=set(pelanggan_id) if isinstance(pelanggan_id,list) else {pelanggan_id}"),
    ("penggilingan/inventory/packaging.py","stok_kemasan_rinci",
     '"pemilik_id": pelanggan_id if not isinstance(pelanggan_id,list) else None,'),
    # Saringan pemilik yang sudah ditentukan sebagai jasa oleh argumen terpisah.
    ("services/koreksi_bahan_berjalan.py", "sumber_bebas_g1", 'if pelanggan_id is not None:'),
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
    ("web/internal.py", "periksa",
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


def _menyebut_pelanggan(expr):
    return any((isinstance(a, ast.Name) and a.id == 'pelanggan_id')
               or (isinstance(a, ast.Attribute) and a.attr == 'pelanggan_id')
               or (isinstance(a, ast.Constant) and a.value == 'pelanggan_id')
               for a in ast.walk(expr))


def _temuan() -> list[tuple[str, int, str]]:
    hasil: list[tuple[str, int, str]] = []
    for berkas in sorted(AKAR.rglob("*.py")):
        if "__pycache__" in berkas.parts:
            continue
        rel = str(berkas.relative_to(AKAR))
        pohon = ast.parse(berkas.read_text())
        fungsi = [n for n in ast.walk(pohon)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        baris_ternary = {i for n in ast.walk(pohon) if isinstance(n, ast.IfExp)
                         and _menyebut_pelanggan(n.test)
                         for i in range(n.test.lineno, n.test.end_lineno + 1)}
        baris_none = set()
        for n in ast.walk(pohon):
            if not isinstance(n, ast.Compare):
                continue
            for kiri, op, kanan in zip([n.left, *n.comparators], n.ops, n.comparators):
                kosong = lambda a:isinstance(a, ast.Constant) and a.value is None
                if isinstance(op, (ast.Is, ast.IsNot)) and ((kosong(kiri) and _menyebut_pelanggan(kanan)) or (kosong(kanan) and _menyebut_pelanggan(kiri))):
                    baris_none.update(range(n.lineno, n.end_lineno + 1))
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
            # Periksa KONDISI ternary, bukan nama pelanggan di bagian lain
            # baris panjang yang kebetulan mempunyai ternary untuk berat.
            if i not in baris_none and i not in baris_ternary:
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


def test_kondisi_ternary_diperiksa_tanpa_menuduh_kolom_di_sebelahnya(monkeypatch, tmp_path):
    monkeypatch.setitem(globals(), 'AKAR', tmp_path)
    f = tmp_path / 'contoh.py'
    f.write_text('def baca(r):\n return dict(pelanggan_id=r.pelanggan_id, kg=1 if r.berat is not None else 0)\n')
    assert _temuan() == []
    for kondisi in ('r.pelanggan_id', 'r.get("pelanggan_id")', 'pelanggan_id'):
        f.write_text(f'def baca(r):\n return "jasa" if {kondisi} else "pabrik"\n')
        assert len(_temuan()) == 1


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
