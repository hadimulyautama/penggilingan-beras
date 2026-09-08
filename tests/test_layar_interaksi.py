"""Uji jalan buntu di layar — kotak yang mati sesudah sekali ditekan.

Pemilik menemukannya: kartu di Antrian tunggu dan Menunggu keputusan ditekan,
lembarnya terbuka, lalu ia keluar dengan menekan area di luar — dan sesudah
itu kartu yang sama tak bisa ditekan lagi.

Sebabnya alamat yang berbohong. Kartu menaut ke `?buka=…&nilai=…`, dan
perpindahan halaman instan menolak tautan yang alamatnya sama persis dengan
alamat sekarang (kalau tidak, tiap ketukan pada layar yang sedang dibuka akan
memuat ulang halaman). Menutup lembar tidak membersihkan alamat itu, jadi
ketukan kedua ditolak — dan satu-satunya jalan keluar adalah memuat ulang
halaman, yang tak terpikir siapa pun.
"""
from __future__ import annotations

import pathlib

AKAR = pathlib.Path(__file__).resolve().parents[1]
AKSI = (AKAR / "app/web/static/aksi.js").read_text()
PINDAH = (AKAR / "app/web/static/pindah.js").read_text()
BASE = (AKAR / "app/web/templates/base.html").read_text()


def test_menutup_lembar_membersihkan_alamatnya():
    """Semua jalan keluar sama: Batal, Escape, ketukan di luar, dan simpan
    yang berhasil — keempatnya lewat `tutupLembar`."""
    assert "lupakanBuka();" in AKSI
    badan = AKSI.split("function tutupLembar()")[1].split("}")[0]
    assert "lupakanBuka()" in badan, "jalan keluar yang tak membersihkan alamat"

    fn = AKSI.split("function lupakanBuka()")[1].split("\n  }")[0]
    assert 'searchParams.delete("buka")' in fn
    assert 'searchParams.delete("nilai")' in fn
    # `replaceState`, BUKAN `pushState`: menutup lembar bukan langkah baru
    # dalam riwayat, dan tombol Kembali harus membawa orang ke layar
    # sebelumnya — bukan membuka lagi lembar yang baru saja ia tutup.
    assert "history.replaceState" in fn and "pushState" not in fn


def test_yang_sudah_dikerjakan_hilang_seketika():
    """Kartunya digambar server, jadi memuat ulang daftar aksi saja tak
    menyentuhnya. Layar yang masih menagih pekerjaan yang baru saja
    diselesaikan orangnya sendiri adalah cara tercepat membuatnya berhenti
    dipercaya."""
    assert "segarkan: function" in PINDAH
    simpan = AKSI.split("async function simpan(")[1].split("catch")[0]
    assert "PINDAH.segarkan(" in simpan
    # Kabarnya ditampilkan SESUDAH isinya ditukar — ia ikut tersapu bersama
    # isi lama kalau ditampilkan lebih dulu.
    assert 'PINDAH.segarkan(function () { kabar(pesan, "ok"); });' in simpan


def test_pintu_laci_layar_yang_sedang_dibuka_bukan_jalan_buntu():
    """Menekannya tak menghasilkan apa pun — alamatnya sama dengan alamat
    sekarang — dan lacinya menggantung terbuka."""
    assert 'laci.querySelectorAll(".pintu")' in BASE
    blok = BASE.split('laci.querySelectorAll(".pintu")')[1][:200]
    assert "buka(false)" in blok


def test_pendengar_papan_tik_tidak_menumpuk():
    """`document` tak ikut ditukar saat halaman berpindah, jadi pendengar
    yang dipasang langsung padanya bertambah satu tiap perpindahan — dan
    yang bertambah memegang elemen lama yang sudah dibuang."""
    for berkas, teks in (("aksi.js", AKSI), ("base.html", BASE)):
        keydown = teks.split('"keydown"')[0]
        assert keydown.rstrip().endswith("pasang(document,"), \
            f"{berkas}: pendengar keydown harus lewat PINDAH.pasang"


def test_setiap_kartu_membentang_di_tempat():
    """Pemilik: kotak yang ditekan harus membentang seperti laci, bukan
    melemparkan lembar melayang ke depan layar.

    Ketukan pertama yang artinya berbeda-beda di tiap kartu memaksa orang
    menebak apa yang akan terjadi sebelum menekan — dan yang menebak akan
    berhenti menekan. Jadi tiap baris yang punya tindakan wajib membawa
    `pilihan`, sekalipun isinya cuma satu.
    """
    import ast

    sumber = (AKAR / "app/services/berjalan.py").read_text()
    telanjang = []
    for simpul in ast.walk(ast.parse(sumber)):
        if not (isinstance(simpul, ast.Call)
                and getattr(simpul.func, "id", None) == "Baris"):
            continue
        kunci = {k.arg for k in simpul.keywords}
        if "aksi" in kunci and "pilihan" not in kunci:
            telanjang.append(f"baris {simpul.lineno}")
    assert not telanjang, (
        "baris ini masih melempar langsung ke lembar, bukan membentang:\n  "
        + "\n  ".join(telanjang))


def test_kartu_yang_membentang_membawa_seluruh_tindakannya():
    """Yang dibentangkan harus benar-benar bisa dikerjakan dari situ —
    membentang lalu menyuruh orang mencari tombolnya di tempat lain lebih
    buruk daripada tidak membentang sama sekali."""
    makro = (AKAR / "app/web/templates/_benda.html").read_text()
    blok = makro.split("{% if b.pilihan %}")[1].split("{% elif")[0]
    assert "<details" in blok and "<summary>" in blok
    assert 'class="pilihan"' in blok
    assert "{{ alamat }}?buka={{ id }}" in blok


def test_penunjuk_buka_tutup_sebaris_dengan_judulnya():
    """Dulu diapungkan ke kanan, dan apungan mengikuti BARIS TERAKHIR isi
    kartu — jadi pada kartu tinggi ia melorot ke bawah, jauh dari judul yang
    sebenarnya ia jelaskan. Penanda yang meleset terbaca sebagai cacat meski
    tak ada yang bisa menyebut apa yang salah."""
    css = (AKAR / "app/web/static/app.css").read_text()
    for kelas in ("benda", "padat"):
        blok = css.split(f"details.{kelas} > summary::after {{")[1].split("}")[0]
        assert "position: absolute" in blok, kelas
        assert "float" not in blok, f"{kelas}: apungan mengikuti baris terakhir"
        assert "width: 7px" in blok, f"{kelas}: ukurannya harus sama di kedua kartu"
    # Ruang kanannya disisakan supaya bobot yang panjang tak menabraknya.
    ringkas = css.split("details.benda > summary {")[1].split("}")[0]
    assert "padding: 13px 32px 13px 14px" in ringkas
