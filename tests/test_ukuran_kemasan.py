"""Ukuran karung yang DITAWARKAN wajib juga DITERIMA.

Ada dua daftar ukuran, dan keduanya harus sepakat:

  · `packaging._BERAS_SIZES` — yang menawarkan pilihannya di borang, lewat
    `aksi_inventory.kombinasi_kemasan`;
  · baris `package_sizes` yang disemai `seed_master` — yang MENERIMA-nya saat
    disimpan, lewat `find_or_create_sku` → `get_size`.

Ukuran yang ada di daftar pertama tetapi tidak di kedua berakhir sebagai
pilihan yang bisa ditekan lalu ditolak: "Ukuran 20 kg tidak terdaftar" —
sesudah operator memilih lotnya, memilih merknya, dan mengetik jumlah
karungnya. Ia tak melahirkan galat di mana pun sampai ada yang benar-benar
memakainya, dan yang memakainya adalah operator sambil berdiri di mesin.

Arah sebaliknya tidak dijaga: ukuran yang tersemai tetapi tak ditawarkan cuma
baris master yang menganggur, dan itu tak merugikan siapa pun.

Lahir 28 September 2026, saat pemilik menyebut "ukuran kemasan ada yang 20 dan
40 kg" — dua angka, dan keduanya harus ditambahkan di DUA tempat.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re

AKAR = pathlib.Path(__file__).resolve().parents[1]


def _ukuran_tersemai() -> set[int]:
    """Ukuran yang ditulis `seed_master`, dibaca dari SUMBERNYA.

    Dibaca dengan AST, bukan dijalankan: memanggil `seed_master` menuntut basis
    data, dan pagar yang menuntut basis data akan dilewati di suite sqlite —
    yaitu suite yang paling sering dijalankan orang.
    """
    from app.services import seed

    pohon = ast.parse(inspect.getsource(seed.seed_master))
    for simpul in ast.walk(pohon):
        # `for ukuran in (5, 10, 20, ...):`
        if (isinstance(simpul, ast.For)
                and isinstance(simpul.target, ast.Name)
                and simpul.target.id == "ukuran"
                and isinstance(simpul.iter, ast.Tuple)):
            return {int(x.value) for x in simpul.iter.elts}
    raise AssertionError(
        "Perulangan penyemai ukuran tak ditemukan lagi di `seed_master` — "
        "pagar ini membaca sumbernya, jadi bentuknya yang berubah membuatnya "
        "buta. Sesuaikan pembacanya, jangan hapus pagarnya.")


def test_tiap_ukuran_yang_ditawarkan_juga_disemai():
    from app.penggilingan.inventory.packaging import _BERAS_SIZES

    kurang = sorted(_BERAS_SIZES - _ukuran_tersemai())
    assert not kurang, (
        "ukuran ditawarkan di borang tetapi tak pernah disemai — akan ditolak "
        f"saat disimpan: {kurang} kg")


def test_ukuran_tetap_per_kategori_juga_disemai():
    """Kategori selain beras memakai ukuran TETAP di `KEMASAN_VALID` (broken 50
    & 25, menir 50, reject 50, PK 50) — angka yang ditulis di tempat lain lagi,
    dan karenanya bisa melenceng dengan caranya sendiri."""
    from app.penggilingan.inventory.packaging import KEMASAN_VALID

    tetap = {u for aturan in KEMASAN_VALID.values() for _, u in aturan
             if u is not None}
    kurang = sorted(tetap - _ukuran_tersemai())
    assert not kurang, f"ukuran tetap tak disemai: {kurang} kg"


def test_dua_puluh_dan_empat_puluh_kilo_bisa_dipakai():
    """Keterangan pemilik 28 September 2026: "ukuran kemasan ada yang 20 dan 40
    kg". Disebut dengan angkanya supaya hilangnya terbaca sebagai hilang, bukan
    sebagai daftar yang kebetulan lebih pendek."""
    from app.penggilingan.inventory.packaging import _BERAS_SIZES, _validate_kemasan

    for u in (20, 40):
        assert u in _BERAS_SIZES, f"{u} kg hilang dari ukuran beras"
        assert u in _ukuran_tersemai(), f"{u} kg tak disemai ke master"
        # Dan aturan kemasannya menerimanya, untuk kedua jenis karung beras.
        for bahan in ("biasa", "laminasi"):
            _validate_kemasan("beras_putih", bahan, u)
            _validate_kemasan("beras_b", bahan, u)


def test_borang_menawarkan_ukuran_barunya():
    """Sampai ke DAFTAR YANG DILIHAT ORANG, bukan berhenti di tetapannya."""
    from app.web.aksi_inventory import kombinasi_kemasan

    ukuran = {u for kat, _, u in kombinasi_kemasan() if kat == "beras_putih"}
    assert {20, 40} <= ukuran, f"borang tak menawarkan 20/40 kg: {sorted(ukuran)}"


def test_ukuran_tak_ditulis_ulang_di_layar():
    """Angka ukuran tak boleh diketik lagi di templat atau katalog aksi.

    Daftar keempat yang lahir di layar akan menawarkan 25 & 50 saja selamanya,
    dan tak seorang pun tahu sebabnya — sebab tempatnya bukan tempat yang
    dicari orang saat menambah ukuran.
    """
    salah = []
    for berkas in [AKAR / "app/web/api.py", AKAR / "app/web/aksi_inventory.py"]:
        for no, baris in enumerate(berkas.read_text().splitlines(), 1):
            if baris.lstrip().startswith("#"):
                continue
            # Deret angka ukuran yang diketik langsung, mis. [5, 10, 25, 50].
            if re.search(r"[\[\{\(]\s*5\s*,\s*10\s*,\s*\d+\s*,", baris):
                salah.append(f"{berkas.name}:{no}")
    assert not salah, (
        "daftar ukuran diketik ulang di layar; yang berwenang "
        "`packaging._BERAS_SIZES`: " + ", ".join(salah))


def _merk_tersemai() -> dict[str, str]:
    """Merk yang ditulis `seed_master`, dibaca dari SUMBERNYA — alasannya sama
    dengan `_ukuran_tersemai`: pagar yang menuntut basis data akan dilewati di
    suite yang paling sering dijalankan orang."""
    from app.services import seed

    pohon = ast.parse(inspect.getsource(seed.seed_master))
    for simpul in ast.walk(pohon):
        if (isinstance(simpul, ast.Assign)
                and isinstance(simpul.targets[0], ast.Name)
                and simpul.targets[0].id == "_BRANDS"):
            return {t.elts[0].value: t.elts[1].value for t in simpul.value.elts}
    raise AssertionError(
        "`_BRANDS` tak ditemukan lagi di `seed_master` — pagar ini membaca "
        "sumbernya, jadi bentuknya yang berubah membuatnya buta. Sesuaikan "
        "pembacanya, jangan hapus pagarnya.")


def test_merk_baru_terdaftar_dan_bertipe_benar():
    """Keterangan pemilik 28 September 2026: "ada merk baru, FJ dan Gunung Mas".

    `tipe` bukan sekadar catatan: `/actions/merk` mengurutkan `tipe` MENURUN
    lalu nama, jadi merk bertipe `polos` selalu jatuh ke bawah daftar. Merk
    sendiri yang salah tipe akan tersembunyi di ujung, di bawah "Polos" — dan
    operator yang tak menemukannya akan menyimpulkan merknya belum didaftarkan,
    lalu memakai merk lain.
    """
    merk = _merk_tersemai()
    for nama in ("FJ", "Gunung Mas"):
        assert nama in merk, f"merk '{nama}' belum terdaftar"
        assert merk[nama] == "house", (
            f"merk '{nama}' bertipe '{merk[nama]}' — ia akan tenggelam di "
            "bawah 'Polos' di borang")


def test_nama_merk_tak_melebihi_kolomnya():
    """`brands.nama` 50 huruf. Nama yang lebih panjang tidak ditolak borang
    mana pun — ia gagal di basis data, saat penyemaian, saat aplikasi menyala:
    seed dibungkus `try` di `main.py`, jadi kegagalannya cuma satu baris log
    dan seluruh merk sesudahnya ikut tak tersemai."""
    panjang = [n for n in _merk_tersemai() if len(n) > 50]
    assert not panjang, f"nama merk melebihi 50 huruf: {panjang}"


def test_bekatul_dikemas_40_dan_20_kg():
    """Jawaban pemilik 30 September 2026 atas laporan operator ("ukuran karung
    bekatul hanya ada 40 kg saja, tidak ada 20 kg"): di lapangan dipakai
    KEDUANYA.

    Laporannya bisa dibaca dua arah — "app kurang 20" atau "benar, memang
    cuma 40" — dan keduanya menghasilkan pekerjaan yang berlawanan. Yang
    memutuskan pemilik, bukan tebakan.
    """
    from app.penggilingan.inventory.packaging import KEMASAN_VALID

    ukuran = {u for m, u in KEMASAN_VALID["bekatul"]}
    assert ukuran == {40, 20}, ukuran
    assert {m for m, _ in KEMASAN_VALID["bekatul"]} == {"bekas"}, \
        "bekatul dikemas karung BEKAS — bukan karung baru"


def test_packing_otomatis_hasil_samping_menyisakan_curah():
    from app.services.stok import _packing_otomatis

    assert _packing_otomatis("bekatul", 167) == (40, 4, 160, 7)
    for jenis in ("reject", "menir", "broken"):
        assert _packing_otomatis(jenis, 167) == (50, 3, 150, 17)
