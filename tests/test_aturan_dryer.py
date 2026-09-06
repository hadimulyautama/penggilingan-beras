"""Uji aturan dryer — empat aturan yang ditegaskan Direksi 2 September 2026.

Aturan-aturan ini menentukan kapan gabah boleh masuk mesin pengering. Salah
satu saja longgar, dan dua muatan gabah bisa tercampur di satu mesin tanpa ada
yang menyadarinya sampai hasil gilingnya aneh.
"""
from __future__ import annotations

import inspect

from app.penggilingan.gudang1.services import drying


def test_lot_yang_mengering_maupun_mendinginkan_menutup_dryer():
    """Aturan 1: selagi mengering ATAU mendinginkan, tak ada gabah yang boleh
    masuk."""
    sumber = inspect.getsource(drying.active_drying_lot)
    assert 'DryingLot.status.in_(["proses", "selesai"])' in sumber


def test_lot_yang_belum_pindah_silo_tetap_menutup_dryer():
    """Aturan 2: sudah selesai dikeringkan DAN didinginkan pun, selama gabahnya
    masih menumpuk di dryer, dryer tetap tertutup. Inilah sebab syarat
    `belum_ke_silo` — tanpa itu, gabah baru masuk menimpa yang lama."""
    sumber = inspect.getsource(drying.active_drying_lot)
    assert "belum_ke_silo" in sumber
    assert "SiloStorage.drying_lot_id" in sumber


def test_masuk_dryer_menolak_saat_dryer_terisi():
    sumber = inspect.getsource(drying.masuk_dryer)
    assert "active_drying_lot" in sumber
    assert "masih dipakai lot" in sumber


def test_pendinginan_boleh_dinyatakan_berkali_kali():
    """Aturan 3: gabah yang sudah dinyatakan dingin bisa ternyata masih panas.
    Menolak pernyataan kedua memaksa operator berbohong pada catatan."""
    sumber = inspect.getsource(drying.finish_cooling)
    assert "sudah dinyatakan selesai pendinginan" not in sumber, \
        "penolakan pernyataan kedua seharusnya sudah dicabut"
    assert "diulang" in sumber, "putaran ulang harus terbaca di riwayat"


def test_basah_dan_kering_tak_boleh_bercampur_di_dryer():
    """Bukan bagian dari empat aturan itu, tetapi menjaga keempatnya berguna:
    dryer yang menerima campuran membuat kadar air lot tak berarti apa-apa."""
    assert "mencampur gabah basah & kering" in inspect.getsource(drying.masuk_dryer)


def test_pengeringan_satu_batch_diperingatkan_bukan_ditolak():
    """Dryer 30 ton yang dinyalakan untuk satu muatan kecil membakar bahan
    bakar yang sama dengan yang penuh, dan biayanya dibagi ke gabah yang lebih
    sedikit. Tetapi menahan gabah demi menunggu muatan kedua justru membuatnya
    menginap — jadi peringatan, bukan penolakan."""
    sumber = inspect.getsource(drying.start_drying)
    assert "len(loose) < 2" in sumber
    assert "peringatan" in sumber
    # Sesudah peringatan disusun, tak boleh ada penolakan — peringatan yang
    # diikuti `raise` bukan peringatan, itu penolakan dengan kalimat sopan.
    assert "raise DryingError" not in sumber.split("catatan: list[str] = []")[1]


def test_silo_campuran_diperingatkan_bukan_ditolak():
    """Gabahnya harus keluar dari dryer, dan menahannya sampai silo kosong
    memacetkan pengeringan berikutnya. Tetapi isinya jadi campuran, dan itu
    harus terbaca sekarang — bukan diketahui belakangan saat angka giling
    tidak seperti yang diingat orang."""
    from app.penggilingan.gudang1.services import silo
    from app.web import miniapp

    assert "digabung = await _silo_content_kg" in inspect.getsource(silo.masuk_silo)
    assert "isinya kini tercampur" in inspect.getsource(miniapp.act_pindah_silo)


# ─────────────── Tiap dryer berjalan sendiri-sendiri ───────────────

