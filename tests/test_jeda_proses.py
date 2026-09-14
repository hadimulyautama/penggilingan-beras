"""Uji aturan berhenti sementara — pengeringan & giling.

Mesin berhenti di tengah jalan adalah kejadian sehari-hari, dan sebelum ada
tempat untuk itu operator hanya punya dua pilihan yang sama-sama merusak
catatan: membiarkan prosesnya "berjalan" padahal mesinnya mati, atau
menutupnya lalu memulai proses baru — yang membuat satu muatan gabah
terhitung dua kali.
"""
from __future__ import annotations

import inspect

from app.penggilingan.gudang1.services import jeda
from tests.bantu import kode_saja


def test_jeda_disimpan_sebagai_tabel_bukan_kolom():
    """Satu proses bisa berhenti berkali-kali dalam sehari, dan yang berguna
    justru jumlah PER SEBAB. Kolom pada lot hanya bisa menyimpan yang
    terakhir — dan yang terakhir hampir tak pernah yang terbesar."""
    from app.models import JedaProses

    kolom = {c.name for c in JedaProses.__table__.columns}
    assert {"jenis", "sebab", "mulai", "selesai", "dicatat_oleh"} <= kolom
    assert "drying_lot_id" in kolom and "milling_process_id" in kolom


def test_sebab_wajib_dan_boleh_ditulis_sendiri():
    """Berhenti tanpa sebab tak bisa dipakai memperbaiki apa pun. Tetapi
    daftar sebab tak akan pernah lengkap, dan daftar yang tak lengkap memaksa
    orang memilih yang paling mirip — lalu angkanya berbohong dengan rapi."""
    sumber = kode_saja(jeda.hentikan)
    assert "SEBAB_LAIN" in sumber
    assert "Tulis sebabnya dulu" in inspect.getsource(jeda.hentikan)
    assert "Pilih sebab berhentinya" in inspect.getsource(jeda.hentikan)


def test_dua_jenis_punya_daftar_sebabnya_sendiri():
    """Dryer tak pernah kepenuhan limbah; mesin giling tak pernah kehabisan
    bahan bakar. Daftar gabungan akan memaksa operator melewati sebab yang
    mustahil untuk mesinnya."""
    assert "Bahan bakar habis" in jeda.SEBAB["pengeringan"]
    assert "Bahan bakar habis" not in jeda.SEBAB["giling"]
    assert "Limbah produksi penuh" in jeda.SEBAB["giling"]
    assert "Limbah produksi penuh" not in jeda.SEBAB["pengeringan"]
    # "Mesin rusak" saja ambigu begitu ada mesin pendukung — dan sebab yang
    # ambigu tak bisa dipakai menghitung apa pun.
    for daftar in jeda.SEBAB.values():
        assert "Mesin rusak" not in daftar
        assert "Mesin pendukung rusak" in daftar


def test_tertahan_menghitung_jeda_yang_masih_berlangsung():
    """Proses yang sedang mati tak boleh terlihat seolah jam tertahannya
    berhenti bertambah — justru saat itulah angkanya paling perlu naik."""
    sumber = kode_saja(jeda.tertahan_detik)
    assert "j.selesai or kini" in sumber


def test_tak_bisa_berhenti_dua_kali():
    assert "memang sedang berhenti" in inspect.getsource(jeda.hentikan)


def test_lanjutkan_menolak_yang_tak_sedang_berhenti():
    assert "tidak sedang berhenti" in inspect.getsource(jeda.lanjutkan)


def test_proses_yang_sudah_selesai_tak_bisa_dihentikan():
    """Menghentikan yang sudah ditutup akan menciptakan jam tertahan pada
    proses yang jamnya sudah tidak berjalan."""
    assert "sudah tidak berjalan" in inspect.getsource(jeda._lot_berjalan)
    assert "sudah ditutup" in inspect.getsource(jeda._giling_berjalan)


def test_rekap_dijumlah_per_sebab_terbanyak_dulu():
    """Daftar kejadian cuma bisa dibaca; yang dijumlah per sebab bisa dipakai
    memutuskan — mesin pendukung yang memakan dua jam sehari itu belanja,
    bukan keluhan."""
    sumber = kode_saja(jeda.rekap_berhenti)
    assert "reverse=True" in sumber
    assert "b.detik" in sumber


