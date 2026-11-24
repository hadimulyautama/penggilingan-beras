"""Permission choice follows native actor; blueprint itself is public UI only."""
import json
import pytest
from bs4 import BeautifulSoup
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_jasa_bertahap import _tanpa_host_registry

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse,variant',[(P.ADMIN,None,'pengiriman-admin'),(P.SUPERADMIN,None,'pengiriman-admin'),(P.OPERATOR,'g2','pengiriman-operator'),(P.OPERATOR,'g1',None)])
async def test_manifest_uses_native_permission_and_read_context(pg,stok_lengkap,role,warehouse,variant):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        response=await client.get('/kabar')
        assert response.status_code==200
        doc=BeautifulSoup(response.text,'html.parser')
        head=doc.select('head script[src^="/static/kerangka-ui.js?v="]')
        assert len(head)==1 and not head[0].has_attr('defer') and not head[0].has_attr('async')
        ui=doc.select_one('#padi-kerangka-ui')
        assert ui is not None
        if ui:
            registry=json.loads(doc.select_one('#padi-kerangka-langsung').string)
            data=json.loads(ui.string)
            assert set(data)=={'versi','sumber','cap','konteks','sesi','varians'}
            assert data['varians']==({'pengiriman':variant,'jasa':'jasa-admin','akun':'akun-pribadi','laporan':'laporan-katalog'} if variant=='pengiriman-admin' else {'pengiriman':variant,'akun':'akun-pribadi','laporan':'laporan-katalog'} if variant else {'akun':'akun-pribadi','laporan':'laporan-katalog'})
            assert all(data[k]==registry[k] for k in ('cap','konteks','sesi'))
            _tanpa_host_registry(response.text)
        assert await _sidik(pg)==before
