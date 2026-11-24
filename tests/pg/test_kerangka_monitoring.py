"""Monitoring active branch retains authorized first-click registries."""
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize('role',['operator','admin'])
@pytest.mark.parametrize('enabled',[False,True])
async def test_native_monitoring_keeps_registry_and_session(pg,lengkap,monkeypatch,role,enabled):
    import hmu_identitas.monitoring as monitoring
    from app.web.kerangka_langsung import LITERAL
    import json
    # Isolate the monitoring enablement branch only. Real auth and database
    # namespace resolution are unchanged; no company/binding/grant is created.
    monkeypatch.setattr(monitoring,'RuangData',SimpleNamespace(
        lingkungan=lambda:object() if enabled else None))
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as client:
        before=await _sidik(pg)
        for path in ('/kabar','/pekerjaan','/barang-masuk','/stok'):
            response=await client.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            assert response.status_code==200 and 'no-store' in response.headers['cache-control']
            doc=BeautifulSoup(response.text,'html.parser')
            hosts=doc.select('#padi-kerangka-langsung')
            assert len(hosts)==1 and not hosts[0].find_parent(class_='bingkai')
            assert len(doc.select('script[src^="/monitoring/aktivitas.js"]'))==int(enabled)
            data=json.loads(hosts[0].string)
            assert set(LITERAL).issubset(data['frames'])
            assert data['konteks']==doc.select_one('.bingkai')['data-pindah-konteks']
            assert data['sesi']==doc.select_one('#formulir-sesi')['data-token']
            assert len(doc.select('#padi-stok-kerangka'))==1
            assert int(response.headers['content-length'])==len(response.content)
        assert await _sidik(pg)==before
