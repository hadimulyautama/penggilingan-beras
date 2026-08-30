"""Uji logika kontrol modul Timbangan.

Tiga contoh resmi diuji apa adanya — bila salah satu berubah, rumusnya bergeser
dari dokumen dan uji ini yang menahannya:

  1. SOP Internal Kontrol Pembelian Gabah, butir 5
  2. Spesifikasi Direksi (contoh Anton, 23 Agustus 2026)
  3. Sistem Tara & Pembelian Beras PK, butir 6
"""
from __future__ import annotations

from datetime import date

import pytest

from app.timbangan import logic as L


def jenis(kode: str) -> L.AturanJenis:
    return L.JENIS_PETA[kode]


def baris(kode: str, karung: int, tara: float, acuan: float) -> L.BarisMuatan:
    return L.BarisMuatan(
        jenis_kode=kode, jumlah_karung=karung,
        tara_per_karung_kg=tara, berat_acuan_kg=acuan,
    )


# ─────────────────── Tiga contoh resmi ───────────────────

def test_contoh_sop_gabah():
    """SOP butir 5: hasil timbang 20.220, 800 karung, nota 20.000 → wajar.

    Contoh ini memakai muatan 20 ton; truk bermuatannya 26,4 ton, jadi TIDAK
    dapat ditimbang di jembatan 20 ton milik perusahaan. Rumusnya tetap diuji
    apa adanya dengan kapasitas yang lebih besar — lihat pula
    `test_contoh_sop_melebihi_kapasitas_perusahaan`.
    """
    h = L.hitung(
        aturan=jenis("GABAH_BASAH"),
        berat_bermuatan_kg=26_420, berat_kosong_kg=6_200,
        muatan=[baris("GABAH_BASAH", 800, 0.25, 20_000)],
        kapasitas_kg=30_000,
    )
    assert h.netto_timbangan_kg == 20_220
    assert h.total_tara_kg == 200
    assert h.berat_barang_kg == 20_020
    assert h.selisih_kg == 20
    assert h.status == L.NORMAL


def test_contoh_spesifikasi_direksi():
    """Contoh Anton: netto kontrol 10.000, selisih −48 → perlu pemeriksaan."""
    h = L.hitung(
        aturan=jenis("GABAH_BASAH"),
        berat_bermuatan_kg=13_600, berat_kosong_kg=3_570,
        muatan=[baris("GABAH_BASAH", 120, 0.25, 10_048)],
    )
    assert h.netto_timbangan_kg == 10_030
    assert h.total_tara_kg == 30
    assert h.berat_barang_kg == 10_000
    assert h.selisih_kg == -48
    assert round(h.selisih_persen, 2) == -0.48
    assert h.status == L.PERLU_PEMERIKSAAN
    assert h.wajib_diperiksa


def test_contoh_sistem_tara_pk():
    """Sistem Tara butir 6, disetel ke kapasitas jembatan 20 ton."""
    h = L.hitung(
        aturan=jenis("BERAS_PK"),
        berat_bermuatan_kg=19_400, berat_kosong_kg=5_400,
        muatan=[baris("BERAS_PK", 200, 0.085, 13_990)],
    )
    assert h.netto_timbangan_kg == 14_000
    assert h.total_tara_kg == 17
    assert h.berat_barang_kg == 13_983
    assert h.selisih_kg == -7
    assert h.batas_bawah_kg == -10          # 200 karung × 0,05
    assert h.status == L.NORMAL


def test_contoh_sop_melebihi_kapasitas_perusahaan():
    """Temuan: contoh pada SOP resmi tidak mungkin terjadi di pos ini.

    Muatan 20 ton + tara truk ~6 ton = 26,4 ton, sedangkan jembatan timbang
    perusahaan hanya 20 ton. Angka pada SOP bersifat ilustrasi rumus, bukan
    transaksi yang pernah atau dapat ditimbang di sini.
    """
    with pytest.raises(L.ValidasiError, match="kapasitas jembatan"):
        L.hitung(
            aturan=jenis("GABAH_BASAH"),
            berat_bermuatan_kg=26_420, berat_kosong_kg=6_200,
            muatan=[baris("GABAH_BASAH", 800, 0.25, 20_000)],
        )


# ─────────────────── Ambang proporsional (gabah basah) ───────────────────

