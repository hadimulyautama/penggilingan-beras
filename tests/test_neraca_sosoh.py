"""Neraca bobot penyosohan — 100% bahan baku, dibagi tanpa sisa.

Keputusan pemilik 2 Oktober 2026, berikut contohnya sendiri: *"jika yang
disosoh bahan bakunya termasuk campurannya adalah 10 ton lalu dari beras dan
semua produk samping hasilnya totalnya hanya 9900 kg. maka persentase susut
adalah 100 dibagi 10000"* — 1%.

Diuji atas ANGKA TELANJANG, bukan lewat basis data, dan itu sebabnya
`neraca_sosoh()` dibuat murni: rumus yang hanya bisa diuji lewat layar adalah
rumus yang tak pernah diuji pada kasus tepinya — dan kasus tepi rumus ini
(bahan nol, hasil melebihi bahan) justru yang paling berbahaya, sebab keduanya
berarti ada yang salah catat dan keduanya tak melempar galat apa pun.
"""
from __future__ import annotations

import pytest

from app.penggilingan.gudang2.polishing import (SAMPING_DISEBUT, beras_dari_output,
                                                neraca_sosoh, rendemen)


def test_contoh_pemilik_sepuluh_ton_susut_satu_persen():
    """⭐ Angka yang pemilik sebut sendiri, apa adanya."""
    n = neraca_sosoh(10_000, {"medium": 6_500, "broken": 1_200,
                              "menir": 700, "bekatul": 1_500})
    assert n.keluar_kg == pytest.approx(9_900)
    assert n.susut.kg == pytest.approx(100)
    assert n.susut.persen == pytest.approx(1.0)
    # Dan pembagiannya utuh: 65 + 12 + 7 + 15 + 1 = 100.
    assert n.beras.persen == pytest.approx(65.0)
    persen = {b.jenis: b.persen for b in n.samping}
    assert persen["broken"] == pytest.approx(12.0)
    assert persen["menir"] == pytest.approx(7.0)
    assert persen["bekatul"] == pytest.approx(15.0)


def test_jumlah_persennya_selalu_tepat_seratus():
    """⭐ IDENTITAS YANG MENJAGA KARTUNYA.

    Seluruh persen berpenyebut sama — PK terpakai — dan karena itu jumlahnya
    wajib 100%. Baris "Jumlah" di kaki kartu bukan hiasan: satu entri hasil
    yang salah ketik langsung menggeser susutnya, dan di sanalah ia terbaca
    tanpa seseorang perlu mencurigainya lebih dulu.

    Diuji atas bentuk-bentuk yang berbeda, termasuk yang hasilnya nol sama
    sekali (susut 100%) — di sanalah penjumlahan yang melewatkan satu suku
    paling mudah lolos.
    """
    for bahan, keluar in (
        (10_000, {"medium": 6_500, "broken": 1_200, "menir": 700, "bekatul": 1_500}),
        (10_000, {}),                                    # hasil belum ada: susut 100%
        (8_000, {"premium": 8_000}),                     # tanpa susut sama sekali
        (7_777, {"sayur": 1_111, "menir": 333, "reject": 7}),
        (1, {"bekatul": 1}),
    ):
        n = neraca_sosoh(bahan, keluar)
        jumlah = (n.beras.persen + sum(b.persen for b in n.samping)
                  + n.susut.persen)
        assert jumlah == pytest.approx(100.0), (bahan, keluar, jumlah)


def test_yang_pemilik_minta_disebut_tetap_tampil_walau_nol():
    """"bekatul 0%" adalah KABAR; baris yang hilang cuma membuat orang
    mengira pertanyaannya tak ditanyakan."""
    n = neraca_sosoh(1_000, {"medium": 1_000})
    ada = [b.jenis for b in n.samping]
    for jenis in SAMPING_DISEBUT:
        assert jenis in ada, f"{jenis} hilang dari kartu saat nol"
    # `reject` TIDAK diminta disebut, jadi ia tak ikut saat nol — daftar yang
    # memuat segalanya berhenti bisa dipindai.
    assert "reject" not in ada


def test_samping_yang_tak_diminta_tetap_DIJUMLAH_saat_ada():
    """⚠ Membuangnya dari jumlah akan memindahkan beratnya ke SUSUT.

    Dan susut adalah angka yang dipakai menuduh mesin bocor. `reject` tak
    pemilik sebut, tetapi ia barang yang sungguh keluar dari mesin.
    """
    n = neraca_sosoh(1_000, {"medium": 800, "reject": 200})
    assert n.susut.kg == pytest.approx(0), "reject mengalir ke susut"
    assert "reject" in [b.jenis for b in n.samping]
    assert n.susut.persen == pytest.approx(0)


