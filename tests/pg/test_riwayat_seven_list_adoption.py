"""Owner fixture proof: native document shells and sameURL read-only hydration."""
import os

import pytest
from bs4 import BeautifulSoup

from tests.pg.test_konsolidasi_stok import stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from app.web.riwayat_daftar_metadata import PROCESS, QC, metadata

pytestmark=pytest.mark.asyncio
PATHS=tuple(PROCESS)+tuple('/riwayat-qc/'+q for q in sorted(QC))
HEADERS={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}


def allowed(role,warehouse,path):
    return role=='admin' or (path in ('/riwayat-sosoh','/riwayat-qc/pk-luar'))==(warehouse=='g2')


@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g1'),('operator','g2')])
async def test_document_guards_native_columns_parity_and_zero_mutation(pg,stok_lengkap,monkeypatch,role,warehouse):
    from app.penggilingan.gudang1.services import milling,drying
    from app.penggilingan.gudang2 import polishing
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as c:
        before=await _sidik(pg)
        for path in PATHS:
            native=await c.get(path,headers={'X-Pindah':'1'})
            shell=None
            async def forbidden(*args,**kwargs):pytest.fail('Document shell waited for heavy history reader')
            with monkeypatch.context() as m:
                m.setattr(milling,'riwayat_giling',forbidden)
                m.setattr(drying,'riwayat_pengeringan',forbidden)
                m.setattr(polishing,'riwayat_sosoh',forbidden)
                shell=await c.get(path,headers=HEADERS)
            if not allowed(role,warehouse,path):
                assert native.status_code==shell.status_code==403,path
                continue
            assert native.status_code==shell.status_code==200,(path,shell.text[-1000:])
            doc=BeautifulSoup(shell.text,'html.parser');root=doc.select_one('[data-riwayat-daftar-native]')
            assert root and root['data-url']==path
            assert 'Belum dibaca' in root.get_text() and not root.select('a[href],input,form')
            assert all(b.has_attr('disabled') for b in doc.select('[data-lk-cetak]'))
            expected=metadata(path)
            for label in expected['columns']:
                if label:assert label in root.get_text()
            native_doc=BeautifulSoup(native.text,'html.parser')
            assert not native_doc.select('[data-riwayat-daftar-native]')
            assert expected['header'] in native.text
            # X-Pindah wins even if foreground flags were inherited.
            repeated=await c.get(path,headers={**HEADERS,'X-Pindah':'1','X-Kerangka-Halaman':'1'})
            assert repeated.status_code==200
            assert not BeautifulSoup(repeated.text,'html.parser').select('[data-riwayat-daftar-native]')
            if path in PROCESS:
                cur=await c.get(path+'?sebelum=1',headers=HEADERS)
                assert BeautifulSoup(cur.text,'html.parser').select_one('[data-riwayat-daftar-native]')['data-url']==path+'?sebelum=1'
        assert await _sidik(pg)==before


@pytest.mark.skipif(not (os.getenv('OWNER_BROWSER') in {'chromium','webkit'} and os.getenv('DETAIL_OUT') and os.getenv('PWA_GUARD')), reason='Owner native HTTP fixture required; mandatory server-role cases remain active')
@pytest.mark.parametrize('role,warehouse,path,qc',[
    ('admin',None,'/riwayat-giling','/riwayat-qc/gabah-basah'),
    ('operator','g1','/riwayat-giling','/riwayat-qc/pk-hasil-giling'),
    ('operator','g2','/riwayat-sosoh','/riwayat-qc/pk-luar'),
])
@pytest.mark.parametrize('width',[390,1280])
async def test_browser_delayed_native_get_error_retry_navigation(pg,stok_lengkap,monkeypatch,role,warehouse,path,qc,width):
    # Protocol proof 8c314882 demonstrated that route interception omits
    # browser Sec-Fetch metadata. Run the original expectations through the
    # approved native HTTP lifecycle instead of fabricating those headers.
    from tests.pg.riwayat_seven_native_http import exercise
    await exercise(pg,stok_lengkap,monkeypatch,role,warehouse,path,qc,width)
