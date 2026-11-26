"""Read shell never adopts the Admin QC writer or invents lab data."""
import json
import pytest
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_qc_sosoh import dunia as rice_dunia,ambil
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse,expected', [('operator','g2',200),('operator','g1',403),('operator',None,403),('admin',None,200)])
async def test_readonly_shell_keeps_native_role_and_writer(pg,lengkap,stok_lengkap,rice_dunia,monkeypatch,role,warehouse,expected):
    await ambil(pg,rice_dunia)
    client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with client:
        before=await _sidik(pg)
        path='/riwayat-qc/beras-hasil-sosoh/'+rice_dunia['proc'].kode_proses
        for tab in ('ringkasan','sampel','sesi','asal'):
            shell=await client.get(path+'?tab_qc='+tab,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            native=await client.get(path+'?tab_qc='+tab,headers={'X-Pindah':'1'})
            assert shell.status_code==native.status_code==expected
            if expected!=200:continue
            s=BeautifulSoup(shell.text,'html.parser');n=BeautifulSoup(native.text,'html.parser')
            if role=='admin':
                assert not s.select('[data-qc-beras-shell]')
                assert bool(s.select('[data-qc-editor]'))==bool(n.select('[data-qc-editor]'))
            else:
                root=s.select_one('[data-qc-beras-shell]');assert root and len(root.select('[role=tab]'))==4
                assert root.select_one('#qc-panel-'+tab).get('hidden') is None
                assert [len(t.select('thead th')) for t in root.select('table')]==[3,6,5]
                assert not root.select('form,[data-qc-editor],[data-qc-baru],[data-qc-lengkapi]')
                assert root.select_one('[aria-disabled=true]').text.strip()=='Lihat proses'
                assert 'Menunggu hasil QC' in n.text and n.select_one('[data-qc-sosoh]')
        home=BeautifulSoup((await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})).text,'html.parser')
        host=home.select_one('#padi-qc-kerangka');desc=json.loads(host.string) if host else {}
        assert bool(desc.get('beras'))==(role=='operator' and warehouse=='g2')
        if desc.get('beras'):assert set(desc['beras']['frames'])=={'beras-hasil-sosoh'}
        if expected==200:
            # Action, unknown and duplicate parameters stay native.
            for query in ('buka=batalkan_sampel_qc_sosoh&nilai=1','tab_qc=sampel&tab_qc=asal','nilai=1'):
                r=await client.get(path+'?'+query,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
                assert r.status_code==200 and not BeautifulSoup(r.text,'html.parser').select('[data-qc-beras-shell]')
            r=await client.get('/riwayat-qc/beras-hasil-sosoh/NOT-FOUND',headers={'X-Pindah':'1'})
            assert r.status_code==404
        assert await _sidik(pg)==before
