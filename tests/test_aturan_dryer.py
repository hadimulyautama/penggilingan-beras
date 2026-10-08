"""Uji aturan dryer — empat aturan yang ditegaskan Direksi 2 September 2026.

Aturan-aturan ini menentukan kapan gabah boleh masuk mesin pengering. Salah
satu saja longgar, dan dua muatan gabah bisa tercampur di satu mesin tanpa ada
yang menyadarinya sampai hasil gilingnya aneh.
"""
from __future__ import annotations

import inspect
import pathlib

from app.penggilingan.gudang1.services import drying
from tests.bantu import kode_saja


def _aksi(api, id_aksi: str) -> dict:
    """Spesifikasi satu aksi, dibaca dari SUMBER `actions_menu`.

    Memanggil fungsinya butuh basis data — dan yang diperiksa di sini bentuk
    spesifikasinya, bukan isinya saat jalan."""
    import ast
    import textwrap

    pohon = ast.parse(textwrap.dedent(inspect.getsource(api.actions_menu)))
    for simpul in ast.walk(pohon):
        if not isinstance(simpul, ast.Dict):
            continue
        for k, v in zip(simpul.keys, simpul.values):
            if (isinstance(k, ast.Constant) and k.value == "id"
                    and isinstance(v, ast.Constant) and v.value == id_aksi):
                # Hanya kunci bernilai tetap yang bisa dibaca tanpa dijalankan;
                # `options` yang dibangkitkan memang tak diperiksa di sini.
                keluar = {}
                for kk, vv in zip(simpul.keys, simpul.values):
                    if not isinstance(kk, ast.Constant):
                        continue
                    try:
                        keluar[kk.value] = ast.literal_eval(vv)
                    except ValueError:
                        pass
                return keluar
    raise AssertionError(f"aksi {id_aksi} tidak ada di actions_menu")


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
    from app.web import api

    assert "digabung = bool(sebelum)" in inspect.getsource(silo.masuk_silo)
    assert "isinya kini tercampur" in inspect.getsource(api.act_pindah_silo)
    # Dan peringatannya menyebut ISI yang sudah ada, bukan sekadar bahwa silo
    # "sudah berisi" — dua lot pengeringan yang menumpuk adalah keadaan lain
    # daripada hasil pengeringan sendiri yang bertemu gabah beli kering.
    assert "isi_sebelumnya" in inspect.getsource(api.act_pindah_silo)


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
    from app.web import api

    assert api._urai_tujuan("dryer:3") == ("dryer", 3)
    assert api._urai_tujuan("silo_a") == ("silo_a", None)
    assert api._urai_tujuan("tumpuk") == ("tumpuk", None)
    assert api._urai_tujuan("") == ("", None)
    # Bentuk aneh tidak boleh menembus sebagai mesin nomor sekian.
    assert api._urai_tujuan("dryer:abc") == ("dryer", None)


def test_daftar_tujuan_dibangkitkan_bukan_ditulis_tetap():
    """Mesin bisa bertambah lewat Pengaturan, dan daftar yang ditulis tetap
    akan diam-diam ketinggalan."""
    from app.web import api

    sumber = inspect.getsource(api.actions_menu)
    assert "_pilihan_tujuan_gabah" in sumber
    assert '["dryer", "Dryer"]' not in sumber


def test_mesin_tanpa_gabah_tak_ditawarkan_saat_mulai_pengeringan():
    """Menawarkan mesin kosong hanya menghasilkan penolakan 'tidak ada gabah
    di mesin itu' setelah orang memilihnya."""
    from app.web import api

    assert "if not batches:" in inspect.getsource(api.dryer_menunggu)


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
    from app.web.api import KadarAirReq

    r = KadarAirReq(kode_lot="PGR-1", kadar_air=18)
    assert r.kadar_air == 18 and r.tes_1 is None and r.indikator is None
    # Bentuk baru: empat sampel, mesin terpisah.
    b = KadarAirReq(kode_lot="PGR-1", tes_1=18.2, tes_2=18.6, indikator=18.5)
    assert b.tes_1 == 18.2 and b.indikator == 18.5 and b.kadar_air is None
    # Bentuk TERBARU: satu daftar, sepanjang titik yang benar-benar diukur.
    c = KadarAirReq(kode_lot="PGR-1", tes=[18.2, 18.6, 19.0], indikator=18.5)
    assert c.tes == [18.2, 18.6, 19.0] and c.tes_1 is None


