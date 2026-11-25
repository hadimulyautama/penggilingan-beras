"""Kerangka lima daftar QC: izin native, angka utuh, tanpa mutasi GET."""
import json,re
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import event
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_qc_sosoh import dunia as rice_dunia,ambil as rice_sample
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from tests.pg.test_halaman_bertahap import _sidik,_isi
from hmu_identitas.ruang_data import pasang_pagar

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse,allowed',[
 ('admin',None,{'gabah-basah','gabah-kering','pk-hasil-giling','pk-luar','beras-hasil-sosoh'}),
 ('operator','g1',{'gabah-basah','gabah-kering','pk-hasil-giling'}),
 ('operator','g2',{'pk-luar','beras-hasil-sosoh'}),('operator',None,set())])
async def test_qc_shell_permission_native_parity_and_query(pg,lengkap,qc,rice_dunia,monkeypatch,role,warehouse,allowed):
    from app.web.qc_bertahap import TUJUAN,KOLOM
    await rice_sample(pg,rice_dunia)
    client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    before=await _sidik(pg)
    try:
        home=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        dom=BeautifulSoup(home.text,'html.parser');host=dom.select_one('#padi-qc-kerangka')
        assert bool(host)==bool(allowed)
        if host:
            data=json.loads(host.string);base=json.loads(dom.select_one('#padi-kerangka-langsung').string)
            assert set(data['frames'])=={'/riwayat-qc/'+x for x in allowed}
            assert all(data[k]==base[k] for k in ('cap','konteks','sesi'))
            for path,refs in data['frames'].items():
                f=BeautifulSoup(''.join(data['potongan'][i] for i in refs),'html.parser')
                assert f.select_one('script[data-qc-aset-native="qc-kerangka.js"]')
                assert f.select_one('script[data-qc-aset-native="halaman-bertahap.js"]')
                assert f.select_one('[data-lk-cetak]').has_attr('disabled')
                assert not f.select('form[method=post],.tabel-standar__baris[href],a[href*="/GB-QC-"]')
        for kind,cfg in TUJUAN.items():
            shell=await client.get(cfg['path'],headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            native=await client.get(cfg['path'],headers={'X-Pindah':'1'})
            response=await client.get('/api/halaman-bertahap/'+kind)
            if cfg['jenis'] not in allowed:
                assert shell.status_code==native.status_code==response.status_code==403
                continue
            assert shell.status_code==native.status_code==response.status_code==200
            sd=BeautifulSoup(shell.text,'html.parser');nd=BeautifulSoup(native.text,'html.parser')
            root=sd.select_one('[data-halaman-bertahap]')
            assert root and root['data-kind']==kind and root['data-stamp']==response.json()['stamp']
            assert _isi(native.text)==_isi(response.json()['html'])
            assert nd.select_one('[data-halaman-bertahap]') is None
            if cfg['jenis']=='beras-hasil-sosoh':
                assert [a['href'] for a in sd.select('[data-qc-rice-actions] a')]==[a['href'] for a in nd.select('[data-qc-rice-actions] a')]
                assert sd.select_one('[data-qc-rice-columns]')
            else:
                assert [x.text for x in sd.select('[data-qc-summary] strong')]==['—','—']
                assert [x.text.strip() for x in sd.select('[data-qc-read-grid] .tabel-standar__kepala>span')]==KOLOM
                assert [x.text.strip() for x in nd.select('.tabel-standar__kepala>span')]==KOLOM
            for query in ('?asal=pekerjaan','?buka=unknown&nilai=synthetic'):
                doc=await client.get(cfg['path']+query,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
                assert BeautifulSoup(doc.text,'html.parser').select_one('[data-halaman-bertahap]') is None
                raw=await client.get(cfg['path']+query,headers={'X-Pindah':'1'})
                result=await client.get('/api/halaman-bertahap/'+kind+query)
                assert _isi(raw.text)==_isi(result.json()['html'])
        assert await _sidik(pg)==before
    finally:await client.aclose()

async def test_qc_prototypes_do_not_read_qc_records(pg,lengkap,monkeypatch):
    from app.models import PurchaseBatchQcSample,MillingQcLog,PkPurchaseQcLog,SampelQcSosoh
    names=[m.__tablename__ for m in (PurchaseBatchQcSample,MillingQcLog,PkPurchaseQcLog,SampelQcSosoh)]
    def check(conn,cursor,statement,*args):
        assert not any(re.search(r'\b'+re.escape(name)+r'\b',statement,re.I) for name in names),'Prototype may not query QC records'
    engine=pg.kw['bind'].sync_engine
    async with await _klien(pg,role='admin') as client:
        before=await _sidik(pg);event.listen(engine,'before_cursor_execute',check)
        try:
            response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            assert response.status_code==200 and BeautifulSoup(response.text,'html.parser').select_one('#padi-qc-kerangka')
        finally:event.remove(engine,'before_cursor_execute',check)
        assert await _sidik(pg)==before

@pytest.mark.parametrize('status',[503,403])
async def test_optional_qc_failure_keeps_session_boundary(pg,lengkap,monkeypatch,status):
    from fastapi import HTTPException
    from app.web import qc_bertahap
    async def fail(*a,**k):raise HTTPException(status,'Synthetic unavailable')
    monkeypatch.setattr(qc_bertahap,'susun',fail)
    async with await _klien(pg,role='admin') as client:
        before=await _sidik(pg)
        response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        dom=BeautifulSoup(response.text,'html.parser')
        assert response.status_code==200 and dom.select_one('#padi-qc-kerangka') is None
        assert bool(dom.select_one('#padi-kerangka-langsung'))==(status==503)
        assert await _sidik(pg)==before
