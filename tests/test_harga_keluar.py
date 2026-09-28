"""Harga keluar dari Pos Produksi — SELURUHNYA.

Keputusan pemilik 28 September 2026 membuang verifikasi/penetapan harga (gabah,
PK luar, hasil samping) dan kedua HPP, berikut tarif biayanya — tetapi masih
menyisakan empat aksi TRANSAKSI yang boleh menyebut rupiah.

⚠ SISA ITU DICABUT 29 September 2026. Pemilik, saat PK dikembalikan ke rantai
barang keluar: "istilah dijual kan harus tau harganya. sedangkan sistem
produksi tidak boleh ada sangkut paut dengan harga. termasuk beras yang keluar.
tidak boleh melampirkan harga. semua yang berhubungan dengan harga tolong
dihapus."

Jadi aturannya kini MUTLAK, dan pagar ini ikut berubah bentuk: dulu ia
menjaga daftar pengecualian, sekarang ia menjaga bahwa TAK ADA pengecualian.
Yang berpindah di Pos Produksi BARANG — berapa kilogram, berapa karung, dari
mana ke mana. Berapa rupiahnya dicatat di tempat uang dicatat.

Yang paling mudah kembali diam-diam: satu medan harga yang "cuma opsional",
diselipkan ke borang baru karena terasa berguna. Karena itu pagar ini membaca
BENTUK BORANGNYA, bukan daftar nama aksi.
"""
from __future__ import annotations

import pathlib
import re

import pytest

AKAR = pathlib.Path(__file__).resolve().parents[1]

#: KOSONG, dan kekosongannya yang dijaga. Ditulis sebagai himpunan — bukan
#: dihapus — supaya pagar di bawah tetap berbentuk sama bila suatu hari ada
#: pengecualian yang sungguh diputuskan pemilik, dan supaya penambahan nama ke
#: sini terbaca sebagai perubahan aturan, bukan sebagai perbaikan uji.
BOLEH_BERHARGA: set[str] = set()


def _spesifikasi() -> dict[str, list[str]]:
    """{id aksi: nama medannya} dari seluruh katalog.

    Dibaca PER BERKAS — menggabungkan sumbernya lebih dulu membuat spesifikasi
    terakhir satu berkas menyerap medan spesifikasi pertama berkas berikutnya,
    dan pagar yang salah menuduh lebih buruk daripada tak ada pagar.

    `_bidang_pengiriman()` dibentangkan: medannya tak tertulis di tempat
    spesifikasinya, jadi tanpa itu pagar ini buta terhadap seluruh borang
    pengiriman — termasuk bila suatu hari harga diselipkan kembali ke sana.
    """
    keluar: dict[str, list[str]] = {}
    for berkas in ("app/web/api.py", "app/web/aksi_inventory.py",
                   "app/web/aksi_undo.py"):
        teks = (AKAR / berkas).read_text()
        kirim: list[str] = []
        if "def _bidang_pengiriman(" in teks:
            i = teks.index("def _bidang_pengiriman(")
            kirim = re.findall(r'"name": "([a-z0-9_]+)"',
                               teks[i:teks.index("\n\n\n", i)])
        for m in re.finditer(r'\{"id": "([a-z0-9_]+)", "label": "', teks):
            i = teks.find('"fields"', m.end())
            if i < 0 or i - m.end() > 2500:
                continue
            n = teks.find('{"id": "', m.end())
            j = n if n > 0 else len(teks)
            blok = teks[i:j]
            medan = re.findall(r'"name": "([a-z0-9_]+)"', blok)
            if "_bidang_pengiriman()" in blok:
                medan += kirim
            keluar[m.group(1)] = medan
    return keluar


