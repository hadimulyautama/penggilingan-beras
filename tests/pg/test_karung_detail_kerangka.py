"""Prototype contains no balance, row or ownership action."""
import json
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
from tests.pg.test_halaman_bertahap import _sidik
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g2'),('operator','g1'),('operator',None)])
async def test_destination_matches_stock_catalogue_without_reading_sources(pg,lengkap,stok_lengkap,monkeypatch,role,warehouse):
    from app.services import kepemilikan_detail
    original=kepemilikan_detail.daftar_karung
    async def forbidden(*args,**kw):raise AssertionError('Prototype must not read packaging source rows')
    client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with client:
        before=await _sidik(pg);monkeypatch.setattr(kepemilikan_detail,'daftar_karung',forbidden)
        response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert response.status_code==200
        doc=BeautifulSoup(response.text,'html.parser');stock=doc.select_one('#padi-stok-kerangka');stock=json.loads(stock.string) if stock else {}
        host=doc.select_one('#padi-karung-detail-kerangka');assert bool(host)==('karung' in stock.get('frames',{}))
        if host:
            d=json.loads(host.string);assert set(d['frames'])=={'/stok/karung/detail'}
            proto=BeautifulSoup(''.join(d['potongan'][n] for n in d['frames']['/stok/karung/detail']),'html.parser')
            root=proto.select_one('[data-karung-detail-shell]');assert root and len(root.select('h1'))==1
            assert not root.select('form,article,a[href*="/stok/sumber/"]')
            assert len(root.select('nav [aria-disabled=true]'))==2
        monkeypatch.setattr(kepemilikan_detail,'daftar_karung',original)
        path='/stok/karung/detail?material=laminasi&ukuran=25&merk=Penyunesia&pemilik=pabrik'
        native=await client.get(path,headers={'X-Pindah':'1'})
        if role=='admin' or warehouse=='g2':
            assert native.status_code==200
            actual=BeautifulSoup(native.text,'html.parser').select_one('[data-karung-detail-native]');assert actual and actual.select('.daftar-standar__baris')
            assert not actual.select('form,script,[data-kepemilikan-sumber]')
        else:assert native.status_code==403
        assert await _sidik(pg)==before
