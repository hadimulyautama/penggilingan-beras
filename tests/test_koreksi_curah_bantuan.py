from types import SimpleNamespace as N
import pytest
from bs4 import BeautifulSoup
from decimal import Decimal as D
from hmu_identitas import peran as P
from app.peran import can_see_financials
from app.web.tampilan import templates


def data(*,portal=False,status='Terverifikasi',tipe='byproduct_curah'):
    return N(portal=portal,status=status,pelanggan=[N(rec=N(id=1,kode='OUT-UJI-CURAH',status='selesai'),barang=[N(id=7,nama='Broken curah',tipe=tipe,aktual=D('450.00'))])])

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN])
def test_existing_permission_drives_help_link_not_new_role_right(role):
    allowed=can_see_financials(N(role=role))
    html=templates.env.get_template('_koreksi_curah_bantuan.html').render(perjalanan=data(),boleh_perbaiki=allowed,filter_query='q=curah')
    soup=BeautifulSoup(html,'html.parser');text=soup.get_text(' ',strip=True)
    assert 'Admin atau Super Admin' in text and 'OUT-UJI-CURAH' in text and 'item #7' in text and '450 kg' in text
    assert 'Perbaiki pengiriman' in text and 'Koreksi pengiriman terverifikasi' in text
    assert bool(soup.select('[data-curah-perbaikan]'))==allowed
    if not allowed:assert 'tidak mengirim pengajuan' in text and not soup.select('a,form,button')
    assert not soup.select('form')
    assert soup.select_one('[data-curah-langkah]') and not soup.select_one('[data-curah-langkah]').has_attr('open')

@pytest.mark.parametrize('change',[{'portal':True},{'status':'Masih berjalan'},{'tipe':'finished_goods'}])
def test_help_is_limited_to_internal_final_curah(change):
    html=templates.env.get_template('_koreksi_curah_bantuan.html').render(perjalanan=data(**change),boleh_perbaiki=False,filter_query='')
    assert 'data-bantuan-koreksi-curah' not in html
