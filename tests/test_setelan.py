"""Uji setelan pabrik & tempat katalog aksi.

Dua hal yang ditemukan pemilik saat memakai beta: daftar aksi lengkap masih
menggantung di bawah antrean, dan setelan yang ada di rancangan tak ada di
aplikasi.
"""
from __future__ import annotations

import inspect
import pathlib
import types

from app.services import setelan
from app.web.tampilan import templates
from tests.bantu import kode_saja

AKAR = pathlib.Path(__file__).resolve().parents[1]


def _akun(peran: str):
    a = types.SimpleNamespace(nama="Pras", peran=peran, sesi_pendek=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def test_katalog_aksi_keluar_dari_antrean():
    """Antrean adalah daftar BENDA. Daftar kata kerja di bawahnya cuma
    menawarkan pintu kedua untuk pekerjaan yang sudah punya pintu — dan
    membuat antrean berhenti berarti apa yang ia namai."""
    html = (AKAR / "app/web/templates/aksi.html").read_text()
    assert "semua-aksi" not in html
    assert "Catat pekerjaan lain" not in html.split("{% block isi %}")[1] \
        or "/aksi-lain" in html


def test_katalog_punya_alamatnya_sendiri():
    """Tak ada yang boleh jadi tak terjangkau: aksi yang tak berwujud benda —
    harga, QC, barang keluar, pembatalan — tetap perlu pintu."""
    from app import main
    from app.web.nav import TAB

    assert any(k == "aksi_lain" for k, *_ in TAB)
    assert hasattr(main, "halaman_aksi_lain")
    # Dan halamannya benar-benar memuat kerangka yang diisi aksi.js. Templatnya
    # milik paket sejak 23 September 2026 (ketiga app memakainya); paragraf
    # pembukanya yang tinggal di sini, karena ia menyebut layar app ini.
    html = (AKAR / "hmu_tampilan/templates/aksi_lain.html").read_text()
    assert 'id="layar"' in html and "aksi.js" in html
    kata = (AKAR / "app/web/templates/_kata_aksi_lain.html").read_text()
    assert 'href="/aksi"' in kata and 'href="/berjalan"' in kata


def test_antrean_kosong_menunjuk_ke_mana_lagi():
    """Layar kosong tanpa kalimat adalah tempat aplikasi terlihat rusak,
    padahal justru sedang benar."""
    html = templates.get_template("aksi.html").render(
        request=None, akun=_akun("operator"), layar="aksi", MENUNGGU=0,
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None,
        menunggu=[], berjalan=[], buka="", nilai="", lama=lambda t: "", FASE={})
    assert "Tidak ada yang menunggu Anda" in html
    assert "/berjalan" in html and "/aksi-lain" in html


def test_setelan_kerja_hanya_untuk_admin():
    """Operator mengurus data dirinya sendiri dan sandinya sendiri, tak lebih.
    Sebab berhenti dan target bawaan menyentuh pekerjaan semua orang."""
    kosong = templates.get_template("pengaturan.html").render(
        request=None, akun=_akun("operator"), layar="pengaturan", MENUNGGU=0,
        MODE_UJI=True, LIHAT_SEBAGAI=None, kembali=None, pesan_ok=None, err="",
        tuan=False, target_bawaan=None, sebab_jeda={}, mutu_aktif=False,
        JAM_BATAS=48, blok_setelan=False, PROSES=())
    for blok in ("Sebab berhenti", "Target kadar air", "Batas ubah catatan"):
        assert blok not in kosong, blok

    penuh = templates.get_template("pengaturan.html").render(
        request=None, akun=_akun("admin"), layar="pengaturan", MENUNGGU=0,
        MODE_UJI=True, LIHAT_SEBAGAI=None, kembali=None, pesan_ok=None, err="",
        tuan=True, target_bawaan=14.0,
        sebab_jeda={"pengeringan": ["Listrik padam", "Bahan bakar habis"],
                    "giling": ["Mesin giling rusak", "Limbah produksi penuh"]},
        mutu_aktif=True, JAM_BATAS=48, blok_setelan=True,
        PROSES=(("pengeringan", "Pengeringan"), ("giling", "Giling")))
    # Satu blok per PROSES, bukan satu blok per setelan: yang dicari orang
    # adalah "setelan pengeringan", bukan "setelan target". Sebab berhenti
    # tinggal di dalam bloknya masing-masing.
    for blok in ("Sebab berhenti", "Target kadar air",
                 "Batas ubah catatan", "Listrik padam", "Mesin giling rusak"):
        assert blok in penuh, blok
    assert penuh.count("Sebab berhenti") == 2, "sebab berhenti bukan dua blok proses"
    assert "Sebab berhenti · " not in penuh, "judul lama yang berdiri sendiri kembali"


def test_batas_48_jam_ditampilkan_tapi_tak_bisa_diubah():
    """Batas yang bisa dilonggarkan oleh orang yang ingin melonggarkannya
    bukan batas. Tetapi menyembunyikannya juga salah — setelan yang diam tanpa
    keterangan akan dicari orang di menu lain sampai lelah."""
    html = (AKAR / "hmu_tampilan/templates/pengaturan.html").read_text()
    blok = html[html.index("Batas ubah catatan"):]
    blok = blok[:blok.index("</div>\n</div>") + 12] if "</div>\n</div>" in blok else blok
    assert "<form" not in blok, "batas tak boleh punya borang"
    assert "keputusan Direksi" in blok


def test_sebab_berhenti_tak_boleh_dikosongkan():
    """Berhenti tanpa sebab tak bisa dipakai memperbaiki apa pun."""
    assert "tak boleh kosong" in inspect.getsource(setelan.set_sebab_jeda)


def test_setelan_rusak_sebagian_tak_mengosongkan_borang():
    """Setelan yang gagal dibaca tak boleh membuat borang jeda tak punya
    pilihan sama sekali — operator lalu tak bisa mencatat berhentinya."""
    sumber = kode_saja(setelan.sebab_jeda)
    assert "JSONDecodeError" in sumber
    assert "simpan.get(k) or v" in sumber


def test_borang_jeda_membaca_setelan_bukan_konstanta():
    """Yang ditambahkan admin harus langsung muncul tanpa menunggu kode
    berubah."""
    from app.web import api

    sumber = inspect.getsource(api.actions_menu)
    assert "SEBAB_AKTIF" in sumber
    assert "await sebab_jeda(db)" in sumber


def test_satu_tombol_satu_perubahan():
    """Borang yang mengirim seluruh daftar sekaligus akan menimpa perubahan
    orang lain yang membuka layar yang sama semenit lebih dulu."""
    from app.web import pengaturan

    sumber = kode_saja(pengaturan.ubah_sebab_jeda)
    assert "tambah" in sumber and "buang" in sumber


def test_mutu_dipasang_sebagai_saklar_yang_menunjukkan_keadaannya():
    """Tombol bertuliskan "Matikan" memaksa orang membaca dulu keadaan
    sekarang untuk tahu arah tekanannya. Saklar MENUNJUKKAN keadaannya."""
    html = (AKAR / "hmu_tampilan/templates/pengaturan.html").read_text()
    blok = html[html.index("Mutu &amp; QC"):]
    assert 'role="switch"' in blok, "bukan saklar"
    assert 'aria-checked="{{ \'true\' if mutu_aktif else \'false\' }}"' in blok
    assert "saklar--nyala' if mutu_aktif" in blok
    # Satu ketukan, bukan centang lalu "Simpan": setelan yang perlu dua ketukan
    # sering tinggal satu.
    assert blok.count("<button") == 1


def test_setelan_dikelompokkan_per_proses():
    """Halaman ini pernah jadi deretan judul yang harus digulung untuk
    menemukan satu angka: target kadar air, lalu sebab berhenti pengeringan,
    lalu sebab berhenti giling, masing-masing dengan judulnya sendiri. Yang
    dicari orang adalah "setelan pengeringan", bukan "setelan target"."""
    html = (AKAR / "hmu_tampilan/templates/pengaturan.html").read_text()
    assert "Sebab berhenti · " not in html, "judul lama yang berdiri sendiri kembali"
    # Sebab berhenti tinggal di dalam blok prosesnya, lewat satu macro —
    # dua salinan akan berbeda begitu salah satunya diperbaiki.
    assert "{% macro sebab_blok(" in html
    # Sejak Tahap 2 templatnya BERLINGKAR atas daftar proses, dan daftarnya
    # milik app: Meja punya blok Penyosohan yang tak ada di sini. Jadi yang
    # menyebut "Pengeringan" dan "Giling" adalah rutenya, bukan markupnya —
    # dan judulnya tetap digambar `<span class="lbl">` yang sama.
    assert "{% for jenis, judul in PROSES %}" in html
    assert '<span class="lbl">{{ judul }}</span>' in html
    assert html.count("{{ sebab_blok(jenis) }}") == 1
    from app.web import pengaturan

    rute = kode_saja(pengaturan.halaman_pengaturan)
    assert "('pengeringan', 'Pengeringan')" in rute and "('giling', 'Giling')" in rute
    assert "penyosohan" not in rute, "setelan Gudang 2 diurus dari Meja"

    # Dilipat: daftar sebab tumbuh — itu memang gunanya — dan daftar yang
    # tumbuh terus membuat setelan di bawahnya makin jauh dari jangkauan.
    # Jumlahnya disebut di ringkasannya, supaya yang cuma ingin tahu "ada
    # berapa" tak perlu membukanya.
    assert '<details class="lipat">' in html
    assert "lipat__jml" in html and "|length }}</span>" in html

    # Setelan sebaris untuk yang isinya satu angka: halaman ini panjangnya
    # jangan ditentukan oleh setelan yang paling jarang diubah.
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    assert ".sebaris-borang" in css and ".saklar {" in css