def test_jenis_samping_baru_ikut_terjumlah_tanpa_menyunting_rumusnya():
    """Daftar sisanya diambil dari `BYPRODUCTS`, bukan ditulis tangan.

    Kalau tidak, jenis samping yang kelak ditambahkan ke master akan mengalir
    ke "susut" diam-diam — dan tak ada yang mencurigai susut yang naik 3%
    sesudah sebuah jenis baru dipakai.
    """
    import app.penggilingan.gudang2.polishing as P

    assert "BYPRODUCTS" in P.neraca_sosoh.__globals__
    # Keempat jenis samping yang dikenal hari ini wajib terjumlah.
    n = neraca_sosoh(1_000, {j: 250 for j in P.BYPRODUCTS})
    assert n.susut.kg == pytest.approx(0), \
        f"ada jenis samping yang tak terjumlah: {[b.jenis for b in n.samping]}"


def test_bahan_nol_bukan_nol_persen_melainkan_tak_bisa_dihitung():
    """⚠ Nol persen adalah PERNYATAAN bahwa tak ada yang jadi.

    Yang benar saat bahan bakunya belum tercatat adalah "tak bisa dihitung" —
    dan bedanya penting, sebab 0% beras pada kartu penyosohan akan dibaca
    sebagai mesin yang gagal total.
    """
    n = neraca_sosoh(0, {"medium": 500})
    assert not n.bisa_dihitung
    assert n.beras.persen is None
    assert n.susut.persen is None
    assert all(b.persen is None for b in n.samping)
    # Dan ia TIDAK ditandai timpang: timpang berarti "mustahil", sedangkan ini
    # cuma berarti "belum diketahui". Dua kabar yang berbeda tindak lanjutnya.
    assert not n.timpang


def test_hasil_melebihi_bahan_dilaporkan_bukan_dipangkas():
    """⚠ Susut negatif = SALAH CATAT, dan itu harus terbaca.

    Hasil dicatat ke proses yang keliru, atau satuan tertukar. Susut yang
    dipangkas jadi 0% membuat kesalahannya tak pernah terbaca di mana pun —
    dan yang tak terbaca tak pernah dibetulkan.
    """
    n = neraca_sosoh(1_000, {"premium": 2_000})
    assert n.susut.kg == pytest.approx(-1_000)
    assert n.susut.persen == pytest.approx(-100.0)
    assert n.timpang


def test_tak_ada_ambang_susut_terlalu_besar():
    """Susut 87% pun bukan "bahaya" — ia cuma angka.

    Pemilik belum menetapkan batas wajarnya, dan pagar yang ditebak sendiri
    akan menuduh mesin yang sehat. Aturan yang sama dipakai layar Jasa untuk
    batas ton (keputusan pemilik 10): angka apa adanya, tanpa warna bahaya.
    """
    n = neraca_sosoh(4_000, {"medium": 500})
    assert n.susut.persen == pytest.approx(87.5)
    assert not n.timpang, "susut besar bukan kemustahilan"


def test_beras_b_ikut_terhitung_beras():
    """`GRADES` memuat `beras_b`, dan `stok.GRADES_BERAS` SENGAJA tidak.

    Keduanya berbeda bukan karena salah satunya lupa: yang kedua memisahkan
    blok di layar Stok Produk. Menukarnya di sini menggeser penyebut rendemen
    seluruh pabrik tanpa satu pun galat.
    """
    assert beras_dari_output({"beras_b": 100}) == pytest.approx(100)
    n = neraca_sosoh(1_000, {"beras_b": 1_000})
    assert n.beras.persen == pytest.approx(100.0)
    assert n.susut.kg == pytest.approx(0)


def test_rendemen_satu_rumah():
    """Rumus rendemen MURNI, dan `rendemen_proses` tinggal membacanya.

    Angka ini menilai pekerjaan orang; dua rumus untuk satu angka berarti dua
    penilaian. Penyebutnya PK TERPAKAI — yang tersisa di silo belum disosoh.
    """
    import inspect

    from app.penggilingan.gudang2 import polishing as P

    assert rendemen(6_500, 10_000) == pytest.approx(65.0)
    assert rendemen(100, 0) is None, "pembagian nol wajib None, bukan galat"

    # `rendemen_proses` tak boleh menghitung sendiri lagi.
    badan = inspect.getsource(P.rendemen_proses)
    assert "rendemen(" in badan
    assert "* 100" not in badan, "rumusnya disalin ulang di rendemen_proses"

    # Dan kartunya pun lewat rumus yang sama, bukan `neraca.beras.persen` —
    # dua jalan yang kebetulan sepakat akan berselisih begitu satu disentuh.
    kartu = inspect.getsource(P.KartuSosoh)
    assert "return rendemen(" in kartu
