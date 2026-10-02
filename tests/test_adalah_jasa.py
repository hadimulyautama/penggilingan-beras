"""`adalah_jasa()` / `nama_pihak()` — penanda tiket jasa, dan dua bentuknya.

Cacat lapangan 2 Oktober 2026 (laporan pemilik langsung dari layar Stok): lot
PK titipan pelanggan terbaca sebagai pembelian pabrik, dan pemasok PALSU
bernama pelanggan ("MARNOOO") ikut tercatat — persis yang spek larang keras.

Akarnya: sampai migrasi 0066/0041, "ini jasa?" DITURUNKAN dari
`pelanggan_id IS NOT NULL`. Tetapi borang jasa SENGAJA punya pintu ketik-bebas
untuk pelanggan baru yang belum sampai ke cermin Kledo (`_wajib_pihak` di repo
`timbangan`: "boleh dari daftar ATAU diketik bebas"), dan saat nama diketik
bebas, `pelanggan_id` yang terkirim TETAP KOSONG — `_pasang_pihak(trx, arah,
pihak_id=None, jasa=True)` mengosongkan KEDUA kolom FK. Baris tiket
"jasa-pelanggan-baru" dan "pembelian-pemasok-baru" jadi IDENTIK bentuknya; tak
ada yang membedakan keduanya tanpa penanda tersendiri.

Diuji di SINI atas DICT TELANJANG — bukan lewat basis data — supaya ketiga
bentuk tiket (lama/baru/biasa) bisa dibandingkan berdampingan tanpa
menyiapkan satu pun baris, dan supaya kasus tepinya (kolom `jasa` belum ada
sama sekali di dict, tiket pra-migrasi) ikut terbukti.
"""
from __future__ import annotations

from app.penggilingan.gudang1.services.timbang_link import adalah_jasa, nama_pihak


def test_pelanggan_lama_dari_dropdown_tetap_jasa():
    """Bentuk yang SUDAH BENAR sebelum migrasi — tak boleh berubah."""
    t = {"jasa": True, "pelanggan_id": 7, "nama_pelanggan": "Bu Sri",
         "jasa_id": None, "jasa_kode": None}
    assert adalah_jasa(t)
    assert nama_pihak(t) == "JASA · Bu Sri"


def test_pelanggan_baru_diketik_bebas_tetap_terdeteksi_jasa():
    """⭐ INTI CACATNYA. `pelanggan_id` NULL, hanya `jasa` dan `pihak_nama`.

    Ini persis bentuk tiket "Marnooo" di lapangan: pelanggan belum ada di
    cermin Kledo, diketik bebas, `pelanggan_id` tetap kosong sampai produksi
    membuatnya. SEBELUM migrasi ini, `adalah_jasa` menjawab False di sini —
    dan itulah yang membuat pemasok palsu tercipta.
    """
    t = {"jasa": True, "pelanggan_id": None, "nama_pelanggan": None,
         "pihak_nama": "Marnooo", "jasa_id": None, "jasa_kode": None,
         "nama_supplier": None}
    assert adalah_jasa(t), "pelanggan baru diketik bebas tak terdeteksi jasa"
    # Dan kartunya menyebut JASA — bukan nama telanjang yang terbaca seperti
    # pemasok biasa.
    assert nama_pihak(t) == "JASA · Marnooo"


def test_pembelian_biasa_pemasok_diketik_bebas_tetap_bukan_jasa():
    """Sisi SEBALIKNYA, sama pentingnya: pembelian biasa tak boleh ikut
    tertandai jasa hanya karena pemasoknya diketik bebas.

    Bentuknya SENGAJA dibuat semirip mungkin dengan kasus di atas — hanya
    `jasa` yang beda — supaya jelas satu-satunya pembeda memang kolom itu,
    bukan ada-tidaknya `pihak_nama`.
    """
    t = {"jasa": False, "pelanggan_id": None, "nama_pelanggan": None,
         "pihak_nama": "CV Makmur", "jasa_id": None, "jasa_kode": None,
         "nama_supplier": None}
    assert not adalah_jasa(t)
    assert nama_pihak(t) == "CV Makmur"


def test_dict_tanpa_kolom_jasa_sama_sekali_tetap_terjaga_oleh_kaki_kedua():
    """Tiket PRA-MIGRASI, dibaca lewat jalur yang entah kenapa belum memilih
    kolom `jasa` sama sekali (`.get("jasa")` → `None`, bukan `False`).

    `pelanggan_id`/`jasa_id` tetap jadi kaki kedua untuk kasus ini — bukan
    untuk tiket baru (yang `jasa`-nya selalu terisi benar), melainkan supaya
    jalur baca yang lebih tua tak tiba-tiba berhenti mendeteksi jasa.
    """
    assert adalah_jasa({"pelanggan_id": 3})
    assert adalah_jasa({"jasa_id": 9})
    assert not adalah_jasa({})
    assert not adalah_jasa({"pelanggan_id": None, "jasa_id": None, "jasa": None})


def test_pesanan_disebut_di_kartu_bila_sudah_ditunjuk():
    """"JAS-2610-007 Pak Budi" — bukan sekadar nama. Pak Budi bisa punya dua
    pesanan berjalan; yang menentukan barang ini masuk ke mana adalah
    pesanannya, bukan namanya."""
    t = {"jasa": True, "pelanggan_id": 1, "nama_pelanggan": "Pak Budi",
         "jasa_id": 7, "jasa_kode": "JAS-2610-007"}
    assert nama_pihak(t) == "JASA · JAS-2610-007 Pak Budi"