def test_hanya_titik_pertama_yang_wajib():
    """Alat tes bisa rusak, muatan bisa kecil. Memaksa empat angka berarti
    memaksa operator mengarang tiga di antaranya — dan catatan karangan lebih
    buruk daripada catatan yang kurang lengkap.

    Empat kotak bernomor diganti SATU kotak berikut tombol yang menambah
    kotak, jadi aturannya sekarang dijaga di dua tempat: spesifikasinya
    menyebut satu medan wajib, dan `aksi.js` hanya memberi `data-wajib` pada
    kotak pertama.
    """
    import inspect
    import pathlib

    from app.web import api

    spec = inspect.getsource(api)
    blok = spec[spec.index('"name": "tes"'):spec.index('"name": "indikator"')]
    assert '"type": "ulang"' in blok and '"wajib": True' in blok
    # Empat kolom tersimpan; menaikkan `maks` tanpa migrasi akan membuang
    # titik kelima diam-diam.
    assert '"maks": 4' in blok

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/aksi.js").read_text()
    tambah = js[js.index("[data-tambah]"):]
    assert 'removeAttribute("data-wajib")' in tambah[:1200], (
        "kotak yang ditambahkan ikut wajib — menekan tambah lalu ragu jadi "
        "tak bisa disimpan")


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
    # Batas blok mengikuti kalimatnya, bukan kata yang kebetulan ada di
    # sekitarnya — sejak jeda ditambahkan, keadaannya tak lagi satu kalimat
    # tetap.
    blok = sumber[sumber.index("_latest_log"):sumber.index("menunggu kadar air turun")]
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

    from app.penggilingan.gudang1.services import drying
    from app.services import berjalan, dashboard

    # Titik tolaknya bacaan PERTAMA, bukan terakhir.
    assert "waktu_update.asc()" in inspect.getsource(drying.kadar_air_awal)
    assert "(awal - kini) / (awal - target)" in inspect.getsource(drying.kemajuan)

    # Rumusnya SATU. Dashboard dan layar Beranda memanggilnya, tidak menyalin —
    # dua salinan rumus yang sama adalah dua angka yang cepat atau lambat
    # berbeda, dan yang berbeda diam-diam tak akan ada yang menyadarinya.
    dash = inspect.getsource(dashboard._pengeringan_berjalan)
    assert "kadar_air_target_persen" in dash
    assert "kemajuan(awal, ka, target)" in dash
    assert "kemajuan(await kadar_air_awal(db, lot.id)" in inspect.getsource(
        berjalan.untuk_gudang1)
    # Dua bacaan tetap terpisah, tidak diruntuhkan jadi satu.
    assert '"tes": tes' in dash and '"mesin": mesin' in dash


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
          / "hmu_tampilan" / "static" / "aksi.js").read_text()
    assert "f.wajib ?" in js                       # opt-in, bukan !f.optional
    assert '[data-wajib]' in js                    # input ikut diperiksa, bukan select saja
    assert "Belum diisi:" in js


# ──────────────────── Campur basah–kering: ditutup, bukan ditolak ───────────
#
# Aturan ini sudah ditegakkan di `masuk_dryer` sejak lama. Yang ditambahkan di
# sini bukan aturannya, melainkan KAPAN ia terasa: pilihan yang mustahil harus
# tertutup sebelum ditekan, bukan ditolak sesudahnya. Penolakan sesudah
# ditekan tetap benar — tetapi saat itu batch-nya sudah tercatat dan harus
# ditempatkan ulang dengan tangan.

def test_isi_dryer_membaca_lot_maupun_batch_lepas():
    """Gabah di dryer punya dua bentuk: batch lepas yang menunggu mesin
    dinyalakan, dan lot yang sedang dikeringkan atau didinginkan. Membaca satu
    saja berarti separuh keadaan terlihat kosong."""
    sumber = kode_saja(drying.isi_dryer)
    assert "active_drying_lot" in sumber
    assert "_loose_dryer_batches" in sumber
    assert "kondisi_gabah" in sumber