def test_keterisian_ditanyakan_per_mesin():
    """Aturan 1 & 2 kini berlaku per mesin. Menanyakan 'apakah dryer terpakai'
    tanpa menyebut mesinnya akan menutup seluruh pabrik gara-gara satu mesin
    sibuk."""
    sumber = inspect.getsource(drying.active_drying_lot)
    assert "dryer_id" in sumber
    assert "DryingLot.dryer_id == dryer_id" in sumber


def test_gabah_menunggu_disaring_per_mesin():
    """Tanpa saringan ini, 'mulai pengeringan' menyapu gabah dari SEMUA mesin
    ke dalam satu lot — gabah yang tidak pernah bertemu di mesin yang sama."""
    assert "PurchaseBatch.dryer_id == dryer_id" in inspect.getsource(
        drying._loose_dryer_batches)


def test_masuk_dan_mulai_keduanya_menyebut_mesin():
    for fungsi in (drying.masuk_dryer, drying.start_drying):
        assert "pilih_dryer" in inspect.getsource(fungsi)


def test_satu_mesin_tak_perlu_dipilih():
    """Menyuruh orang memilih dari daftar berisi satu pilihan bukan ketelitian,
    melainkan pekerjaan tambahan tanpa isi."""
    sumber = inspect.getsource(drying.pilih_dryer)
    assert "if len(mesin) == 1" in sumber


def test_mesin_batch_dilepas_saat_lot_terbentuk():
    """Setelah lot ada, mesinnya tersimpan di lot. Dua tempat yang menyebut
    hal yang sama cepat atau lambat berbeda."""
    assert "b.dryer_id = None" in inspect.getsource(drying.start_drying)


def test_tujuan_menyebut_mesin_dalam_satu_pilihan():
    """Bukan "Dryer" lalu ditanya lagi mesin mana: itu dua ketukan untuk satu
    keputusan, dan yang menekannya sedang berdiri memegang layar dengan satu
    tangan."""
    from app.web import miniapp

    assert miniapp._urai_tujuan("dryer:3") == ("dryer", 3)
    assert miniapp._urai_tujuan("silo_a") == ("silo_a", None)
    assert miniapp._urai_tujuan("tumpuk") == ("tumpuk", None)
    assert miniapp._urai_tujuan("") == ("", None)
    # Bentuk aneh tidak boleh menembus sebagai mesin nomor sekian.
    assert miniapp._urai_tujuan("dryer:abc") == ("dryer", None)


def test_daftar_tujuan_dibangkitkan_bukan_ditulis_tetap():
    """Mesin bisa bertambah lewat Pengaturan, dan daftar yang ditulis tetap
    akan diam-diam ketinggalan."""
    from app.web import miniapp

    sumber = inspect.getsource(miniapp.actions_menu)
    assert "_pilihan_tujuan_gabah" in sumber
    assert '["dryer", "Dryer"]' not in sumber


def test_mesin_tanpa_gabah_tak_ditawarkan_saat_mulai_pengeringan():
    """Menawarkan mesin kosong hanya menghasilkan penolakan 'tidak ada gabah
    di mesin itu' setelah orang memilihnya."""
    from app.web import miniapp

    assert "if not batches:" in inspect.getsource(miniapp.dryer_menunggu)


def test_kadar_air_dari_empat_sampel_bukan_satu_angka():
    """Kadar air diukur dari EMPAT titik dengan alat tes, dan yang dipakai
    rata-ratanya.

    Satu titik bisa kebetulan mengenai bagian yang paling basah atau paling
    kering, dan keputusan menghentikan pengeringan tak boleh bergantung pada
    satu tusukan. Layar lama cuma meminta satu angka — padahal servisnya sejak
    awal sudah membedakan bacaan mesin dari alat tes.
    """
    from app.penggilingan.gudang1.services import drying
    from tests.bantu import kode_saja

    kode = kode_saja(drying.log_moisture)
    assert "sampel" in kode
    assert "sum(isi) / len(isi)" in kode          # rata-rata, bukan satu angka
    for n in range(1, 5):
        assert f"kadar_air_tes_{n}" in kode       # mentahnya ikut disimpan


