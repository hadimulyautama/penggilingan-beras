"""Papan Beranda pemegang kedua gudang — celah ke-5 menjelang app meja dihapus.

Tiga hal yang hanya ada di Beranda Meja sampai 24 September 2026: blok "Perlu
perhatian", rincian keputusan (harga / output / mutu), dan satu baris per gudang.
Perhitungannya pindah ke `services/beranda.py` dan dipakai KEDUA app — dua
Beranda yang menghitung penyimpangan sendiri-sendiri akan menyebut angka berbeda
tentang pabrik yang sama, dan tak ada yang menyadarinya sebab tak ada yang
membuka keduanya berdampingan.
"""
from __future__ import annotations

import inspect

from app.services import beranda as svc
from app.services import keputusan as K
from app.web.layar_keputusan import AKSI_DIKENAL, JENIS_KEPUTUSAN, JENIS_MUTU
from tests.bantu import kode_saja


def test_tiap_jenis_keputusan_punya_golongan_tepat_satu():
    """Golongan yang ketinggalan satu jenis membuat rincian di Beranda tak
    berjumlah sama dengan lencananya — dan angka yang tak berjumlah membuat orang
    berhenti mempercayai keduanya.

    Inilah kelas galat yang sama yang menyembunyikan `betulkan_bobot_giling` dari
    setiap layar selama sebulan: daftar di satu tempat, kenyataan di tempat lain,
    dan tak ada yang membandingkannya.
    """
    semua = [a for golongan in svc.GOLONGAN_KEPUTUSAN.values() for a in golongan]
    assert sorted(semua) == sorted(AKSI_DIKENAL), \
        f"selisih: {set(semua) ^ set(AKSI_DIKENAL)}"
    assert len(semua) == len(set(semua)), "satu jenis masuk dua golongan"
    # Sejak layarnya DUA (24 September 2026), `AKSI_DIKENAL` adalah gabungan
    # keduanya — dan tiap jenis harus muncul di TEPAT SATU layar. Nol berarti
    # pekerjaan yang tak tergambar di mana pun; dua berarti kartu yang sama
    # ditagih di dua tempat, lalu dikerjakan dua kali.
    blok = [a for a, _ in JENIS_KEPUTUSAN] + [a for a, _ in JENIS_MUTU]
    assert sorted(blok) == sorted(AKSI_DIKENAL), f"selisih: {set(blok) ^ set(AKSI_DIKENAL)}"
    assert len(blok) == len(set(blok)), "satu jenis punya blok di dua layar"
    # Dan pembagiannya memang pembagian yang sama dengan golongannya — bukan
    # dua pendapat tentang apa itu "mutu".
    assert sorted(a for a, _ in JENIS_MUTU) == sorted(svc.GOLONGAN_KEPUTUSAN["mutu"])


def test_rincian_berjumlah_sama_dengan_lencana():
    """Bukan sekadar tiap jenis bergolongan: jumlah ketiganya harus SAMA dengan
    jumlah kartu meja, sebab keduanya tampil berdampingan di satu kartu."""
    # SELURUH jenis, dari sumbernya — bukan daftar satu layar. Sejak layarnya
    # dua, memakai `JENIS_KEPUTUSAN` saja membuat uji ini buta terhadap
    # golongan yang justru baru saja dipindahkan.
    # Baris KEDUA dari satu jenis, supaya yang diuji benar-benar penjumlahan
    # dan bukan sekadar "tiap jenis muncul sekali". Dulu barisnya
    # `verify_gabah`; aksinya dihapus 28 September 2026 bersama seluruh harga.
    meja = [{"aksi": a} for a in K.SEMUA] + [{"aksi": K.SEMUA[0]}]
    n = svc.hitung_keputusan(meja)
    assert sum(n.values()) == len(meja)
    # Jumlah tiap golongan dari SUMBERNYA, plus satu baris kembar di
    # atas — angka yang diketik di sini akan basi tiap kali satu jenis lahir
    # atau dihapus, dan yang basi cepat "diperbaiki" dengan menurunkan
    # tuntutannya. (Terakhir: `verify_output` dihapus 24 September 2026.)
    for golongan, daftar in K.GOLONGAN.items():
        tambahan = 1 if K.SEMUA[0] in daftar else 0
        assert n[golongan] == len(daftar) + tambahan, golongan