def test_isi_dryer_tetap_menghalangi_setelah_pendinginan_selesai():
    """Inti bahayanya: mesin yang pengeringan & pendinginannya sudah selesai
    terasa 'sudah bebas', padahal gabahnya masih di dalam. `active_drying_lot`
    memang mencakup lot berstatus 'selesai' yang belum ke silo — dan
    `isi_dryer` harus ikut memakainya, bukan menyaring lot yang masih
    berproses saja."""
    sumber = kode_saja(drying.isi_dryer)
    assert "status" not in sumber, \
        "isi_dryer tidak boleh menyaring lot berdasarkan statusnya sendiri"


def test_pilihan_tujuan_menyebut_isi_tiap_mesin():
    """Operator harus bisa melihat isi mesin SEBELUM memilihnya."""
    from app.web import api

    sumber = kode_saja(api._pilihan_tujuan_gabah)
    assert "isi_dryer" in sumber
    assert "berisi gabah" in sumber


def test_label_mesin_tak_bergantung_kondisi_gabah_yang_masuk():
    """Daftar ini dibangun dua kali — untuk gabah basah dan untuk gabah kering
    — lalu digabung dengan membuang yang kembar. Label yang menyebut kondisi
    gabah yang MASUK akan berbeda di kedua daftar, dan mesin yang sama muncul
    dua kali."""
    from app.web import api

    sumber = kode_saja(api._pilihan_tujuan_gabah)
    kepala = sumber[:sumber.index("for d in mesin:")]
    ekor = sumber[sumber.index("for d in mesin:"):]
    # Variabel `kondisi` (kondisi gabah yang masuk) boleh dipakai untuk memilih
    # jenis dan untuk label tumpukan, tetapi tidak untuk menamai mesin.
    baris_mesin = [b for b in ekor.splitlines() if "dryer:" in b or "berisi" in b]
    assert baris_mesin
    for b in baris_mesin:
        assert "{kondisi}" not in b, f"label mesin ikut kondisi gabah masuk: {b}"
    assert "GABAH_BASAH" in kepala


def test_gabah_masuk_menolak_campuran_sebelum_batch_dibuat():
    """Penolakan sesudah batch tercatat menyisakan pekerjaan bersih-bersih.
    Untuk hal yang sudah pasti salah, tolak lebih dulu."""
    from app.web import api

    sumber = kode_saja(api.act_gabah_masuk)
    i_periksa = sumber.index("await isi_dryer")
    # Yang dicari PANGGILANNYA, bukan barisan `import` di kepala fungsi —
    # urutan import tak mengatakan apa-apa tentang urutan kejadian.
    i_buat = sumber.index("await create_purchase_batch_dari_timbang")
    assert i_periksa < i_buat, \
        "pemeriksaan campuran harus mendahului pembuatan batch"
    assert "tidak boleh dicampur" in sumber


# ──────────────────── Silo: boleh campur, wajib terbaca ────────────────────
#
# Keputusan pemilik 6 September 2026: silo TETAP boleh menerima hasil
# pengeringan sendiri bersama gabah yang dibeli sudah kering — menahannya
# sampai ada silo kosong hanya memacetkan dryer. Syaratnya campuran itu
# terbaca: diperingatkan saat terjadi, dan disebut komposisinya di laporan.

def test_laporan_silo_menyebut_seluruh_isi_bukan_baris_pertama():
    """Sebelum ini laporan mengambil baris lot yang PERTAMA ditemukan. Gabah
    kering yang menumpuk di silo yang sama hilang dari laporan berikut
    beratnya, dan yang membaca mengira silo itu berisi lot saja."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.laporan_silo)
    assert "next((r for r in rows if r.drying_lot_id)" not in sumber, \
        "laporan tak boleh berhenti di baris lot yang pertama"
    assert "isi_silo" in sumber
    assert "_tercampur" in sumber


def test_laporan_silo_menandai_campuran():
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.laporan_silo)
    assert "TERCAMPUR" in sumber


def test_campuran_dinilai_dari_asal_bukan_jumlah_baris():
    """Dua lot pengeringan yang menumpuk masih SATU asal. Yang menghapus batas
    yang ingin dilihat pemilik adalah hasil pengeringan sendiri yang bertemu
    gabah beli kering."""
    from app.penggilingan.gudang1.services import silo

    A = silo.IsiSilo("pengeringan", "PGR-1", 1000.0)
    B = silo.IsiSilo("pengeringan", "PGR-2", 1000.0)
    C = silo.IsiSilo("beli_kering", "GB-9", 1000.0)
    assert silo._tercampur([A, B]) is False
    assert silo._tercampur([A, C]) is True
    assert silo._tercampur([C]) is False


def test_isi_dibaca_sebelum_yang_baru_ditambahkan():
    """Kalau dibaca sesudahnya, gabah yang baru masuk ikut terhitung dan
    peringatannya menuduh dirinya sendiri."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.masuk_silo)
    i_baca = sumber.index("sebelum = await isi_silo")
    for tanda in ("baris = SiloStorage(", "status_batch = 'di_silo'"):
        assert i_baca < sumber.index(tanda), f"isi dibaca setelah {tanda}"


