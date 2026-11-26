"""Only a structural list; native GET owns filters and warehouse permissions."""
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
@pytest.mark.parametrize('role,wh',[('admin',None),('operator','g2'),('operator','g1')])
async def test_prototype_has_controls_not_rows_and_native_scope_stays(pg,lengkap,stok_lengkap,keluar_dua,monkeypatch,role,wh):
 from app.services import riwayat_retur_supplier as svc
 original=svc.daftar
 async def forbidden(*a,**kw):raise AssertionError('Prototype cannot read history rows')
 client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][wh] if wh else None);space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
 async with client:
  before=await _sidik(pg);monkeypatch.setattr(svc,'daftar',forbidden)
  response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert response.status_code==200
  soup=BeautifulSoup(response.text,'html.parser');host=soup.select_one('#padi-rrs-kerangka');assert host;d=json.loads(host.string);assert set(d['frames'])=={'/riwayat-retur-supplier'}
  proto=BeautifulSoup(''.join(d['potongan'][i] for i in d['frames']['/riwayat-retur-supplier']),'html.parser');root=proto.select_one('[data-rrs-shell]');assert root
  assert len(root.select('.rsh-tabel thead th'))==6 and not root.select('a[href^="/riwayat-retur-supplier/"]')
  assert set(n['name'] for n in root.select('input[name],select[name]'))=={'q','awal','akhir','status','supplier','gudang'}
  assert root.select_one('select[name=supplier]').has_attr('disabled') and root.select_one('select[name=gudang]').has_attr('disabled')
  assert all(x.get_text()=='—' for x in root.select('.rrs-metrik strong'))
  assert not root.select('form[method=post]');monkeypatch.setattr(svc,'daftar',original)
  native=await client.get('/riwayat-retur-supplier',headers={'X-Pindah':'1'});assert native.status_code==200 and 'data-rrs-native' in native.text and 'data-rrs-shell' not in native.text
  native=await client.get('/riwayat-retur-supplier?gudang='+str(lengkap['gudang']['g2']),headers={'X-Pindah':'1'});assert native.status_code==(403 if wh=='g1' else 200)
  empty=await client.get('/riwayat-retur-supplier?q=not-a-synthetic-record',headers={'X-Pindah':'1'});assert empty.status_code==200;empty=BeautifulSoup(empty.text,'html.parser');assert len(empty.select('.rsh-tabel thead th'))==6 and 'Tidak ada hasil pada filter ini' in empty.get_text()
  assert await _sidik(pg)==before
