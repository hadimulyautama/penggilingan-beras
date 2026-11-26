"""Prototype is structural only; native handler retains record/warehouse policy."""
import json
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_retur_supplier import asal,skema_retur_timbang
from tests.pg.test_retur_supplier_koreksi import keluar_dua
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
from tests.pg.test_halaman_bertahap import _sidik
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g2'),('operator','g1')])
async def test_read_prototype_does_not_read_record_and_native_scope_stays(pg,lengkap,stok_lengkap,keluar_dua,monkeypatch,role,warehouse):
    from app.services import riwayat_retur_supplier as service
    original=service.detail
    async def forbidden(*a,**kw):raise AssertionError('Prototype must not read a return record')
    client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with client:
        before=await _sidik(pg);monkeypatch.setattr(service,'detail',forbidden)
        response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert response.status_code==200
        doc=BeautifulSoup(response.text,'html.parser');host=doc.select_one('#padi-rsd-kerangka');assert host
        data=json.loads(host.string);assert set(data['frames'])=={'ringkasan','timbang','stok','jejak'}
        for tab,indices in data['frames'].items():
            proto=BeautifulSoup(''.join(data['potongan'][i] for i in indices),'html.parser');root=proto.select_one('[data-rsd-shell]');assert root and root['data-rsd-tab']==tab and root['data-rsd-id']=='__RSD_ID__'
            assert len(root.select('.rsh-tabs [role=tab]'))==4 and len(root.select('h1'))==1
            assert not root.select('form,a[href*="/tindakan"],a[href*="timbangan/transaksi"]')
            assert root.select_one('#rsd-panel')['aria-labelledby']=='rsd-tab-'+tab
            assert len(root.select('style[data-rsd-style]'))==6
            assert '—' in root.get_text() and '0,00 kg' not in root.get_text()
        monkeypatch.setattr(service,'detail',original)
        for tab in data['frames']:
            native=await client.get('/riwayat-retur-supplier/'+str(keluar_dua['rid'])+'?tab='+tab,headers={'X-Pindah':'1'})
            if warehouse=='g1':assert native.status_code==403
            else:
                assert native.status_code==200;root=BeautifulSoup(native.text,'html.parser').select_one('[data-riwayat-retur-supplier]');assert root and root['data-rsd-tab']==tab and not root.select('form,script')
                assert bool(root.select('a[href*="/tindakan"]'))==(role=='admin')
        assert await _sidik(pg)==before
