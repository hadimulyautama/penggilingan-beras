from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from app.services.laporan_periode import TAHAP, kueri, susun
from app.web.laporan import _rentang
D = date(2026, 11, 11)

def test_tanggal_khusus_wajib_lengkap_dan_urut():
    for awal, akhir in ((None, D), (D, None), (D, date(2026, 11, 10))):
        with pytest.raises(HTTPException) as e:
            _rentang('khusus', awal, akhir)
        assert e.value.status_code == 422
    assert _rentang('khusus', D, D) == (D, D)

@pytest.mark.parametrize('kode', TAHAP)
def test_setiap_tahap_punya_kueri_valid_dan_keadaan_kosong(kode):
    q, nama = kueri(kode, D, D)
    sql = str(q.compile(dialect=postgresql.dialect()))
    assert 'SELECT' in sql and 'ORDER BY' in sql
    assert 'hpp' not in sql and 'harga' not in sql
    assert nama[:2] == ['id', 'tanggal']
    assert 'Tidak ada transaksi' in susun(kode, D, D, [])

def test_batas_waktu_wib_setengah_terbuka():
    q, _ = kueri('pengeringan', D, D)
    nilai = list(q.compile().params.values())
    assert nilai[0].astimezone(timezone.utc) == datetime(2026, 11, 10, 17, tzinfo=timezone.utc)
    assert nilai[1].astimezone(timezone.utc) == datetime(2026, 11, 11, 17, tzinfo=timezone.utc)

def test_bobot_kosong_dan_jasa_dibedakan():
    rows = [dict(id=1, tanggal=D, kode='GB-1', status='diterima', bobot=Decimal('150.50'), jasa_id=None),
            dict(id=2, tanggal=D, kode='GB-2', status='diterima', bobot=None, jasa_id=3)]
    teks = susun('gabah_masuk', D, D, rows)
    assert '150.50 kg' in teks
    assert 'Bobot belum tercatat: 1' in teks
    assert 'Milik pabrik: 1' in teks and 'Milik jasa: 1' in teks

def test_transfer_batal_dan_pk_ditolak_dikecualikan():
    for kode in ('transfer_pk', 'pk_masuk'):
        q, _ = kueri(kode, D, D)
        sql = str(q.compile(compile_kwargs={'literal_binds': True}))
        assert 'NOT IN' in sql and "'dibatalkan'" in sql and "'ditolak'" in sql


def test_pdf_banyak_halaman_mengulang_kepala_dan_mengamankan_teks():
    from io import BytesIO
    from pypdf import PdfReader
    from app.services.laporan_periode import data_laporan
    from app.web.pdf_periode import buat_pdf
    rows=[dict(id=i,tanggal=D,kode=f'<b>GB-{i}</b>',status='diterima',bobot=Decimal('10.25'),jasa_id=None) for i in range(90)]
    data=data_laporan('gabah_masuk',D,D,rows)
    reader=PdfReader(BytesIO(buat_pdf(data)))
    assert len(reader.pages)>1
    text='\n'.join(p.extract_text() for p in reader.pages)
    assert '<b>GB-0</b>' in text and '<b>GB-89</b>' in text
    assert '922,5 kg' in text
    for page in reader.pages[1:]:
        assert 'Halaman' in page.extract_text()

@pytest.mark.parametrize('saat,tiga,ini,lalu',[
    (date(2026,11,11),date(2026,9,1),date(2026,1,1),(date(2025,1,1),date(2025,12,31))),
    (date(2026,1,3),date(2025,11,1),date(2026,1,1),(date(2025,1,1),date(2025,12,31))),
])
def test_periode_tiga_bulan_dan_tahun(monkeypatch,saat,tiga,ini,lalu):
    from types import SimpleNamespace
    from app.web import laporan
    from app.services import report
    for mod in [laporan,report]:
        monkeypatch.setattr(mod,'now_local',lambda:SimpleNamespace(date=lambda:saat))
    for kode,expected in [('3_bulan',(tiga,saat)),('tahun_ini',(ini,saat)),('tahun_lalu',lalu)]:
        assert laporan._rentang(kode)==report._range(kode)==expected
