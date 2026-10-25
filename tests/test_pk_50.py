"""Pemecahan unit tidak menciptakan berat atau membulatkan saldo."""
from decimal import Decimal
import pytest
from app.services.pk_50 import bagi, teks

@pytest.mark.parametrize('kg,n,c', [('0',0,'0'),('49.999',0,'49.999'),('50',1,'0'),('50.001',1,'0.001'),('6420',128,'20'),('6420.123',128,'20.123')])
def test_unit_tetap_satu_bobot(kg,n,c):
    assert bagi(kg) == (n,Decimal(c))
    assert n*50+Decimal(c) == Decimal(kg)

@pytest.mark.parametrize('kg',['-1','NaN','Infinity','-Infinity'])
def test_bobot_tidak_sah(kg):
    with pytest.raises(ValueError):bagi(kg)

def test_label_tanpa_mengubah_nilai():
    assert teks('6420') == '128 karung × 50 kg + 20 kg curah'


@pytest.mark.parametrize('isi,kg', [
    ({'jumlah_karung':10,'berat_curah_kg':20},520),
    ({'jumlah_karung':10},500), ({'berat_curah_kg':20},20),
    ({'jumlah_karung':0,'berat_curah_kg':'0.125'},.125),
    ({'berat':75.125},75.125), ({'berat':75.125,'cara':'kg'},75.125),
    ({},None), ({'jumlah_karung':1,'berat_curah_kg':75},125),
])
def test_unit_permintaan_ke_satu_bobot(isi,kg):
    from app.services.pk_50 import bobot_isian
    assert bobot_isian(**isi) == kg


@pytest.mark.parametrize('isi', [
    {'jumlah_karung':1.5}, {'jumlah_karung':True}, {'jumlah_karung':-1},
    {'jumlah_karung':'NaN'}, {'berat_curah_kg':'Infinity'},
    {'berat_curah_kg':-1}, {'jumlah_karung':0}, {'cara':'karung'},
    {'cara':'lain'}, {'berat':50,'jumlah_karung':1},
    {'cara':'kg','jumlah_karung':1}, {'cara':'karung','berat':50},
])
def test_unit_permintaan_tidak_ambigu(isi):
    from app.services.pk_50 import bobot_isian
    with pytest.raises(ValueError): bobot_isian(**isi)