def test_jeda_tak_bisa_dibatalkan_lewat_undo():
    """Yang benar bukan menghapus catatan berhentinya melainkan MELANJUTKAN
    prosesnya. Berhenti yang dihapus membuat jam berjalan ikut berbohong."""
    from app.services import undo

    # Punya label manusia — supaya riwayat tetap bisa dibaca orang …
    assert undo.label_tabel("jeda_proses") != "jeda_proses"
    # … tetapi TIDAK ada di daftar yang bisa dibatalkan.
    assert "jeda_proses" not in undo._UNDOABLE


def test_layar_berjalan_membedakan_yang_berhenti():
    """Yang sedang berhenti tak menunggu operator — ia menunggu montir. Kalau
    ia terbaca sama dengan yang sedang jalan, tak ada yang akan menelepon
    montirnya."""
    from app.services import berjalan

    sumber = kode_saja(berjalan.untuk_gudang1)
    assert "jeda_terbuka" in sumber
    assert "lanjutkan_proses" in sumber
    assert "hentikan_proses" in sumber


def test_dashboard_menyebut_berapa_lama_pabrik_berhenti():
    from app.services import dashboard

    assert "rekap_berhenti" in kode_saja(dashboard._berhenti_hari_ini)
    assert "Pabrik berhenti" in inspect.getsource(dashboard.render_dashboard_text)


def test_aksi_terdaftar_untuk_gudang1():
    from app.web import api

    assert api._ACTION_WH.get("hentikan_proses") == "g1"
    assert api._ACTION_WH.get("lanjutkan_proses") == "g1"


# ──────────────── Tiga golongan: antrean, berjalan, transit ────────────────

def test_antrean_hanya_yang_belum_punya_tempat():
    """Batasnya satu kalimat: begitu gabahnya punya tempat, ia bukan antrean
    lagi. Daftar itu jadi punya arti yang tajam — ia yang seharusnya kosong
    saat pulang, karena isinya berarti ada gabah bermalam tanpa tempat."""
    from app.services import berjalan

    import re

    sumber = inspect.getsource(berjalan.untuk_gudang1)

    def golongan(penanda: str) -> str:
        """Baris yang memuat `penanda` masuk golongan mana.

        Dicari MUNDUR dari penandanya ke `b.<golongan>.append` terdekat —
        penandanya sendiri berada di dalam panggilan itu, jadi memotong ke
        depan justru melewatkan nama golongannya.
        """
        i = sumber.index(penanda)
        cocok = list(re.finditer(r"b\.(menunggu|berjalan|transit)\.append", sumber[:i]))
        assert cocok, penanda
        return cocok[-1].group(1)

    # Yang sudah punya tempat: menunggu dinyalakan, menunggu diangkut ke silo,
    # menunggu digiling — semuanya `transit`, bukan `menunggu`.
    assert golongan("batch di {mesin.nama}") == "transit"
    assert golongan("sudah dingin, dryer perlu dikosongkan") == "transit"
    assert golongan("gabah kering · {_kg(kg_silo)}") == "transit"
    # Yang belum punya tempat tetap antrean. Tiket datang sebagai satu
    # daftar utuh dari `_tiket_belum_ditaut`, jadi yang diperiksa
    # penggabungannya — bukan `append` seperti baris lain.
    assert "b.menunggu += await _tiket_belum_ditaut(db)" in sumber
    assert golongan("menumpuk · ") == "menunggu"
    # Yang mesinnya bekerja tetap berjalan.
    assert golongan("pengeringan selesai, sedang didinginkan") == "berjalan"


def test_kartu_yang_sama_tak_muncul_di_dua_layar():
    """Kartu yang sama di dua tempat adalah dua tempat di kepala orang, dan
    cepat atau lambat keduanya berbeda isi."""
    from app import main
    from app.web import layar_berjalan

    aksi = kode_saja(main.halaman_aksi)
    assert "berjalan=[]" in aksi, "layar antrean tak boleh ikut memuat yang berjalan"
    jalan = kode_saja(layar_berjalan.halaman_berjalan)
    assert "transit=b.transit" in jalan
    assert "menunggu=" not in jalan


