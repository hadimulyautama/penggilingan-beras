"""Arti awalan kode — dan bahwa tak ada satu pun tempat yang masih memakai
arti lamanya.

Awalan pernah berpindah arti: `LOT-` dulu berarti pengeringan, sekarang
berarti giling; pengeringan pindah ke `PGR-`. Perpindahan seperti itu tidak
merusak apa pun secara mencolok — yang rusak adalah lapisan yang menebak
jenis barang dari huruf depan kodenya, dan ia rusak diam-diam: kodenya sah,
tujuannya salah, dan hasilnya tetap tampak masuk akal.

Penebak terbesarnya, jalur cepat router bot (`app.ai.fast_route`), ikut
dibubarkan bersama bot produksi. Yang tersisa dijaga di sini.
"""
import pathlib
import re

AKAR = pathlib.Path(__file__).resolve().parents[1]

#: Awalan → apa yang ia namai. Satu-satunya daftar; yang lain dicocokkan ke sini.
ARTI = {"GB": "pembelian gabah", "PGR": "pengeringan", "LOT": "giling",
        "TRF": "transfer PK", "PKB": "beli PK luar", "POL": "penyosohan",
        "PTS": "pindah tumpukan", "REJ": "PK ditolak", "OUT": "barang keluar",
        "PKP": "beli kemasan", "JAS": "pesanan jasa",
        "BKS": "pindah broken ke silo",
        "GKR": "gabah kering dikemas", "GKS": "bongkar gabah kering ke silo",
        "BRS": "pindah beras ke silo"}


def test_codegen_memakai_awalan_yang_diumumkan():
    """Pembuat kodenya sendiri yang jadi patokan — bukan komentar di tempat lain.

    DUA bentuk pemanggilan dicari, bukan satu. `_next_sequence` merakit
    `PREFIX-YYYYMMDD-NN` untuk yang harian; `JAS` memakai penghitung yang sama
    lewat `_ambil_urut` karena bentuknya bulanan (`JAS-YYMM-NNN`) — lihat
    `next_jasa_code`. Pola yang hanya mengenali bentuk pertama akan membiarkan
    awalan bulanan berikutnya lahir tanpa pernah diumumkan di sini, dan daftar
    yang bolong lebih buruk daripada tak ada daftar: yang membacanya percaya ia
    lengkap.
    """
    teks = (AKAR / "app/services/codegen.py").read_text()
    dipakai = set(re.findall(r'_(?:next_sequence|ambil_urut)\(db, "([A-Z]+)"', teks))
    assert dipakai == set(ARTI), f"awalan tak dikenal: {dipakai ^ set(ARTI)}"


def test_tak_ada_yang_menyalurkan_pekerjaan_dari_huruf_depan_kode():
    """Menebak jenis pekerjaan dari awalan kode sudah sekali salah dan akan
    salah lagi tiap kali sebuah awalan berpindah arti. `report.py` sudah
    memilih jalan yang benar — mencari DI TABELNYA — dan tes ini menjaga agar
    tak ada yang kembali menebak."""
    teks = (AKAR / "app/services/report.py").read_text()
    assert "Dicari DI TABELNYA, bukan ditebak dari awalan kode." in teks
    assert "DryingLot.kode_lot == kode" in teks

    # Dan tak ada regex awalan→domain yang hidup lagi di mana pun.
    salah = []
    for berkas in (AKAR / "app").rglob("*.py"):
        teks = berkas.read_text()
        for m in re.finditer(r'r"\\\\b\(?(?:LOT|PGR|MIL)[-|]', teks):
            salah.append(f"{berkas.relative_to(AKAR)}: {teks[m.start():m.start()+40]}")
    assert not salah, "awalan dipakai menebak domain lagi:\n  " + "\n  ".join(salah)


def test_tak_ada_contoh_yang_mengajarkan_awalan_lama():
    """Contoh di pesan galat dan di keterangan alat AI ikut MENGAJARI orang
    (dan agennya) awalan mana untuk apa. Contoh yang basi bukan sekadar
    tulisan salah — ia menyuruh orang mengetik kode yang tak pernah ada."""
    salah = []
    for berkas in (AKAR / "app").rglob("*.py"):
        for n, baris in enumerate(berkas.read_text().splitlines(), 1):
            if "MIL-" not in baris:
                continue
            # Yang boleh menyebut MIL-: yang justru menjelaskan bahwa ia lama.
            if any(k in baris for k in ("dulu MIL", "Dulu MIL", "MIL- tetap dikenali",
                                        "MIL|", "(LOT|MIL)", "# MIL-")):
                continue
            salah.append(f"{berkas.relative_to(AKAR)}:{n} {baris.strip()[:70]}")
    assert not salah, "awalan lama masih diajarkan:\n  " + "\n  ".join(salah)
