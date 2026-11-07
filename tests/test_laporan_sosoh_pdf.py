from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as N
from io import BytesIO
from copy import deepcopy
from pypdf import PdfReader
from app.penggilingan.gudang2.polishing import neraca_sosoh
from app.web.laporan_sosoh import buat_pdf
from app.web.pdf_sosoh import qc_bahan,ringkas_sumber


def data_sosoh():
    start=datetime(2026,10,31,1,tzinfo=timezone.utc)
    outputs=dict(medium=4800,premium=600,broken=750,menir=150,bekatul=600,reject=75)
    return dict(process=N(kode_proses='POL-20261031-01',waktu_mulai=start,waktu_selesai=start+timedelta(hours=4)),owner='Pemilik Uji',operator='Operator Uji',outputs=outputs,balance=neraca_sosoh(7500,outputs),input_complete=True,neraca_tercatat=None,jeda=dict(tertahan='20 menit',efektif='3 jam 40 menit',kalender='4 jam',items=[]),source_rows=[dict(kind='giling',code='LOT-20261030-01',material='PK hasil giling',owner='Pemilik Uji',weight=4000),dict(kind='pk_luar',code='PKB-20261030-02',material='PK beli luar',owner='Pemasok Uji',weight=3500)],milling_qc=[dict(code='LOT-20261030-01',moisture=v,broken=b,loss=l,yellow=y,paddy='bersih',chaff='bersih') for v,b,l,y in [(13.2,20,10,'bersih'),(13.4,22,11,'sedikit'),(13.6,24,12,'banyak')]],external_qc=[dict(code='PKB-20261030-02',moisture=14,broken=20,loss=10,yellow='sedikit',paddy='bersih',chaff='parah')])


def test_ringkasan_dua_halaman_dan_neraca_asli():
    d=data_sosoh();before=deepcopy(d)
    r=PdfReader(BytesIO(buat_pdf(d)))
    assert len(r.pages)==2
    first,second=[' '.join(p.extract_text().split()) for p in r.pages]
    for x in ['7.500 kg','5.400 kg','72,0%','6.975 kg','525 kg (7,0%)','3 jam 40 menit']:
        assert x in first
    for x in ['Bahan PK dan catatan proses','13,4%','22,0%','11,0%','3 pemeriksaan','1 pemeriksaan','Sedikit / Bersih / Parah']:
        assert x in second
    assert 'QC bahan PK' not in first.split('Status:')[0]
    assert 'Rincian QC proses giling dan pengeringan' not in first+second
    assert d==before


def test_agregat_memakai_nilai_sumber_bukan_teks_dan_tidak_mengisi_kosong():
    d=data_sosoh()
    d['milling_qc'][0]['moisture']=None
    ratings=qc_bahan(d)
    assert ratings['LOT-20261030-01']['rows'][0]['n']==2
    d['external_qc'][0]['loss']=None
    assert qc_bahan(d)['PKB-20261030-02']['rows'][2]['hasil']=='Belum dinilai'
    d['source_rows'].append(dict(d['source_rows'][0],weight=100))
    assert ringkas_sumber(d)[0]['weight']==4100
    d['source_rows'][-1]['weight']=None
    assert ringkas_sumber(d)[0]['weight'] is None


def test_bahan_tidak_final_dan_campuran_broken_tidak_diberi_rendemen_pasti():
    d=data_sosoh();d['input_complete']=False
    d['source_rows'][0]['kind']='broken';d['source_rows'][0]['material']='Broken'
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(buat_pdf(d))).pages)
    assert 'BAHAN DIPAKAI' in text and 'PK DIPAKAI' not in text
    assert 'Belum dapat dipastikan' in text and '72,0%' not in text
    assert 'Belum dicatat' in text


def test_koreksi_bobot_penutupan_dan_angka_nol_tetap_jelas():
    d=data_sosoh();d['neraca_tercatat']=neraca_sosoh(8000,d['outputs'])
    text=' '.join(' '.join(p.extract_text().split()) for p in PdfReader(BytesIO(buat_pdf(d))).pages)
    assert 'Saat ditutup: bahan 8.000 kg' in text
    d['balance']=neraca_sosoh(0,{})
    d['outputs']={};d['milling_qc']=[];d['external_qc']=[];d['source_rows']=[]
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(buat_pdf(d))).pages)
    assert 'Belum ada catatan QC' in text and 'Belum dapat dipastikan' in text
