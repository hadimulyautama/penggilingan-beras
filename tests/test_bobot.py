"""Bobot bertiga-keadaan — QA P6, 21 September 2026.

"Belum diketahui" bukan nol. Modul `bobot` menjawab "berapa bobot batch ini
SEKARANG, dan seberapa pasti" untuk semua tempat yang dulu menulis
`float(b.berat_total_kg or 0)`. Uji di sini menjaga semantiknya (murni,
tanpa basis data) dan pola sumber yang tak punya tempat lain untuk dijaga;
perilakunya di Postgres ada di tests/pg/test_bobot_belum_final.py.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.penggilingan.gudang1.services import bobot as B
from tests.bantu import kode_saja


def _b(berat, sumber, perkiraan=None):
    """Batch tiruan. `perkiraan` = `berat_perkiraan_kg` (perkiraan dari tara);
    perkiraan yang sama dengannya berasal dari tara lama, yang berbeda dari
    timbang kedua hari ini pada tiket yang belum ditutup (QA 21 Sep d)."""
    return SimpleNamespace(berat_total_kg=berat, sumber_berat=sumber, berat_perkiraan_kg=perkiraan)


def test_tiga_keadaan_dari_kolom_batch():
    assert B.dari_batch(_b(11330, "timbangan")).keadaan == B.PASTI
    assert B.dari_batch(_b(11330, "nota")).pasti
    assert B.dari_batch(_b(11330, "manual")).pasti, "diketik dari nota di tangan = pasti"
    p = B.dari_batch(_b(11330, "perkiraan"))
    assert p.keadaan == B.PERKIRAAN and p.diketahui and not p.pasti
    t = B.dari_batch(_b(None, "menunggu"))
    assert t.keadaan == B.TAK_DIKETAHUI and not t.diketahui and t.tak_diketahui == 1
    assert B.dari_batch(None).keadaan == B.TAK_DIKETAHUI


def test_teks_tak_pernah_nol_untuk_yang_belum_diketahui():
    """Angka nol untuk bobot yang belum diketahui itulah yang membuat semua
    orang mengira datanya salah (tangkapan layar pemilik: "Catur 0 kg")."""
    assert B.dari_batch(_b(11330, "timbangan")).teks() == "11.330 kg"
    assert B.dari_batch(_b(11330, "perkiraan", 11330)).teks() == "± 11.330 kg (dari tara lama)"
    # Angka dari timbang kedua hari ini bukan tebakan — tanpa "±", tetapi
    # tetap belum pasti karena tiketnya belum ditutup.
    assert B.dari_batch(_b(9950, "perkiraan", 10240)).teks() == "9.950 kg · tiket belum ditutup"
    assert B.dari_batch(_b(9950, "perkiraan", None)).teks() == "9.950 kg · tiket belum ditutup"
    assert not B.dari_batch(_b(9950, "perkiraan", 10240)).pasti
    assert B.dari_batch(_b(None, "menunggu")).teks() == "menunggu timbang"
    assert "0 kg" not in B.dari_batch(_b(None, "menunggu")).teks()
    assert B.dari_batch(_b(None, "menunggu")).angka_teks() is None


def test_jumlah_mengikuti_yang_paling_tak_pasti():
    pasti = B.dari_batch(_b(10640, "timbangan"))
    perk = B.dari_batch(_b(11330, "perkiraan"))
    tunggu = B.dari_batch(_b(None, "menunggu"))
    assert B.jumlah([pasti, pasti]).pasti
    j = B.jumlah([pasti, perk])
    assert j.keadaan == B.PERKIRAAN and j.kg == 10640 + 11330
    # Persis tangkapan layar: satu pasti + satu belum ditimbang di satu silo.
    s = B.jumlah([pasti, tunggu])
    assert s.keadaan == B.TAK_DIKETAHUI and s.kg == 10640 and s.tak_diketahui == 1
    assert s.teks() == "≥ 10.640 kg · 1 truk belum ditimbang"
    assert s.angka_teks() == "≥ 10.640"
    semua = B.jumlah([tunggu, tunggu])
    assert semua.kg is None and semua.teks() == "menunggu timbang · 2 truk"
    assert B.jumlah([]).pasti and B.jumlah([]).kg == 0.0
    assert (pasti + perk).keadaan == B.PERKIRAAN


def test_perkiraan_dan_normalisasi_nopol():
    assert B.perkiraan(17830, 6500) == 11330
    assert B.perkiraan(17830, None) is None
    assert B.perkiraan(6000, 6500) is None, "tara lebih besar dari kotor = tak masuk akal"
    # Batas kewajaran (QA 24 September 2026 (c) butir 2c): muatan 12 ton di atas
    # truk bertara 1 ton adalah kendaraan yang tak ada — taranya milik kendaraan
    # LAIN, atau salah ketik. Yang begitu tak ditebak: "menunggu timbang".
    assert B.perkiraan(13000, 1000) is None, "tara 1 ton untuk muatan 12 ton"
    assert B.perkiraan(13000, 3000) == 10000, "truk sungguhan tetap ditebak"
    # Tepat di batas masih diterima: batasnya pagar, bukan ambang ketelitian.
    assert B.perkiraan(5000, 1000) == 4000
    # Dan tak ada batas BAWAH: mobil bak bertara 1.000 kg yang membawa 1.500 kg
    # adalah kendaraan yang sungguh datang ke pabrik ini (petani kecil). Pagar
    # yang menolak angka kecil akan menolak tara yang benar — yang dijaga
    # rasionya, bukan besarnya.
    assert B.perkiraan(2500, 1000) == 1500
    # Ukuran pagarnya datang dari armada sendiri (keterangan pemilik 24 Sep
    # 2026): truk lazim 3.000 kg kosong, muatan ±10.000 kg — 3,3×, jauh di
    # bawah batas. Angka itu tak menghitung apa pun; ia yang memberi ukuran.
    assert B.perkiraan(13000, B.TARA_TRUK_LAZIM_KG) == 10000
    assert B.norm_nopol("ad 1234 xy") == "AD1234XY" == B.norm_nopol("AD-1234-XY")
    assert B.norm_nopol(None) == ""


# ─────────────── Pola sumber yang tak punya tempat lain untuk dijaga ───────────────

def test_start_milling_menulis_null_bukan_nol_dan_menandai_belum_final():
    from app.penggilingan.gudang1.services import milling

    sumber = kode_saja(milling.start_milling)
    assert "_storage_bobot" in sumber
    assert "berat_kg=bb.kg" in sumber, "NULL bila belum diketahui, bukan 0"
    assert "bobot_masuk_final=total.pasti" in sumber
    # Galat mentah Postgres tak boleh sampai ke layar (seperti R-T-01).
    assert "except IntegrityError" in sumber and "MillingError" in sumber


def test_pagar_pk_lebih_besar_dari_gabah_hanya_bila_pembandingnya_pasti():
    from app.penggilingan.gudang1.services import milling

    # `>=`, bukan `>` — rendemen tepat 100% sama mustahilnya dengan yang
    # lebih besar (keputusan pemilik 5 Oktober 2026, celah yang lolos dari
    # 1.145 uji karena tak satu pun mencoba angka tepat di batasnya).
    assert "if proc.bobot_masuk_final and masuk and berat_akhir >= masuk:" in inspect.getsource(
        milling.finish_milling)
    # Verifikasi output (rendemen final & HPP) menunggu bahan final.
    assert "_pesan_belum_final" in kode_saja(milling.verify_milling_output)


def test_pagar_pengering_memakai_batas_atas():
    from app.penggilingan.gudang1.services import drying

    for fn in (drying.masuk_dryer, drying.add_batches_to_lot):
        assert "_berat_untuk_pagar" in kode_saja(fn), fn.__name__
    sumber = kode_saja(drying._berat_untuk_pagar)
    assert "berat_kotor_tiket" in sumber
    assert "belum ditimbang kedua" in inspect.getsource(drying._berat_untuk_pagar)


# `test_rupiah_tak_pernah_berdiri_di_atas_perkiraan` DIBUANG 28 September 2026.
#
# Aturannya BENAR dan tidak dicabut — rupiah memang tak boleh berdiri di atas
# bobot perkiraan. Yang hilang subjeknya: kedua penulis harga (`verify_gabah_
# price`, `verify_pk_price`) dihapus bersama seluruh harga, atas keputusan
# pemilik. Aturan itu kini milik keuangan, dan pagarnya harus berdiri di sana.
#
# Yang TETAP dijaga di berkas ini seluruh jalur BOBOT-nya: perkiraan tak pernah
# dipakai sebagai angka pasti, poller menggantinya, dan pagar dryer menolaknya.


def test_poller_mengganti_perkiraan_lewat_jalur_menunggu():
    from app.penggilingan.gudang1.services import timbang_link

    assert "b.sumber_berat IN ('menunggu', 'perkiraan')" in timbang_link._SQL_SINKRON
    # Perkiraan hanya untuk yang belum punya angka sungguhan, dan positif.
    assert "IS NULL" in timbang_link._SQL_PERKIRAAN
    assert "t.timbang1_kg - k.berat_kosong_kg > 0" in timbang_link._SQL_PERKIRAAN
    # `berat_perkiraan_kg` TIDAK disentuh saat netto datang — selisihnya
    # itulah yang menguji anggapan "tara stabil".
    sql = "\n".join(l for l in timbang_link._SQL_SINKRON.splitlines()
                    if not l.strip().startswith("--"))
    assert "berat_perkiraan_kg" not in sql


def test_rekonsiliasi_punya_tiga_butir_baru():
    from app.penggilingan.gudang1.services import rekonsiliasi as r

    sumber = inspect.getsource(r.rekonsiliasi)
    for kunci in ("perkiraan", "perkiraan_meleset", "giling_belum_final"):
        assert f'"{kunci}":' in sumber, kunci
    assert r.AMBANG_PERKIRAAN_PERSEN == 2.0
    fmt = inspect.getsource(r.format_rekonsiliasi)
    assert "PERKIRAAN MELESET" in fmt and "BELUM FINAL" in fmt
    # "Bersih" tak boleh diucapkan selama salah satu dari ketiganya berisi.
    assert "not perk and not meleset and not gbf" in fmt


def test_rute_giling_dan_pk_menangkap_galat_mentah():
    from app.web import api

    sumber = inspect.getsource(api)
    awal = sumber.index('@router.post("/actions/mulai-giling")')
    assert "except IntegrityError" in sumber[awal:awal + 2500]
    awal = sumber.index('@router.post("/actions/masukkan-pk")')
    assert "except IntegrityError" in sumber[awal:awal + 2500]


def test_layar_tak_lagi_menulis_nol_untuk_bobot_batch():
    """Kartu batch, PK luar, dan verifikasi memakai `dari_batch(...).teks()`;
    `_kg(x.berat_total_kg)` — yang menulis "0 kg" untuk NULL — tak tersisa."""
    from app.services import berjalan

    sumber = inspect.getsource(berjalan)
    assert "_kg(b_.berat_total_kg)" not in sumber
    assert "_kg(pk.berat_total_kg)" not in sumber
    assert "_kg(batch.berat_total_kg)" not in sumber
    assert "def _utama(" in sumber


def test_korban_lama_p6_03_disebut_bukan_dibetulkan_otomatis():
    """QA pra-deploy P6: giling selesai yang bobot masuknya tak cocok dengan
    bahannya sekarang tampak sama dari data dengan revisi tiket yang sengaja.
    Maka: rekonsiliasi menyebutnya (⑪), poller TIDAK menyentuhnya (hanya yang
    bertanda belum final), dan admin membetulkannya per proses — tercatat
    bertag supaya pembatalannya tak jatuh ke `_undo_finish_milling`."""
    from app.penggilingan.gudang1.services import koreksi_bobot as k
    from app.penggilingan.gudang1.services import milling, rekonsiliasi as r
    from app.services import undo

    assert '"giling_tak_cocok":' in inspect.getsource(r.rekonsiliasi)
    assert "not tc" in inspect.getsource(r.format_rekonsiliasi)
    assert "m.bobot_masuk_final = true" in k._SQL_TAK_COCOK.text
    assert "MillingProcess.bobot_masuk_final.is_(False)" in kode_saja(milling.resinkron_bahan_berjalan)
    assert "resinkron_bahan_berjalan" in kode_saja(k.betulkan_bobot_masuk), "jalur poller yang sama"
    assert "aksi=TAG_BETULKAN" in kode_saja(k.betulkan_bobot_masuk)
    assert undo._PENANGAN_TAG.get("betulkan_bobot") == "_undo_betulkan_bobot"
    assert 'tag == "betulkan_bobot"' in inspect.getsource(undo._undo_one)


def test_timbang_kedua_sementara_menimpa_tebakan_tara():
    """QA 21 Sep (d): "Simpan sementara" di Pos Timbang menyimpan timbang2
    tanpa menghitung netto dan tiketnya tetap TERBUKA. Poller memakai angka
    timbangan hari itu (bermuatan − kosong, rumus netto Pos Timbang sendiri)
    untuk batch 'menunggu' MAUPUN 'perkiraan' — hanya tiket DUA KALI barang
    masuk — dan TIDAK menimpa `berat_perkiraan_kg` (penguji "tara stabil")."""
    from app.penggilingan.gudang1.services import timbang_link as t

    sql = "\n".join(l for l in t._SQL_PERKIRAAN_TIKET.splitlines() if not l.strip().startswith("--"))
    assert "b.sumber_berat IN ('menunggu', 'perkiraan')" in sql
    assert "t.status_tiket = 'TERBUKA'" in sql
    assert "t.cara_timbang = 'DUA_KALI'" in sql
    assert "t.arah IN ('MASUK', 'TRANSFER', 'RETUR_MASUK')" in sql
    assert "berat_total_kg = t.timbang1_kg - t.timbang2_kg" in sql
    assert "berat_perkiraan_kg" not in sql, "perkiraan dari tara tak ditimpa"
    assert "IS DISTINCT FROM" in sql, "idempoten tiap tiga menit"
    sumber = kode_saja(t.sinkron_perkiraan)
    assert sumber.index("_sql_bobot_batch(_SQL_PERKIRAAN, tbl)") < sumber.index("_sql_bobot_batch(_SQL_PERKIRAAN_TIKET, tbl)"), \
        "angka timbangan hari ini menang atas tebakan tara"
