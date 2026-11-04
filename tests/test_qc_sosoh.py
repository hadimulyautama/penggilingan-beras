"""QC menentukan sesi; setiap delta hanya meliputi rentang pencatatannya."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace as O
import pytest
from app.services.qc_sosoh import bagi_proporsional, petakan

AWAL = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
def t(jam):
    return AWAL + timedelta(hours=jam)
def sampel(id, jenis, jam, **lain):
    return O(id=id, jenis=jenis, waktu_sampel=t(jam), hasil_pada=None, **lain)
def hasil(id, jenis, kg, jam=10, cara='kumulatif'):
    return O(id=id, jenis=jenis, berat_kg=kg, waktu_update=t(jam), cara_input=cara)
def urutan():
    return [sampel(i+1,'medium',i) for i in range(4)] + [sampel(5,'premium',5),sampel(6,'medium',7)]
def berat(data):
    return [s['berat_estimasi_kg'] for s in data['sesi']]

@pytest.mark.parametrize('n,bobot,jatah', [(5,[5,3],[3,2]),(4,[1,1,1],[2,1,1]),
    (1,[0,10],[0,1]),(0,[2,3],[0,0]),(3,[0,0],[0,0]),(5,['0.005','0.003'],[3,2])])
def test_pembulatan(n,bobot,jatah):
    assert bagi_proporsional(n,bobot) == jatah

def test_qc_tetap_di_sesi_asalnya_meski_entry_kumulatif_per_jenis():
    data=petakan(list(reversed(urutan())),[hasil(1,'medium',8000),hasil(2,'premium',2000)],sampai=t(10))
    assert [[q.id for q in s['sampel']] for s in data['sesi']] == [[1,2,3,4],[5],[6]]
    assert berat(data)==[5000,2000,3000]
    assert [s['estimasi_mulai'] for s in data['sesi']]==[t(0),t(5),t(7)]
    assert not data['belum_dipetakan']

@pytest.mark.parametrize('cara',['kumulatif','tambahan','lama'])
def test_lima_satu_dua_ton_pukul_12_16_dan_akhir_setara(cara):
    data=petakan(urutan(),[hasil(1,'medium',5000,4,cara),hasil(2,'medium',1000,8,cara),
        hasil(3,'medium',2000,10,cara),hasil(4,'premium',2000,10,cara)],sampai=t(10))
    assert berat(data)==[5500,2000,2500]

def test_lima_ton_saat_sesi_pertama_masih_berjalan_lalu_delapan_ton():
    data=petakan(urutan(),[hasil(1,'medium',5000,4),hasil(2,'medium',3000,10)],sampai=t(10))
    assert berat(data)==[5750,None,2250]

def test_berat_lama_tidak_masuk_sesi_masa_depan_dan_tidak_bergeser_seiring_jam():
    rows=[hasil(1,'medium',5000,4)]
    assert berat(petakan(urutan(),rows,sampai=t(10)))==[5000,None,None]
    assert berat(petakan(urutan(),rows,sampai=t(40)))==[5000,None,None]

def test_waktu_sama_satu_cakupan_dan_urutan_entry_antar_jenis_tidak_berpengaruh():
    rows=[hasil(1,'medium',5000),hasil(2,'premium',2000),hasil(3,'medium',3000)]
    a=petakan(urutan(),rows,sampai=t(10))
    assert a==petakan(urutan(),list(reversed(rows)),sampai=t(10))
    assert berat(a)==[5000,2000,3000]

def test_durasi_bukan_jumlah_qc_menentukan_bobot():
    qs=[sampel(i+1,'medium',i/10) for i in range(5)]+[sampel(6,'premium',1),sampel(7,'medium',2)]
    assert berat(petakan(qs,[hasil(1,'medium',8000,5)],sampai=t(5)))==[2000,None,6000]

def test_qc_sebelum_timbang_tidak_mengarang_berat_nol():
    data=petakan([sampel(1,'premium',1)],[],sampai=t(2))
    assert data['belum_dipetakan']==[1] and berat(data)==[None]
    assert data['hasil'][0]['berat_kg'] is None

def test_hasil_sebelum_qc_tetap_aktual_dan_belum_dipetakan():
    data=petakan([],[hasil(1,'medium',5000,4)],mulai=t(0),sampai=t(10))
    assert data['hasil'][0]['berat_kg']==5000 and data['hasil'][0]['belum_dipetakan_kg']==5000
    assert not data['sesi']
    data=petakan([sampel(1,'medium',7)],[hasil(1,'medium',5000,4)],mulai=t(0),sampai=t(10))
    assert berat(data)==[None]

def test_tanpa_qc_perantara_jangan_mengarang_pergantian_dari_entry_hasil():
    data=petakan([sampel(1,'medium',0),sampel(2,'medium',3)],
        [hasil(1,'medium',8000),hasil(2,'premium',2000)],sampai=t(10))
    assert len(data['sesi'])==1 and berat(data)==[8000]
    assert any('Premium' in c for c in data['catatan'])

def test_jeda_dikurangi_sekali_dan_sesi_otomatis_tanpa_input_tambahan():
    data=petakan(urutan(),[hasil(1,'medium',8000)],sampai=t(10),jeda=[(t(2),t(4)),(t(3),t(5))])
    assert berat(data)==[3200,None,4800]
    data=petakan([sampel(1,'medium',0),sampel(2,'medium',3)],
        [hasil(1,'medium',6000,5)],sampai=t(5),jeda=[(t(1),t(2))])
    assert len(data['sesi'])==2

def test_pembulatan_sesi_dan_sampel_selalu_menjaga_total():
    data=petakan(urutan(),[hasil(1,'medium','10.01'),hasil(2,'medium','-0.01')],sampai=t(10))
    assert sum(s['berat_estimasi_kg'] or 0 for s in data['sesi'])==Decimal('10.00')
    assert sum(a['berat_estimasi_kg'] for a in data['alokasi'].values())==Decimal('10.00')

def test_qc_jam_sama_tidak_menggandakan_berat():
    data=petakan([sampel(2,'premium',0),sampel(1,'medium',0),sampel(3,'medium',0)],
        [hasil(1,'medium',1,1)],sampai=t(1))
    assert [s['jenis'] for s in data['sesi']]==['medium','premium','medium']
    assert sum(s['berat_estimasi_kg'] or 0 for s in data['sesi'])==1

def test_pembatalan_tidak_membuang_total_timbang():
    qs=[sampel(1,'medium',0),sampel(2,'premium',5,dibatalkan_pada=t(9)),sampel(3,'medium',7)]
    data=petakan(qs,[hasil(1,'medium',8000)],sampai=t(10))
    assert len(data['sesi'])==1 and berat(data)==[8000]

@pytest.mark.parametrize('k,mentah,hasil_angka', [
    ('kadar_air','13,455','13.46'),('broken_persen','9,995','10.00'),
    ('md','123,456','123.46'),('transparant','1,005','1.01'),
    ('whiteness','45.678','45.68'),('md',0,'0.00'),('md',' 123,40 ','123.40'),
])
def test_lima_komponen_desimal_koma_dan_pembulatan_dua_angka(k,mentah,hasil_angka):
    from app.services.qc_sosoh import angka_qc
    nilai=angka_qc(k,mentah)
    assert nilai==Decimal(hasil_angka) and nilai.as_tuple().exponent==-2

@pytest.mark.parametrize('k,nilai', [('kadar_air','100,001'),('broken_persen',101),
    ('md',-1),('transparant','NaN'),('whiteness','Infinity'),('md','abc'),('md','10000000000')])
def test_validasi_persentase_dan_angka_instrumen(k,nilai):
    from app.services.qc_sosoh import angka_qc, QcSosohError
    with pytest.raises(QcSosohError):
        angka_qc(k,nilai)

def test_format_hasil_dan_rata_rata_hanya_dua_komponen_memakai_persen():
    from app.services.qc_sosoh import ringkasan, rata_rata
    q=O(hasil_pada=t(1),kadar_air=Decimal('13.45'),broken_persen=Decimal('10'),
        md=Decimal('123.46'),transparant=Decimal('1.01'),whiteness=Decimal('45.68'),catatan_lab=None)
    assert ringkasan(q)=='Kadar air 13,45% · Broken 10,00% · MD 123,46 · Transparant 1,01 · Whiteness 45,68'
    q2=O(**{**vars(q),'kadar_air':Decimal('13.46')})
    rata=rata_rata([q,q2])
    assert rata[0]==('Kadar air',Decimal('13.46'),2,'%')
    assert rata[2]==('MD',Decimal('123.46'),2,'')

def test_api_menerima_angka_koma_dan_menolak_komponen_pk():
    from pydantic import ValidationError
    from app.web.aksi_qc_sosoh import HasilReq, spesifikasi
    hasil=HasilReq(sampel_id=1,kadar_air='13,455',broken_persen='10,00',md='123,456',transparant='1,005',whiteness='45,678')
    assert hasil.kadar_air==Decimal('13.455') and hasil.md==Decimal('123.456')
    for nama in ('menir_persen','butir_kuning','gabah','merang'):
        with pytest.raises(ValidationError):
            HasilReq(sampel_id=1,**{nama:1})
    fields=next(s for s in spesifikasi() if s['id']=='qc_sosoh')['fields']
    assert [f['label'] for f in fields if f['name'] not in ('sampel_id','catatan_lab')]==['Kadar air (%)','Broken (%)','MD','Transparant','Whiteness']