def test_bacaan_mesin_tidak_dirata_ratakan_bersama_alat_tes():
    """Keduanya mengukur hal yang sama dengan alat berbeda. Mencampurnya
    menghapus justru perbandingan yang berguna: mesin yang sensornya melenceng
    terlihat dari selisih yang tetap dari hari ke hari."""
    from app.penggilingan.gudang1.services import drying
    from tests.bantu import kode_saja

    kode = kode_saja(drying.log_moisture)
    # Baris yang menyusun daftar untuk dirata-ratakan — `ast.unparse`
    # membuang tanda kurungnya, jadi yang dicari isinya, bukan bentuk persis.
    baris = next(b for b in kode.splitlines() if b.strip().startswith("isi ="))
    assert "sampel" in baris
    assert "indikator" not in baris, "bacaan mesin ikut dirata-ratakan"
    assert "sum(isi) / len(isi)" in kode


def test_bentuk_lama_satu_angka_tak_patah():
    """Bot dan tautan tersimpan masih mengirim `kadar_air` tunggal. Ia
    diperlakukan sebagai bacaan mesin, persis seperti dulu."""
    from app.web.miniapp import KadarAirReq

    r = KadarAirReq(kode_lot="PGR-1", kadar_air=18)
    assert r.kadar_air == 18 and r.tes_1 is None and r.indikator is None
    # Bentuk baru: empat sampel, mesin terpisah.
    b = KadarAirReq(kode_lot="PGR-1", tes_1=18.2, tes_2=18.6, indikator=18.5)
    assert b.tes_1 == 18.2 and b.indikator == 18.5 and b.kadar_air is None


def test_hanya_titik_pertama_yang_wajib():
    """Alat tes bisa rusak, muatan bisa kecil. Memaksa empat angka berarti
    memaksa operator mengarang tiga di antaranya — dan catatan karangan lebih
    buruk daripada catatan yang kurang lengkap."""
    import inspect

    from app.web import miniapp

    spec = inspect.getsource(miniapp.susun_aksi) if hasattr(miniapp, "susun_aksi") \
        else inspect.getsource(miniapp)
    blok = spec[spec.index('"name": "tes_1"'):spec.index('"name": "indikator"')]
    assert '"optional": True' not in blok.split('"name": "tes_2"')[0]   # titik 1 wajib
    assert blok.count('"optional": True') == 3                          # titik 2–4 tidak


def test_kartu_pengeringan_menyebut_kedua_bacaan():
    """Kartu di layar Catat menyebut alat tes DAN bacaan mesin.

    Menampilkan rata-rata saja menghapus justru perbandingan yang berguna:
    keduanya mengukur hal yang sama dengan alat berbeda, dan yang menarik
    adalah saat keduanya tidak sepakat. Operator yang memutuskan "sudah cukup
    kering atau belum" juga tak perlu membuka laporan untuk angka terakhir.
    """
    import inspect

    from app.services import berjalan

    sumber = inspect.getsource(berjalan.untuk_gudang1)
    blok = sumber[sumber.index("_latest_log"):sumber.index('keadaan="menunggu kadar air turun"')]
    assert "kadar_air_tes_manual" in blok
    assert "kadar_air_indikator" in blok
    assert "alat tes" in blok and "mesin" in blok
    # Keadaan belum ada log pun harus terbaca, bukan kosong tanpa keterangan.
    assert "kadar air belum dicatat" in blok


def test_kemajuan_pengeringan_dihitung_dari_bacaan_pertama():
    """"1 lot" tak memberi tahu apa pun tentang sudah sejauh mana.

    18% itu jauh atau dekat sepenuhnya tergantung mulai dari berapa — jadi
    kemajuan diukur dari bacaan PERTAMA lot itu menuju target, bukan dari
    angka terakhirnya saja.
    """
    import inspect

    from app.services import dashboard

    sumber = inspect.getsource(dashboard._pengeringan_berjalan)
    assert "waktu_update.asc()" in sumber          # bacaan pertama, bukan terakhir
    assert "kadar_air_target_persen" in sumber
    assert "(awal - ka) / (awal - target)" in sumber
    # Dua bacaan tetap terpisah, tidak diruntuhkan jadi satu.
    assert '"tes": tes' in sumber and '"mesin": mesin' in sumber


