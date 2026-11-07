from datetime import datetime, timezone

from pypdf import PdfReader
from io import BytesIO

from app.web.layar_riwayat import _pdf_pengeringan


def data_pengeringan():
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
        "jeda": {"kalender": "9 jam", "tertahan": "0 detik", "efektif": "9 jam", "items": []},
        "cooling_notes": ["12/10/2026 15:00 WIB: Pendinginan selesai"],
    }

    return payload


def test_pdf_pengeringan_memuat_ringkasan_dan_lampiran():
    payload=data_pengeringan()
    pdf = _pdf_pengeringan(payload)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    for expected in ("PGR-20261012-01", "Widiyanto", "AB 1234 CD", "Riwayat QC bahan baku",
                     "25,5% / 26%", "Ya · 5 sak", "18,5%",
                     "Pengeringan", "Pendinginan", "8 jam", "Catatan pendinginan"):
        assert expected in text


    pdf=PdfReader(BytesIO(pdf))
    assert len(pdf.pages)==3
    first,details,source=[page.extract_text() for page in pdf.pages]
    assert 'Ringkasan hasil' in first and '18,50%' in first and '15,50%' in first
    assert 'Pemantauan kadar air selama proses' in details
    assert 'Durasi dan riwayat jeda' in details and 'Catatan pendinginan' in details
    assert 'Riwayat QC bahan baku' in source


def test_bacaan_mesin_saja_tidak_menghapus_ka_tes_akhir():
    from datetime import timedelta
    payload=data_pengeringan()
    payload['moisture'].append(dict(time=payload['cool_end']+timedelta(minutes=1),samples='Tidak tersedia',average='—',machine='14%',speed='—'))
    first=' '.join(PdfReader(BytesIO(_pdf_pengeringan(payload))).pages[0].extract_text().split())
    assert '15,50%' in first and '14%' in first
    payload['moisture']=[]
    first=' '.join(PdfReader(BytesIO(_pdf_pengeringan(payload))).pages[0].extract_text().split())
    assert 'Belum ada pembacaan' in first


def test_bobot_terukur_dan_estimasi_tetap_terpisah():
    payload=data_pengeringan()
    payload['bobot_pengeringan']=dict(basah='10.000,00 kg',kering='9.000,00 kg',terukur='8.990,00 kg',awal='19%',akhir='14%',timbang_waktu='2026-10-12T10:00:00+07:00',timbang_petugas='Petugas Uji')
    first=' '.join(PdfReader(BytesIO(_pdf_pengeringan(payload))).pages[0].extract_text().split())
    assert '9.000,00 kg' in first and '8.990,00 kg' in first
    assert 'bukan hasil timbang' in first and 'Petugas Uji' in first
