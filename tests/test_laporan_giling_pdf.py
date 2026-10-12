from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader

from app.web.layar_riwayat import _pdf_laporan_giling


def test_pdf_giling_memuat_asal_qc_hasil_transfer_dan_durasi():
    mulai = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
    selesai = datetime(2026, 10, 12, 5, 30, tzinfo=timezone.utc)
    data = {
        "kode": "LOT-20261012-01", "owner": "Pabrik", "class": "KERING",
        "input_kg": 10_000, "output_kg": 6_500, "yield": 65,
        "qc_summary": "KA 14,2%", "transferred_kg": 5_000, "available_kg": 1_500,
        "sources": [{"silo": "Silo A", "source": "PGR-20261011-01",
                     "weight": 10_000, "used": 10_000, "remaining": 0}],
        "batches": [{"code": "GB-20261010-01", "origin": "Widiyanto",
                     "plate": "AB 1234 CD", "condition": "Kering", "weight": 10_000}],
        "raw_qc": [{"batch": "GB-20261010-01 · QC 1", "time": mulai,
                    "moisture": "25,5% / 26%", "lamur": "—",
                    "green": "sedang", "density": "Empuk"}],
        "qc": [{"time": selesai, "moisture": "14%", "broken": "2,5%",
                "loss": "1%", "condition": "KERING"}],
        "progress": [{"time": selesai, "weight": 6_500}],
        "transfers": [{"code": "TRF-20261012-01", "time": selesai,
                       "destination": "Tumpukan", "weight": 5_000}],
        "start": mulai, "end": selesai, "verified_at": selesai,
        "verified_weight": 6_500,
    }

    pdf = _pdf_laporan_giling(data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    for expected in ("LOT-20261012-01", "Silo A", "Widiyanto", "AB 1234 CD",
                     "QC bahan baku", "25,5% / 26%", "QC hasil penggilingan",
                     "14%", "Catatan hasil PK", "TRF-20261012-01", "4 jam 30 menit"):
        assert expected in text
