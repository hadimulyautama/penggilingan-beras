"""Format bobot riwayat tidak boleh mengubah nilai kosong menjadi nol atau membulatkan tara kecil menjadi nol."""
import pytest
from jinja2 import Undefined
from app.web.tampilan import templates

@pytest.mark.parametrize('nilai,satuan,teks',[
    ('9000.000','kg','9.000 kg'),
    ('-0.125','kg','-0,125 kg'),
    ('0.1000','kg/karung','0,1 kg/karung'),
    ('0.0001','kg/karung','0,0001 kg/karung'),
    ('0','kg','0 kg'),
    (None,'kg','Belum tersedia'),
    ('None','kg','Belum tersedia'),
    ('','kg','Belum tersedia'),
    (Undefined(),'kg','Belum tersedia'),
])
def test_bobot_historis_angka_dan_kosong(nilai,satuan,teks):
    macro=templates.get_template('_detail_kirim_tabs.html').module.angka
    assert str(macro(nilai,satuan)).strip()==teks