@pytest.mark.parametrize("nota, selisih_diminta, status", [
    (10_000, -18, L.NORMAL),               # batas ±20
    (10_000, -48, L.PERLU_PEMERIKSAAN),
    (10_000, -60, L.INVESTIGASI),          # batas investigasi 50
    (13_000, -24, L.NORMAL),               # batas ±26
    (8_000, -18, L.PERLU_PEMERIKSAAN),     # batas ±16
    (12_000, +20, L.NORMAL),               # simetris: kelebihan ikut dinilai
    (12_000, +30, L.PERLU_PEMERIKSAAN),    # batas ±24
])
def test_gabah_basah_ambang_ikut_bobot(nota, selisih_diminta, status):
    karung = 100
    tara = karung * 0.25
    barang = nota + selisih_diminta
    h = L.hitung(
        aturan=jenis("GABAH_BASAH"),
        berat_bermuatan_kg=barang + tara + 5_000, berat_kosong_kg=5_000,
        muatan=[baris("GABAH_BASAH", karung, 0.25, nota)],
    )
    assert h.selisih_kg == selisih_diminta
    assert h.status == status


# ─────────────────── Gabah kering: kurang saja ───────────────────

@pytest.mark.parametrize("nota, selisih_diminta, status", [
    (10_000, -4, L.NORMAL),                # batas kurang 5
    (10_000, -6, L.PERLU_PEMERIKSAAN),
    (10_000, +40, L.NORMAL),               # kelebihan diperbolehkan
    (14_000, -6, L.NORMAL),                # batas kurang 7
    (14_000, -8, L.PERLU_PEMERIKSAAN),
])
def test_gabah_kering_hanya_kekurangan(nota, selisih_diminta, status):
    karung = 100
    tara = karung * 0.25
    barang = nota + selisih_diminta
    h = L.hitung(
        aturan=jenis("GABAH_KERING"),
        berat_bermuatan_kg=barang + tara + 4_000, berat_kosong_kg=4_000,
        muatan=[baris("GABAH_KERING", karung, 0.25, nota)],
    )
    assert h.selisih_kg == selisih_diminta
    assert h.status == status
    assert h.batas_atas_kg is None          # tidak dibatasi di sisi lebih


# ─────────────────── Barang keluar: kurang tidak boleh ───────────────────

@pytest.mark.parametrize("bruto, status", [
    (18_200, L.KURANG),        # barang 11.988 < surat jalan 12.000
    (18_212, L.NORMAL),        # pas
    (18_220, L.NORMAL),        # +8, batas +16,8
    (18_228, L.NORMAL),        # +16
    (18_240, L.KELEBIHAN),     # +28
])
def test_pengiriman_kurang_tidak_boleh(bruto, status):
    h = L.hitung(
        aturan=jenis("BEKATUL"),
        berat_bermuatan_kg=bruto, berat_kosong_kg=6_200,
        muatan=[baris("BEKATUL", 240, 0.05, 12_000)],
    )
    assert h.status == status
    assert h.batas_bawah_kg == 0            # tidak ada toleransi kurang
    assert h.batas_atas_kg == pytest.approx(16.8)


def test_pengiriman_beberapa_komoditas():
    """Satu netto, tara per baris, kontrol di tingkat total."""
    h = L.hitung(
        aturan=jenis("BERAS"),
        berat_bermuatan_kg=18_200, berat_kosong_kg=6_200,
        muatan=[
            baris("BERAS", 120, 0.05, 7_000),
            baris("BEKATUL", 80, 0.05, 3_000),
            baris("MENIR", 40, 0.05, 1_980),
        ],
    )
    assert h.netto_timbangan_kg == 12_000
    assert h.jumlah_karung == 240
    assert h.total_tara_kg == 12
    assert h.berat_barang_kg == 11_988
    assert h.berat_acuan_kg == 11_980
    assert h.selisih_kg == 8
    assert h.batas_atas_kg == pytest.approx(16.8)
    assert h.status == L.NORMAL


# ─────────────────── Jasa timbang ───────────────────

def test_jasa_timbang_sekali():
    """Sekali timbang: tidak ada pembanding, tidak ada status kontrol."""
    h = L.hitung(
        aturan=jenis("BEBAS"),
        berat_bermuatan_kg=12_850, berat_kosong_kg=None,
        muatan=[], tara_lain_kg=0,
    )
    assert h.netto_timbangan_kg == 12_850
    assert h.berat_barang_kg == 12_850
    assert h.status == L.TANPA_KONTROL
    assert not h.wajib_diperiksa


def test_jasa_timbang_dua_kali_dengan_tara_manual():
    h = L.hitung(
        aturan=jenis("BEBAS"),
        berat_bermuatan_kg=12_850, berat_kosong_kg=4_430,
        muatan=[], tara_lain_kg=20,
    )
    assert h.netto_timbangan_kg == 8_420
    assert h.berat_barang_kg == 8_400
    assert h.status == L.TANPA_KONTROL


# ─────────────────── Penjaga angka mustahil ───────────────────