def test_hitung_keputusan_menerima_baris_maupun_dict():
    """Pos Produksi memberi `Baris`, Meja memberi dict hasil JSON. Satu fungsi
    untuk keduanya — dua fungsi berarti dua cara menghitung hal yang sama."""
    from app.services.berjalan import Baris

    b = [Baris(kode="X", isi="", keadaan="", aksi="qc_giling")]
    d = [{"aksi": "qc_giling"}]
    assert svc.hitung_keputusan(b) == svc.hitung_keputusan(d)


# `test_perhitungan_tinggal_di_layanan_bukan_di_api_meja` DIHAPUS 24 September
# 2026: subjeknya `web/meja_api.py`, dan berkas itu ikut hilang bersama app
# Meja. Yang dijaganya — perhitungan papan tinggal satu salinan — kini dijaga
# `test_beranda_produksi_memakai_papan_yang_sama` di bawah, terhadap satu-satunya
# Beranda yang tersisa.


def test_beranda_produksi_memakai_papan_yang_sama():
    from app import main

    kode = kode_saja(main.beranda)
    assert "svc_beranda.papan(" in kode
    # Bergerbang view meja — bukan peran tersimpan, dan bukan dihitung ulang
    # di templat.
    assert "view in V_MEJA" in kode
    # Bendera bloknya dibaca dari SATU tempat: `papan is not None`. Kalau
    # dibaca dari `view in V_MEJA` lagi, kegagalan kueri akan menggambar blok
    # kosong — dan blok kosong terbaca sebagai "tak ada yang perlu perhatian",
    # kalimat yang paling mahal untuk salah.
    assert "blok_perhatian=papan is not None" in kode
    assert "rinci_keputusan=papan is not None" in kode


def test_perhatian_hanya_memuat_yang_menyimpang():
    """Blok yang selalu berisi mengajari orang mengabaikannya."""
    kode = kode_saja(svc.perhatian)
    # Mesin: hanya yang notanya "hati" — keadaan yang MENAHAN pekerjaan.
    assert "== 'hati'" in kode
    # Tumpukan: hanya bila melewati batas, dan batasnya boleh tak diatur.
    assert "if maks and tump > maks" in kode
    # Butir "harga menggantung lebih dari dua hari" DIBUANG 28 September 2026
    # bersama seluruh harga (keputusan pemilik). Yang tersisa dua, dan aturan
    # blok ini justru menguat: hanya yang MENYIMPANG yang masuk.
    assert "flag_unverified" not in kode, "Beranda menagih harga lagi"


def test_baris_gudang_dari_daftar_bukan_dua_baris_tetap():
    """Sepuluh gudang = sepuluh baris. Menambah gudang berarti menambah baris di
    master, bukan di kode."""
    kode = kode_saja(svc.baris_gudang)
    assert "for gid, nama, fungsi in GUDANG" in kode
    assert "'g1'" not in kode and "'g2'" not in kode


def test_rincian_pintu_selalu_berjumlah_sama_dengan_lencananya():
    """App yang TAK punya layar mutu tetap menyebut bagian mutunya.

    Pemisahan layar 24 September 2026 sempat membuat Beranda Meja berbunyi
    "4 harga · 0 output" di bawah lencana 8: bagian mutunya hilang dari
    rinciannya sementara pintunya masih memuat mutu. Angka yang tak berjumlah
    membuat orang berhenti mempercayai keduanya — kelas galat yang sama yang
    sudah hidup di layar Menunggu keputusan app Meja (lencana 8, layar 7).

    Rinciannya menyebut isi PINTU ITU: dengan `blok_mutu` (Pos Produksi) bagian
    mutu pindah ke pintu kedua; tanpanya (Meja) ia tetap di tempatnya.
    """
    import pathlib

    tpl = (pathlib.Path(__file__).resolve().parents[1]
           / "hmu_tampilan/templates/beranda.html").read_text()
    blok = tpl.split('br.pintu("/keputusan"')[1].split("{% endif %}")[0]
    assert '"" if blok_mutu else " · " ~ n_mutu ~ " mutu"' in blok, \
        "rincian pintu keputusan tak lagi menyesuaikan diri dengan ada/tidaknya layar mutu"
    # Dan pintu mutunya sendiri memang bergerbang sendiri — bukan menumpang
    # `blok_keputusan`, yang akan menggambar tautan mati di app Meja.
    assert "{% if blok_mutu and MUTU %}" in tpl
    assert '"/mutu"' in tpl.split("{% if blok_mutu and MUTU %}")[1][:400]
