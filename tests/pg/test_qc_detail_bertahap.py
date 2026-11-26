"""Detail shell is metadata only; native QC remains the read authority."""
import json,re
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import event
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar

pytestmark=pytest.mark.asyncio
REF={'gabah-basah':'GB-QC-BASAH','gabah-kering':'GB-QC-KERING',
     'pk-hasil-giling':'LOT-QC-DETAIL','pk-luar':'PKB-QC-DETAIL'}

@pytest.mark.parametrize('role,warehouse,allowed',[
 ('admin',None,set(REF)),('operator','g1',{'gabah-basah','gabah-kering','pk-hasil-giling'}),
 ('operator','g2',{'pk-luar'}),('operator',None,set())])
async def test_shell_keeps_native_scope_and_original_values(pg,lengkap,stok_lengkap,qc,monkeypatch,role,warehouse,allowed):
    client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with client:
        before=await _sidik(pg)
        home=BeautifulSoup((await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})).text,'html.parser')
        host=home.select_one('#padi-qc-kerangka')
        if allowed:
            descriptor=json.loads(host.string)['detail'];assert set(descriptor['frames'])==allowed
            for kind,indexes in descriptor['frames'].items():
                proto=BeautifulSoup(''.join(descriptor['potongan'][i] for i in indexes),'html.parser')
                root=proto.select_one('[data-qc-detail-shell]');assert root['data-qc-kind']==kind
                assert root['data-qc-ref']=='__QC_REF__' and len(root.select('.qc-tabs a'))==4
                assert len(root.select('style[data-qc-detail-style]'))==6
                assert 'GB-QC-BASAH' not in root.text and 'LOT-QC-DETAIL' not in root.text
        for kind,ref in REF.items():
            for tab in ['ringkasan','putaran','perhitungan','asal']:
                path=f'/riwayat-qc/{kind}/{ref}?tab_qc={tab}&putaran=1&kembali_qc=%2Fstok'
                shell=await client.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
                native=await client.get(path,headers={'X-Pindah':'1'})
                if kind not in allowed:
                    assert shell.status_code==native.status_code==403;continue
                assert shell.status_code==native.status_code==200
                s=BeautifulSoup(shell.text,'html.parser');n=BeautifulSoup(native.text,'html.parser')
                root=s.select_one('[data-qc-detail-shell]');assert root and root['data-qc-ref']==ref
                assert root.select_one('#qc-panel-'+tab).get('hidden') is None
                assert root.select_one('[data-qc-detail-back]')['href']=='/stok'
                assert root.select_one('#qc-putaran').has_attr('disabled')
                assert len(root.select('.qc-pager [aria-disabled=true]'))==2
                assert root.select_one('.kontrol-paginasi__posisi').text=='— / —'
                assert not root.select('.qc-history-round,form[method=post]')
                assert n.select_one('[data-riwayat-qc]')['data-qc-ref']==ref
                assert n.select_one('.qc-history-round') and not n.select('[data-qc-detail-shell]')
        if allowed:
            kind=next(iter(allowed));missing=await client.get(f'/riwayat-qc/{kind}/TIDAK-ADA',headers={'X-Pindah':'1'})
            assert missing.status_code==404
        assert await _sidik(pg)==before


async def test_prototype_does_not_read_qc_and_unknown_query_keeps_native(pg,lengkap,monkeypatch):
    from app.models import PurchaseBatchQcSample,MillingQcLog,PkPurchaseQcLog,SampelQcSosoh
    names=[m.__tablename__ for m in [PurchaseBatchQcSample,MillingQcLog,PkPurchaseQcLog,SampelQcSosoh]]
    def check(conn,cursor,statement,*args):
        assert not any(re.search(r'\b'+re.escape(n)+r'\b',statement,re.I) for n in names)
    engine=pg.kw['bind'].sync_engine
    async with await _klien(pg,role='admin') as client:
        space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
        event.listen(engine,'before_cursor_execute',check)
        try:
            r=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            descriptor=json.loads(BeautifulSoup(r.text,'html.parser').select_one('#padi-qc-kerangka').string)
            assert len(descriptor['detail']['frames'])==4
        finally:event.remove(engine,'before_cursor_execute',check)
        # Arbitrary action/editor parameters are never adopted by this shell.
        r=await client.get('/riwayat-qc/pk-luar/TIDAK-ADA?buka=unknown',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert r.status_code==404 and 'data-qc-detail-shell' not in r.text
