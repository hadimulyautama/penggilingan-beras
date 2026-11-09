from datetime import datetime, timedelta, timezone
from io import BytesIO

from pypdf import PdfReader

from app.web.layar_riwayat import _pdf_laporan_giling


def data_giling():
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

    return data


def test_pdf_giling_memuat_ringkasan_dan_lampiran():
    data = data_giling()
    pdf = _pdf_laporan_giling(data)
    assert len(data["raw_qc"]) == 10
    assert len(data["qc"]) == 3
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    for expected in ('LOT-20261012-01','Widiyanto','QC hasil PK','HASIL PK','6.500 kg','65,0%',
                     'PGR-20261011-01','14,50%','Rata-rata QC','KA 14,2% · Broken 2,5% · Susut 1,0%',
                     'Pencatatan hasil PK','TRF-20261012-01','4 jam 30 menit'):
        assert expected in text
    pdf = PdfReader(BytesIO(pdf))
    assert len(pdf.pages) == 2
    first, details = [page.extract_text() for page in pdf.pages]
    assert 'Asal bahan dan QC penerimaan' in first
    assert 'Rata-rata QC' in first and 'QC hasil PK' not in first
    assert 'Pencatatan hasil PK' in details and 'QC hasil PK' in details
    assert details.index('Pengeringan sumber bahan') < details.index('Transfer dan sisa PK')
    assert 'AB 1234 CD' in text  # pelacakan asal tetap tersedia pada baris sumber
    for removed in ('Sopir','Nomor polisi','Densiti','Bahan masuk dan pemakaian silo'):
        assert removed not in text
    assert 'Kesimpulan:' not in text and 'MELEBIHI SATU HALAMAN' not in text


import pytest

@pytest.mark.parametrize('count', [0, 1, 2, 9])
def test_hasil_kumulatif_diringkas_tanpa_menjumlahkan(count):
    data = data_giling()
    data['progress'] = [dict(time=data['start']+timedelta(minutes=i), weight=2500*(i+1),actor='Petugas '+str(i%2)) for i in range(count)]
    pdf = PdfReader(BytesIO(_pdf_laporan_giling(data)))
    text = pdf.pages[1].extract_text()
    if count:
        assert 'Catatan terakhir' in text
        assert f'{count} pencatatan; angka kumulatif tidak dijumlahkan' in text
        assert f'{2500*count:,}'.replace(',', '.')+' kg' in text
    else:
        assert 'Belum ada catatan' in text and 'Catatan terakhir' not in text
    if count > 1:
        assert 'Petugas 0, Petugas 1' in text
        assert str(count-1)+' pencatatan' in text


def test_mutu_ringkasan_mengikuti_layanan_dan_izin():
    from types import SimpleNamespace
    from app.services.mutu_pk import penilaian_dari_log
    data = data_giling()
    data['qc_rating'] = penilaian_dari_log([SimpleNamespace(kadar_air=14.8, broken_persen=28, susut_persen=14, butir_kuning='bersih', gabah='bersih', merang='bersih')])
    data['qc'][0]['note'] = '<b>Catatan lengkap & asli</b>'
    first = PdfReader(BytesIO(_pdf_laporan_giling(data))).pages[0].extract_text()
    assert '90,00 / 100 (B1)' in first
    data['show_quality'] = False
    pdf = PdfReader(BytesIO(_pdf_laporan_giling(data)))
    assert '90,00 / 100 (B1)' not in '\n'.join(p.extract_text() for p in pdf.pages)
    assert '<b>Catatan lengkap & asli</b>' in pdf.pages[1].extract_text()
    data['qc'] *= 14
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(_pdf_laporan_giling(data))).pages)
    assert text.count('<b>Catatan lengkap & asli</b>') == 14


def test_qc_kategori_berbeda_tetap_tampil_per_putaran():
    data = data_giling()
    data['qc'][0].update(yellow='Parah', paddy='Sedikit', chaff='Banyak')
    data['qc'][1].update(yellow='Bersih', paddy='Sedang', chaff='Bersih')
    text = PdfReader(BytesIO(_pdf_laporan_giling(data))).pages[1].extract_text()
    for value in ('Parah', 'Sedikit', 'Banyak', 'Sedang'):
        assert value in text
    assert 'Semua pemeriksaan:' not in text


def test_qc_penerimaan_memakai_agregat_asli_dan_distribusi():
    from app.web.pdf_giling import ringkasan_penerimaan
    data = data_giling()
    code=data['batches'][0]['code']
    data['raw_summary']={code:dict(air=27.33,n=10,sak=29,legacy=False)}
    data['raw_qc'][0]['green']='sedikit'
    rows=ringkasan_penerimaan(data)
    assert rows[0][2:4] == ['27,33%', '29 sak']
    assert 'Sedikit 1/5' in rows[0][4] and 'Sedang 4/5' in rows[0][4]
    assert rows[1][2:4] == ['Belum tersedia', 'Belum dicatat']
    data['raw_summary'][code]['legacy']=True
    assert ringkasan_penerimaan(data)[0][4]=='Historis: sedikit'