def test_kartu_punya_bentuk_yang_bisa_dipindai():
    """Beberapa kalimat bertumpuk dengan ukuran, warna, dan tebal yang sama
    bukan keterangan melainkan dinding."""
    from app.services.berjalan import Baris

    b = Baris(kode="x", isi="y", keadaan="z")
    for kolom in ("judul", "utama", "sub", "fakta", "anak", "nota"):
        assert hasattr(b, kolom), kolom


def test_dua_layar_memakai_bentuk_kartu_yang_sama():
    """Markup kartu yang ditulis dua kali sudah pernah berselisih di sini."""
    import pathlib

    akar = pathlib.Path(__file__).resolve().parents[1] / "app/web/templates"

    # Bentuknya tinggal satu berkas, dan di situlah markupnya berada.
    makro = (akar.parents[2] / "hmu_tampilan/templates/_benda.html").read_text()
    assert "{% macro" in makro
    assert "benda__nilai" in makro and 'class="fakta"' in makro
    assert "padat__nilai" in makro, "bentuk padat Beranda ikut di sini"

    # Layar yang memakainya MENGIMPOR, tidak menyalin. Salinan itulah yang
    # dulu berselisih, dan tesnya ada supaya tak lahir salinan berikutnya.
    for berkas in ("aksi.html", "berjalan.html", "beranda.html"):
        teks = (akar / berkas).read_text()
        assert '"_benda.html"' in teks, berkas
        assert "with context" in teks, f"{berkas}: `lama` datang dari rute"
        assert "benda__nilai" not in teks, f"{berkas}: markup kartu disalin lagi"


def test_yang_menahan_pekerjaan_berteriak():
    """Pemilik: kartu di Sedang berjalan yang prosesnya belum mulai atau
    dijeda, peringatannya harus lebih jelas.

    Sebelumnya keduanya digambar setipis keterangan biasa — garis rambut
    dengan tinta redup — jadi kartu yang BERHENTI terbaca sama dengan kartu
    yang berjalan. Yang terbaca sama akan dilewati sama.
    """
    import pathlib

    from app.services import berjalan as svc

    akar = pathlib.Path(__file__).resolve().parents[1]
    sumber = inspect.getsource(svc.untuk_gudang1)

    # Mesin yang belum dinyalakan — gabah yang bermalam tanpa dipanaskan
    # tidak diam saja, ia menurun mutunya.
    assert "Mesin belum dinyalakan — gabah sudah menunggu" in sumber
    # Jeda menyebut SUDAH BERAPA LAMA. "Menunggu dilanjutkan" tak memberi
    # tahu apakah itu lima menit atau sejak kemarin — dan justru itu yang
    # menentukan apakah seseorang harus turun tangan sekarang.
    assert 'f"Dijeda {_jam(tertahan)} — {macet.sebab}"' in sumber
    assert sumber.count('nota_jenis="hati"') >= 1
    assert 'nota_jenis="hati" if macet else None' in sumber

    # Silo yang menunggu giliran TIDAK ikut berteriak: ia boleh menunggu
    # berhari-hari tanpa ada yang salah.
    blok = sumber[sumber.index("huruf = silo.nama_silo"):]
    blok = blok[:blok.index("b.transit.append") + 600]
    assert "nota_jenis" not in blok

    css = (akar / "hmu_tampilan/static/app.css").read_text()
    hati = css.split(".nota--hati {")[1].split("}")[0]
    assert "background:" in hati and "var(--hati)" in hati


def test_lama_tertahan_selalu_berkata_sesuatu():
    """Nol pun disebut — "baru saja" memberi tahu bahwa jamnya memang
    dihitung, bukan bahwa ia tak diketahui."""
    from app.services.berjalan import _jam

    assert _jam(0) == "baru saja"
    assert _jam(90) == "1 menit"
    assert _jam(3700) == "1 jam 1 menit"
    assert _jam(100000) == "1 hari 3 jam"
