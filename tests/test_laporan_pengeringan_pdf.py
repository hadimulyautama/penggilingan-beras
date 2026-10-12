from datetime import datetime, timezone

from pypdf import PdfReader
from io import BytesIO

from app.web.layar_riwayat import _pdf_pengeringan


def test_pdf_pengeringan_memuat_asal_qc_pemantauan_dan_durasi():
    awal = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    payload = {
        "kode": "PGR-20261012-01",
        "owner": "Pabrik",
        "dryer": "Pengering 1 / 15T",
        "weight": 10_000,
        "target": 14,
        "silo": "Silo A",
        "batches": [{"kode": "GB-20261012-01", "asal": "Widiyanto",
                     "plat": "AB 1234 CD", "weight": 10_000}],
        "qc": [{"batch": "GB-20261012-01 · QC 1", "time": awal,
                "moisture": "25,5% / 26%", "lamur": "Ya · 5 sak",
                "green": "sedang", "density": "Empuk"}],
        "moisture": [{"time": awal, "samples": "19% · 18,5% · 18% · 18,5%",
                      "average": "18,50%", "machine": "19%", "speed": "—"},
                     {"time": datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc),
                      "samples": "16% · 15,5% · 15% · 15,5%", "average": "15,50%",
                      "machine": "16%", "speed": "1,50%/jam"}],
        "dry_start": awal,
        "dry_end": datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
        "cool_start": datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
        "cool_end": datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc),
        "cooling_notes": ["12/10/2026 15:00 WIB: Pendinginan selesai"],
    }

    pdf = _pdf_pengeringan(payload)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    for expected in ("PGR-20261012-01", "Widiyanto", "AB 1234 CD", "Riwayat QC bahan baku",
                     "25,5% / 26%", "Ya · 5 sak", "18,5%", "1,50%/jam",
                     "Pengeringan", "Pendinginan", "8 jam", "Catatan pendinginan"):
        assert expected in text
