"""Tes formatter rekonsiliasi (murni)."""
from app.penggilingan.gudang1.services.rekonsiliasi import format_rekonsiliasi


def test_bersih():
    out = format_rekonsiliasi({"belum_tertaut": [], "selisih": [], "menunggu": [], "jumlah_manual": 0})
    assert "Bersih" in out


def test_isi_dan_rupiah():
    d = {
        "belum_tertaut": [{"kode": "TRX-1", "nama": "Pak A", "jenis_kode": "GABAH_KERING",
                           "berat_acuan_kg": 5000, "netto_timbangan_kg": 4900}],
        "selisih": [{"kode_batch": "GB-1", "nama": "Pak A", "nota": 5000, "timbang": 4800,
                     "selisih_kg": 200, "selisih_persen": 4.0, "harga": 6000}],
        "menunggu": [{"kode_batch": "GB-2"}],
        "jumlah_manual": 2,
    }
    out = format_rekonsiliasi(d)
    assert "TRX-1" in out and "GB-1" in out
    assert "selisih 200 kg" in out and "Rp 1.200.000" in out  # 200 × 6000
    assert "GB-2" in out and "manual (tanpa timbang): 2" in out