def test_tak_ada_borang_yang_meminta_harga_selain_transaksi():
    """Pagar utamanya: Pos Produksi tak lagi MENANYAKAN harga, kecuali pada
    empat aksi yang mencatat uang benar-benar berpindah.

    Diuji pada BENTUK BORANGNYA, bukan pada nama fungsinya: yang sampai ke
    orang adalah medan yang ia lihat di layar, dan aksi baru yang diam-diam
    membawa medan harga akan lolos dari pagar yang cuma membaca daftar nama.
    """
    salah = []
    for aksi, medan in _spesifikasi().items():
        if aksi in BOLEH_BERHARGA:
            continue
        for m in medan:
            if "harga" in m or m in ("nilai", "total_biaya", "hpp"):
                salah.append(f"{aksi}.{m}")
    assert not salah, ("borang ini meminta harga padahal bukan transaksi: "
                       + ", ".join(salah))


def test_tak_satu_pun_borang_menyebut_rupiah():
    """Kebalikan dari pagar yang dulu berdiri di sini.

    Sampai 29 September 2026 uji ini bernama "pembelian karung TETAP punya
    medan harganya", dan ia menjaga agar "buang harga" tak dikerjakan dengan
    menyapu semuanya. Pemilik kemudian memutuskan justru menyapu semuanya —
    termasuk pembelian karung, medan harga terakhir yang tersisa.

    Yang dicatat pembelian karung kini berapa LEMBAR masuk gudang. Itu yang
    dipakai memutuskan kapan membeli lagi, dan itu tak butuh rupiah.
    """
    berharga = {aksi: [m for m in medan
                       if "harga" in m or m in ("nilai", "total_biaya", "hpp")]
                for aksi, medan in _spesifikasi().items()}
    salah = {a: m for a, m in berharga.items() if m}
    assert not salah, f"borang ini masih menyebut rupiah: {salah}"


def test_borang_pengiriman_tak_menanyakan_rupiah():
    """Disebut sendiri, sebab `_bidang_pengiriman()` dipakai berulang: satu
    medan harga yang diselipkan ke sana akan muncul di SETIAP borang keluar
    sekaligus, dan pagar per-aksi di atas menyebutkannya satu per satu — daftar
    yang panjang lebih mudah dibaca sebagai "memang begitu"."""
    from app.web.aksi_inventory import _bidang_pengiriman

    nama = {f["name"] for f in _bidang_pengiriman()}
    assert not [n for n in nama if "harga" in n], (
        "borang pengiriman menanyakan harga — uang urusan keuangan, "
        f"bukan Pos Produksi: {sorted(nama)}")


def test_ketiga_aksi_harga_benar_benar_hilang():
    """Disebut satu per satu, bukan disandarkan pada pagar di atas: pagar itu
    berangkat dari katalog, dan aksi yang rutenya tertinggal tanpa spesifikasi
    tetap bisa dipanggil lewat alamatnya."""
    api = (AKAR / "app/web/api.py").read_text()
    inv = (AKAR / "app/web/aksi_inventory.py").read_text()
    for rute in ("/actions/verify-gabah", "/actions/harga-pk-luar",
                 "/actions/harga-byproduct"):
        assert f'"{rute}"' not in api + inv, f"rute {rute} masih hidup"


def test_kedua_hpp_tak_ada_lagi():
    """Keduanya mati dengan sendirinya begitu harga pergi — HPP PK butuh harga
    gabah, HPP beras butuh HPP PK dan harga hasil samping. Yang dibiarkan hidup
    akan menjawab "menunggu data lengkap" selamanya, dan blok yang selalu
    kosong mengajari orang berhenti membaca dasbornya."""
    assert not (AKAR / "app/services/costing.py").exists(), "costing.py kembali"
    from app.penggilingan.inventory import finished_goods as bj
    from app.services import analytics, transfer

    for modul, nama in ((transfer, "hpp_per_kg_pk"), (bj, "hitung_hpp_beras"),
                        (bj, "laporan_hpp_beras"), (bj, "biaya_penyosohan_proses"),
                        (bj, "set_harga_byproduct"), (bj, "harga_byproduct"),
                        (analytics, "hpp_trend"), (analytics, "biaya_produksi_detail"),
                        (analytics, "simulasi_hpp"), (analytics, "biaya_proses_ringkas")):
        assert not hasattr(modul, nama), f"{nama} kembali hidup"