def test_kedua_arah_pencampuran_diperingatkan():
    """Lot masuk ke silo yang sudah berisi gabah beli kering SUDAH
    diperingatkan. Arah sebaliknya — gabah beli kering menyusul ke silo yang
    berisi lot — sampai sekarang diam."""
    from app.web import api
    from app.penggilingan.gudang1.services import tumpukan

    assert "campur_asal" in kode_saja(api.act_pindah_silo)
    assert "campur_asal" in kode_saja(api.act_gabah_masuk)
    assert "campur_asal" in kode_saja(tumpukan.tempatkan)


def test_peringatan_silo_bukan_penolakan():
    """Gabahnya harus keluar dari dryer. Menolak berarti memacetkan pengeringan
    berikutnya — dan kemacetan itulah yang melahirkan tumpukan di lantai."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.masuk_silo)
    # Tak satu pun penolakan di sini boleh beralasan campuran. Penolakan yang
    # ADA — lot tak ditemukan, belum selesai, kapasitas kurang — semuanya
    # tentang hal lain.
    tolakan = [b.strip() for b in sumber.splitlines() if "raise" in b]
    assert tolakan, "masuk_silo memang punya penolakan lain"
    for t in tolakan:
        assert "campur" not in t.lower(), f"campuran berujung penolakan: {t}"


def test_silo_kosong_tak_dilaporkan_sudah_berisi():
    """`digabung` pernah dihitung SESUDAH baris barunya ditambahkan. Autoflush
    menuliskannya lebih dulu, jadi silo yang kosong pun dilaporkan "sudah
    berisi sebelumnya" — dan peringatan palsu melatih orang mengabaikan
    peringatan yang sungguhan."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.masuk_silo)
    assert "digabung = await _silo_content_kg" not in sumber, \
        "isi silo tak boleh dihitung ulang setelah barisnya ditambahkan"
    # TIGA cabang sejak pesan kerja 12 (gabah kering dibongkar kembali ke
    # silo, migrasi 0077) — ketiganya harus membaca keadaan SEBELUM
    # penambahan, bukan cuma dua yang lebih lama.
    assert sumber.count("digabung = bool(sebelum)") == 3, \
        "ketiga cabang harus membaca keadaan SEBELUM penambahan"


# ──────────── Gabah yang datang saat silo sedang digiling ────────────
#
# Keputusan pemilik 6 September 2026: gilingnya TETAP jalan, bahannya yang
# bertambah. Bukan berhenti, bukan diulang, dan bukan pula diam-diam masuk.

def test_gabah_masuk_saat_giling_jadi_sumber_tambahan():
    """Kalau tidak didaftar, gabahnya tetap tergiling secara fisik sementara
    `berat_gabah_masuk_kg` tinggal di angka lama — dan rendemen proses itu
    terbaca melambung tanpa ada yang tahu sebabnya."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.masuk_silo)
    assert "MillingProcessSource" in sumber
    assert "berat_gabah_masuk_kg" in sumber
    assert "kg_baris" in sumber, "yang ditambahkan berat BARIS BARU, bukan isi silo"


def test_giling_berjalan_tidak_dihentikan_oleh_gabah_baru():
    """Menolak gabah di sini berarti menghentikan mesin yang sedang jalan."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.masuk_silo)
    # Ditambatkan pada NAMA PENANYANYA, bukan pada kueri yang tertulis di
    # tempat: sejak satu lot boleh datang dari beberapa silo (24 September
    # 2026) pertanyaan "silo ini sedang digiling?" punya satu jawaban bersama,
    # `giling_berjalan_untuk_silo` — dan `MillingProcess.status == 'proses'`
    # tak lagi tertulis di sini.
    i = sumber.index("giling_berjalan_untuk_silo")
    ekor = sumber[i:sumber.index("return MasukResult")]
    assert "raise" not in ekor, "giling berjalan tak boleh menolak gabah baru"


