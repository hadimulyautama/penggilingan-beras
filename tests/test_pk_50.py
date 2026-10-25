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