def test_tarif_biaya_tak_ada_lagi_di_setelan():
    """Tarif yang dibiarkan berdiri tanpa pembaca akan dipelihara orang
    berikutnya — dinaikkan tiap tahun, dibahas di rapat — atas hitungan yang
    tak pernah dijalankan."""
    from app.config import settings

    for tarif in ("biaya_bongkar_per_kg_gabah", "biaya_operator_per_proses",
                  "biaya_pengeringan_basah_per_kg", "rubber_roll_harga_per_set",
                  "biaya_penyosohan_per_kg_pk", "biaya_marketing_per_kg_beras"):
        assert not hasattr(settings, tarif), f"{tarif} masih ada"


def test_tak_ada_layar_yang_mencetak_rupiah_lagi():
    """Pagar di atas membaca BORANG; yang ini membaca yang DICETAK.

    Borang yang bersih tak menolong bila laporannya masih mencetak "HPP
    1.234/kg" dari baris lama. Sejak harga dicabut, kolom-kolom itu tak pernah
    diisi lagi — jadi yang tercetak adalah sisa sejarah yang ditampilkan seolah
    masih berlaku, bentuk kebohongan yang paling sulit ketahuan.

    Dicari pada pemformat rupiahnya, bukan pada kata "harga": yang mencetak
    angka uang selalu lewat salah satu dari keduanya.
    """
    import re

    salah = []
    for berkas in sorted((AKAR / "app").rglob("*.py")):
        teks = berkas.read_text()
        for no, baris in enumerate(teks.splitlines(), 1):
            telanjang = baris.split("#")[0]
            if re.search(r"(_rp|_rupiah)\(\s*float\(\s*\w+\.(hpp_per_kg|harga_per_kg|"
                         r"total_biaya|total_harga|harga_per_lembar)", telanjang):
                salah.append(f"{berkas.relative_to(AKAR)}:{no}")
    assert not salah, ("layar ini masih mencetak angka uang dari kolom lama: "
                       + ", ".join(salah))


def test_tak_ada_layanan_yang_menulis_angka_uang_lagi():
    """Dan tak ada yang MENGISI kolomnya.

    Kolomnya belum dibuang — baris lama memuatnya, dan menghapus kolom berarti
    menghapus sejarah. Yang wajib berhenti adalah PENULISANNYA: kolom mati yang
    diam-diam diisi lagi akan menghidupkan kembali seluruh persoalan tanpa satu
    pun borang yang terlihat berubah.
    """
    import re

    salah = []
    for berkas in sorted((AKAR / "app").rglob("*.py")):
        teks = berkas.read_text()
        for no, baris in enumerate(teks.splitlines(), 1):
            telanjang = baris.split("#")[0]
            # `x = None` BUKAN penulisan angka, dan membedakannya penting:
            # pembatalan input justru MENGOSONGKAN kolom-kolom ini, dan pagar
            # yang menuduhnya akan dilonggarkan orang berikutnya alih-alih
            # dibetulkan. `\S` sesudah lookahead mengunci posisinya — tanpa itu
            # `\s*=\s*` mundur satu spasi dan lookahead-nya lolos di depan
            # " None".
            m = re.search(r"\b(harga_per_kg|harga_per_lembar|total_biaya|total_harga)"
                          r"\s*=\s*(?!None\b)\S", telanjang)
            if m and "def " not in telanjang and ":" not in telanjang.split("=")[0]:
                salah.append(f"{berkas.relative_to(AKAR)}:{no} · {m.group(1)}")
    assert not salah, ("layanan ini masih mengisi kolom uang: " + ", ".join(salah))