def test_berat_baris_bukan_berat_seluruh_silo():
    """`kg` pada cabang gabah kering berarti SELURUH isi silo sesudah
    penggabungan. Memakainya sebagai berat sumber akan menghitung ulang gabah
    yang sudah terdaftar sejak giling dimulai."""
    from app.penggilingan.gudang1.services import silo

    sumber = kode_saja(silo.masuk_silo)
    assert "kg_baris = kg_new" in sumber
    assert "kg = existing_kg + kg_new" in sumber


def test_penambahan_bahan_diberitahukan_di_ketiga_jalan():
    from app.web import api
    from app.penggilingan.gudang1.services import tumpukan

    for fn in (api.act_pindah_silo, api.act_gabah_masuk, tumpukan.tempatkan):
        assert "giling_berjalan" in kode_saja(fn), fn.__name__


def test_silo_yang_digiling_tak_muncul_lagi_sebagai_siap_digiling():
    """Bug yang sama di layar: silo yang sedang dikuras terbaca seolah menunggu
    digiling, dan penggilingannya lenyap.

    Pagar ini dulu mencari nama peubah `sibuk` dan kueri di tempat. Sejak satu
    lot boleh datang dari beberapa silo (keputusan pemilik 24 September 2026)
    pertanyaannya BERUBAH ARTI: "silo ini yang tercatat di `silo_id`?" cuma
    menyebut silo pertama, jadi silo kedua tetap berkartu "siap digiling"
    lengkap dengan tombolnya — padahal gabahnya sudah di dalam mesin. Yang
    dijaga sekarang: KETIGA tempat yang menanyakannya memakai jawaban bersama,
    dan tak satu pun kembali memercayai kolom tunggal itu.
    """
    from app.services import berjalan
    from app.penggilingan.gudang1.services import silo as svc_silo
    from app.web import api

    for fn in (berjalan.untuk_gudang1, api.silo_siap_giling, svc_silo.masuk_silo):
        sumber = kode_saja(fn)
        assert "giling_berjalan_untuk_silo" in sumber, fn.__name__
        assert "MillingProcess.silo_id ==" not in sumber, (
            f"{fn.__name__} kembali memercayai silo_id — silo kedua akan terbuka")

    sumber = kode_saja(berjalan.untuk_gudang1)
    # `rindex`: kemunculan PERTAMA namanya ada di baris impor, dan yang dijaga
    # di sini tempat ia DIPAKAI.
    i = sumber.rindex("giling_berjalan_untuk_silo")
    assert "continue" in sumber[i:i + 200], "silo yang digiling tetap berkartu"


# ──────────── Konfirmasi sebelum mesin dinyalakan ────────────

def test_mulai_pengeringan_minta_konfirmasi():
    """Satu-satunya aksi yang menyalakan MESIN — dan dua isiannya (target &
    mode) sebenarnya disetel dengan tangan di panel dryer. Yang tersimpan di
    sini cuma salinannya, dan salinan yang meleset baru ketahuan berjam-jam
    kemudian."""
    from app.web import api

    spec = _aksi(api, "mulai_pengeringan")
    k = spec.get("konfirmasi")
    assert k, "mulai pengeringan harus dikonfirmasi"
    assert "{target_kadar_air}" in k["teks"] and "{mode_dryer}" in k["teks"], \
        "konfirmasi harus MENGULANG angkanya, bukan sekadar bertanya 'yakin?'"


def test_konfirmasi_mengulang_jawaban_bukan_bertanya_yakin():
    """'Yakin?' tidak menanyakan apa pun — ia melatih orang menekan Ya."""
    from app.web import api

    k = _aksi(api, "mulai_pengeringan")["konfirmasi"]
    assert "yakin" not in k["teks"].lower()
    assert "yakin" not in k.get("ya", "").lower()


def test_konfirmasi_memakai_tulisan_pilihan_bukan_id():
    """Lubang {dryer_id} diisi dari SELECT. Kalau yang dipakai nilainya, yang
    terbaca 'Periksa panel 3' — dan angka id tidak mengonfirmasi apa pun."""
    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/aksi.js").read_text()
    i = js.index("function terbaca()")
    blok = js[i:i + 500]
    assert "el.options[el.selectedIndex].text" in blok


