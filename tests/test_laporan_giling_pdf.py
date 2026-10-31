from datetime import datetime, timedelta, timezone
from io import BytesIO

from pypdf import PdfReader

from app.web.layar_riwayat import _pdf_laporan_giling


def test_pdf_giling_memuat_asal_qc_hasil_transfer_dan_durasi():
    mulai = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
    selesai = datetime(2026, 10, 12, 5, 30, tzinfo=timezone.utc)
    pendinginan_selesai = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
    data = {
        "kode": "LOT-20261012-01", "owner": "Pabrik", "class": "MIX",
        "composition": "Gabah kering langsung + gabah hasil pengeringan",
        "input_kg": 10_000, "output_kg": 6_500, "yield": 65,
        "qc_summary": "KA 14,2% · Broken 2,5% · Susut 1,0%", "qc_moisture_avg": "14,2%",
        "qc_broken_avg": "2,5%", "qc_loss_avg": "1,0%",
        "transferred_kg": 5_000, "available_kg": 1_500,
        "sources": [
            {"silo": "Silo A", "source": "Gabah kering langsung",
             "weight": 5_000, "used": 5_000, "remaining": 0},
            {"silo": "Silo B", "source": "PGR-20261011-01 · gabah basah dikeringkan",
             "weight": 5_000, "used": 5_000, "remaining": 0},
        ],
        "batches": [
            {"code": "GB-20261010-01", "origin": "Supplier Kering",
             "plate": "AB 1234 CD", "condition": "Kering", "weight": 5_000},
            {"code": "GB-20261010-02", "origin": "Widiyanto",
             "plate": "B 5678 EF", "condition": "Basah", "weight": 5_000},
        ],
        "raw_qc": [
            {"batch": f"GB-20261010-01 · QC {i + 1}", "time": mulai + timedelta(minutes=i),
             "moisture": moisture, "lamur": "—", "green": "sedang", "density": "Padat"}
            for i, moisture in enumerate(("14% / 14,5%", "14,2% / 14,4%", "14,1% / 14,3%",
                                          "13,9% / 14,2%", "14% / 14,4%"))
        ] + [
            {"batch": f"GB-20261010-02 · QC {i + 1}", "time": mulai + timedelta(minutes=i),
             "moisture": moisture, "lamur": f"Ya · {sacks} sak",
             "green": "sedang", "density": "Empuk"}
            for i, (moisture, sacks) in enumerate((
                ("25,5% / 26%", 5), ("25% / 26%", 6), ("24,5% / 25%", 4),
                ("25,3% / 25,8%", 5), ("25,2% / 25,7%", 3)))
        ],
        "drying_lots": [{"code": "PGR-20261011-01", "batches": "GB-20261010-02",
                         "dry_start": mulai, "dry_end": selesai,
                         "cool_start": selesai, "cool_end": pendinginan_selesai}],
        "drying_moisture": [{"lot": "PGR-20261011-01", "time": selesai,
                             "samples": "15% · 14,5% · 14% · 14,5%",
                             "average": "14,50%", "machine": "15%"}],
        "qc": [
            {"time": selesai - timedelta(minutes=20), "moisture": "14%", "broken": "2,4%",
             "loss": "0,8%", "condition": "CAMPUR"},
            {"time": selesai - timedelta(minutes=10), "moisture": "14,2%", "broken": "2,5%",
             "loss": "1%", "condition": "CAMPUR"},
            {"time": selesai, "moisture": "14,4%", "broken": "2,6%",
             "loss": "1,2%", "condition": "CAMPUR"},
        ],
        "progress": [{"time": selesai, "weight": 6_500}],
        "transfers": [{"code": "TRF-20261012-01", "time": selesai,
                       "destination": "Tumpukan", "weight": 5_000}],
        "start": mulai, "end": selesai, "verified_at": selesai,
        "verified_weight": 6_500,
    }

    pdf = _pdf_laporan_giling(data)
    assert len(data["raw_qc"]) == 10
    assert len(data["qc"]) == 3
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    for expected in ("LOT-20261012-01", "Silo A", "Widiyanto", "AB 1234 CD",
                     "QC bahan sebelum digiling", "25,5% / 26%", "QC hasil PK",
                     "Gabah kering langsung + gabah hasil pengeringan",
                     "HASIL PK", "6.500 kg", "65,0%",
                     "Gabah kering langsung", "PGR-20261011-01", "Riwayat pengeringan bahan",
                     "B 5678 EF", "14,50%", "Ya · 5 sak",
                     "14%", "Rata-rata QC", "KA 14,2% · Broken 2,5% · Susut 1,0%",
                     "Catatan hasil PK", "TRF-20261012-01", "4 jam 30 menit"):
        assert expected in text
    assert text.index("KA 14,2%") < text.index("Broken 2,5%") < text.index("Susut 1,0%")
    assert text.count("GB-20261010-01") >= 2
    assert text.count("GB-20261010-02") >= 2
