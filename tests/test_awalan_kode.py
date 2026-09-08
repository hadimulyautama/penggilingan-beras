"""Arti awalan kode — dan bahwa tak ada satu pun tempat yang masih memakai
arti lamanya.

Awalan pernah berpindah arti: `LOT-` dulu berarti pengeringan, sekarang
berarti giling; pengeringan pindah ke `PGR-`. Perpindahan seperti itu tidak
merusak apa pun secara mencolok — yang rusak adalah lapisan yang menebak
jenis barang dari huruf depan kodenya, dan ia rusak diam-diam: kodenya sah,
tujuannya salah, dan hasilnya tetap tampak masuk akal.
"""
import pathlib
import re

from app.ai.fast_route import _RULES

AKAR = pathlib.Path(__file__).resolve().parents[1]

#: Awalan → apa yang ia namai. Satu-satunya daftar; yang lain dicocokkan ke sini.
ARTI = {"GB": "pembelian gabah", "PGR": "pengeringan", "LOT": "giling",
        "TRF": "transfer PK", "PKB": "beli PK luar", "POL": "penyosohan",
        "PTS": "pindah tumpukan", "REJ": "PK ditolak", "OUT": "barang keluar",
        "PKP": "beli kemasan"}


def test_codegen_memakai_awalan_yang_diumumkan():
    """Pembuat kodenya sendiri yang jadi patokan — bukan komentar di tempat lain."""
    teks = (AKAR / "app/services/codegen.py").read_text()
    dipakai = set(re.findall(r'_next_sequence\(db, "([A-Z]+)"', teks))
    assert dipakai == set(ARTI), f"awalan tak dikenal: {dipakai ^ set(ARTI)}"


def test_jalur_cepat_tak_menyalurkan_lot_ke_pengeringan():
    """Justru inilah bug yang sudah pernah terjadi sekali: `LOT-` jatuh ke
    pengeringan padahal ia kode giling. Yang menahannya cuma satu baris regex,
    jadi baris itu diuji."""
    tujuan = {}
    for pola, domain in _RULES:
        for awalan in ARTI:
            if pola.search(f"{awalan}-20260908-01") and awalan not in tujuan:
                tujuan[awalan] = domain
    assert tujuan.get("LOT") == "milling", "LOT- adalah kode giling"
    assert tujuan.get("PGR") == "pengeringan"
    assert tujuan.get("POL") == "penyosohan"
    assert tujuan.get("TRF") == "transfer_pk"


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