def test_konfirmasi_membaca_isi_sebelum_layar_diganti():
    """Layar konfirmasi menimpa borangnya. Kalau isinya baru dibaca sesudah
    ditekan Ya, yang dibaca adalah borang yang sudah tidak ada."""
    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/aksi.js").read_text()
    i_baca = js.index("var isi = muatan(), v = terbaca();")
    i_tanya = js.index("if (a.konfirmasi) { tanyaYakin(isi, v); return; }")
    assert i_baca < i_tanya


def test_kembali_tak_menghapus_isian():
    """Memeriksa ulang tidak boleh berarti mengetik ulang."""
    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/aksi.js").read_text()
    assert 'bukaAksi(id, v)' in js
    assert "function bukaAksi(id, semula)" in js


def test_ubah_target_punya_lembarnya_sendiri_dan_konfirmasi():
    """Mencatat kadar air MELAPORKAN apa yang terbaca; mengubah target
    MENETAPKAN kapan mesin dimatikan, dan itu ikut menentukan gabah ini dijual
    sebagai apa.

    Dua hal sebesar itu berbagi satu tombol Simpan berarti yang berat ikut
    tertekan bersama yang ringan — dan tak ada satu pun titik di mana orangnya
    ditanya apakah ia sungguh bermaksud menggesernya.
    """
    import inspect

    from app.web import api

    spec = inspect.getsource(api)

    # Bukan lagi medan di borang kadar air.
    kadar = spec[spec.index('"id": "kadar_air"'):spec.index('"id": "ubah_target"')]
    assert '"name": "target_baru"' not in kadar
    assert '"type": "tombol_aksi"' in kadar and '"aksi": "ubah_target"' in kadar
    # Benda yang sedang dikerjakan ikut dibawa — orangnya baru saja menjawab
    # "lot yang mana" di borang yang ia tinggalkan.
    assert '"bawa": "kode_lot"' in kadar

    # Aksinya sendiri, dan ia MENUNTUT konfirmasi.
    aksi = spec[spec.index('"id": "ubah_target"'):spec.index('"id": "selesai_pengeringan"')]
    assert '"konfirmasi"' in aksi
    # Konfirmasi mengulang ANGKA yang baru diketik, bukan bertanya "yakin?".
    # "Yakin?" tak menanyakan apa pun — ia cuma melatih orang menekan Ya.
    assert "{target}" in aksi and "{kode_lot}" in aksi


def test_tombol_aksi_digambar_di_paling_bawah():
    """Letaknya yang menyampaikan maksudnya. Di tengah borang ia terbaca
    sebagai isian yang belum diisi; di bawah tombol Simpan ia terbaca sebagai
    jalan keluar yang lain — dan memang itu."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/aksi.js").read_text()
    assert js.index('id="simpan"') < js.index("tombolLain +")
    # Dan ia tak ikut digambar sebagai medan biasa.
    assert 'if (f.type === "tombol_aksi") { return ""; }' in js


def test_pendengar_lembar_dipasang_sekali_saja():
    """`#lembar` elemen yang TETAP — yang ditukar tiap kali aksi dibuka
    hanyalah isinya. Pendengar yang dipasang di dalam `bukaAksi` menumpuk satu
    tiap kali lembar dibuka, jadi sesudah tiga kali membuka, satu ketukan
    "Tambah" menambah TIGA kotak.

    Bug itu sempat masuk pada 10 September 2026 bersama medan berulangnya
    sendiri, dan ketahuan saat diuji di peramban.
    """
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/aksi.js").read_text()
    badan = js[js.index("function bukaAksi"):js.index("  muat();")]
    assert 'addEventListener("click"' not in badan, (
        "pendengar dipasang di dalam bukaAksi — ia akan menumpuk")
    # Dipasang lewat PINDAH.pasang, karena `document` tak ikut ditukar saat
    # halaman berpindah dan pendengarnya akan menumpuk per perpindahan.
    luar = js[js.index("[data-tambah]"):]
    assert "PINDAH.pasang" in js[:js.index("[data-tambah]")][-1500:] or \
        "PINDAH.pasang" in luar[:200], "pendengar tak lewat PINDAH.pasang"