def test_tolak_melebihi_kapasitas_jembatan():
    with pytest.raises(L.ValidasiError, match="kapasitas jembatan"):
        L.hitung(aturan=jenis("GABAH_BASAH"), berat_bermuatan_kg=23_400,
                 berat_kosong_kg=6_000,
                 muatan=[baris("GABAH_BASAH", 10, 0.25, 15_000)])


def test_tolak_kosong_lebih_berat():
    with pytest.raises(L.ValidasiError, match="lebih kecil"):
        L.hitung(aturan=jenis("GABAH_BASAH"), berat_bermuatan_kg=8_000,
                 berat_kosong_kg=9_000,
                 muatan=[baris("GABAH_BASAH", 10, 0.25, 5_000)])


def test_tolak_tara_melebihi_netto():
    with pytest.raises(L.ValidasiError, match="Tara lebih besar"):
        L.hitung(aturan=jenis("GABAH_BASAH"), berat_bermuatan_kg=6_100,
                 berat_kosong_kg=6_000,
                 muatan=[baris("GABAH_BASAH", 1_000, 0.25, 100)])


def test_catatan_tera_hanya_untuk_bukan_kelipatan_sepuluh():
    assert L.catatan_tera(13_600) is None
    assert L.catatan_tera(3_575) is not None


# ─────────────────── Tara bawaan sebelum sampling ───────────────────

def test_tara_bawaan_dipakai_sebelum_sampling():
    assert jenis("BERAS_PK").tara_default() == 0.1     # bawaan
    assert jenis("GABAH_BASAH").tara_default() == 0.25  # tetap
    assert jenis("BEBAS").tara_default() == 0           # manual


# ─────────────────── Deteksi pola ───────────────────

def ringkas(selisih: float, hari: int, batas: float = 20.0,
            nopol: str = "B 1234 XYZ") -> L.TransaksiRingkas:
    return L.TransaksiRingkas(
        tanggal=date(2026, 8, hari), selisih_kg=selisih,
        selisih_persen=selisih / 10_000 * 100, batas_kg=batas,
        berat_barang_kg=10_000, berat_acuan_kg=10_000 - selisih,
        nomor_polisi=nopol, pihak_nama="Anton",
    )


def test_pola_selisih_negatif_berulang():
    """Contoh Anton: −48, −40, −35, −42, −38 → pola harus terdeteksi."""
    data = [ringkas(s, h) for s, h in
            zip((-48, -40, -35, -42, -38), (3, 8, 14, 19, 23))]
    kode = {p.kode for p in L.deteksi_pola(data)}
    assert "POLA_SELISIH_NEGATIF_BERULANG" in kode
    assert "SERING_MELEWATI_BATAS" in kode


def test_pola_tidak_muncul_pada_selisih_wajar():
    data = [ringkas(s, h) for s, h in
            zip((-5, 3, -8, 6, -2), (3, 8, 14, 19, 23))]
    assert L.deteksi_pola(data) == []


def test_pola_butuh_minimal_tiga_transaksi():
    assert L.deteksi_pola([ringkas(-48, 3), ringkas(-40, 8)]) == []


# ─────────────────── Skor pihak ───────────────────

def test_skor_rendah_pada_selisih_berulang():
    data = [ringkas(s, h) for s, h in
            zip((-48, -40, -35, -42, -38), (3, 8, 14, 19, 23))]
    skor = L.hitung_skor_pihak(data)
    assert skor is not None
    assert skor.melewati_batas == 5
    assert skor.kategori == "D"
    assert skor.data_cukup


def test_skor_tinggi_pada_selisih_wajar():
    data = [ringkas(s, h) for s, h in
            zip((-5, 3, -8, 6, -2), (3, 8, 14, 19, 23))]
    skor = L.hitung_skor_pihak(data)
    assert skor is not None
    assert skor.melewati_batas == 0
    assert skor.kategori in ("A", "B")


def test_bobot_skor_berjumlah_seratus_persen():
    assert round(sum(L.BOBOT_SKOR.values()), 6) == 1.0


def test_skor_tidak_menghakimi_data_tipis():
    skor = L.hitung_skor_pihak([ringkas(-48, 3)])
    assert skor is not None
    assert not skor.data_cukup


# ─────────────────── Lingkup: tidak ada harga ───────────────────

def test_tidak_ada_harga_di_hasil():
    h = L.hitung(
        aturan=jenis("GABAH_BASAH"),
        berat_bermuatan_kg=13_600, berat_kosong_kg=3_570,
        muatan=[baris("GABAH_BASAH", 120, 0.25, 10_048)],
    )
    kolom = " ".join(h.as_dict().keys()).lower()
    for kata in ("harga", "nilai", "rupiah", "biaya", "potongan", "refaksi"):
        assert kata not in kolom