def test_target_kadar_air_ada_setelannya():
    """Kemajuan hanya berarti kalau ada tujuannya — dan tujuan itu milik
    pabrik, bukan angka yang dikarang di dalam kode tampilan."""
    from app.config import settings

    assert settings.kadar_air_target_persen == 14


def test_mode_dryer_dipilih_yang_paling_dekat():
    """Aturan pemilik: mode yang dipakai adalah yang tonasenya PALING DEKAT
    dengan muatan — 23 ton memakai 25T, bukan 20T. Yang dicari jarak
    terdekat, bukan mode terbesar yang masih di bawahnya."""
    from app.penggilingan.gudang1.services.drying import MODE_DRYER, mode_disarankan

    assert MODE_DRYER == ("15T", "20T", "25T", "30T", "35T")
    assert mode_disarankan(23_000) == "25T"      # contoh pemilik sendiri
    assert mode_disarankan(22_000) == "20T"      # 22 lebih dekat ke 20
    assert mode_disarankan(23_500) == "25T"
    assert mode_disarankan(9_000) == "15T"       # di bawah mode terkecil
    assert mode_disarankan(40_000) == "35T"      # di atas mode terbesar
    assert mode_disarankan(0) == "15T"


def test_mode_tak_cocok_diperingatkan_bukan_ditolak():
    """Yang disimpan adalah pernyataan operator tentang setelan mesin yang
    SUNGGUHAN. Menolaknya berarti memaksa ia menuliskan mode yang bukan
    terpasang — dan catatan yang berbohong lebih buruk daripada catatan yang
    menyimpan ketidakcocokan beserta alasannya."""
    import inspect

    from app.penggilingan.gudang1.services import drying

    sumber = inspect.getsource(drying.start_drying)
    blok = sumber[sumber.index("if lot.mode_dryer:"):]
    assert "raise" not in blok.split("catatan.append")[0]
    assert "mode terdekat" in blok


def test_dua_peringatan_tak_saling_menghapus():
    """Mode yang tak cocok dan muatan satu batch adalah dua hal berbeda.
    Sebelumnya keduanya menulis ke variabel yang sama, jadi peringatan mode
    lenyap tiap kali muatannya kebetulan satu batch."""
    import inspect

    from app.penggilingan.gudang1.services import drying

    sumber = inspect.getsource(drying.start_drying)
    assert sumber.count("catatan.append") == 2
    assert 'peringatan = "\\n".join(catatan) or None' in sumber


def test_target_wajib_saat_mulai_pengeringan():
    """Pengeringan tanpa target adalah pengeringan yang tak punya garis
    selesai: kemajuannya tak bisa dihitung, dan "sudah cukup kering" jadi
    perasaan, bukan angka."""
    from tests.bantu import kode_saja
    from app.penggilingan.gudang1.services import drying

    kode = kode_saja(drying.start_drying)
    blok = kode[:kode.index("kondisi_set")]
    assert "target_kadar_air is None" in blok
    assert "raise DryingError" in blok


def test_target_boleh_berubah_seiring_pengeringan():
    """Gabah bisa ternyata lebih basah dari dugaan, atau pembeli berubah
    maunya. Perubahannya DICATAT — garis selesai yang bergeser tanpa jejak
    membuat "kenapa berhenti di 15%?" tak bisa dijawab bulan depan."""
    from tests.bantu import kode_saja
    from app.penggilingan.gudang1.services import drying

    kode = kode_saja(drying.log_moisture)
    assert "target_baru" in kode
    assert "lot.target_kadar_air = target_baru" in kode
    assert "field_name='target_kadar_air'" in kode or 'field_name="target_kadar_air"' in kode


def test_wajib_opt_in_bukan_kebalikan_optional():
    """Sebagian aksi sengaja meminta "isi minimal salah satu" — QC hasil
    giling menerima kadar air ATAU broken ATAU susut. Menjadikan semua kolom
    angka wajib secara diam-diam akan mematikan aksi-aksi itu."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parent.parent
          / "app" / "web" / "static" / "aksi.js").read_text()
    assert "f.wajib ?" in js                       # opt-in, bukan !f.optional
    assert '[data-wajib]' in js                    # input ikut diperiksa, bukan select saja
    assert "Belum diisi:" in js
