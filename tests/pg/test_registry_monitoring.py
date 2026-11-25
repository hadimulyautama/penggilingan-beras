"""Acceptance with official synthetic company and real monitoring middleware.
No production namespace, account, setting or source is used or changed.
"""
import json,os
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from hmu_identitas.ruang_data import pasang_pagar
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark=pytest.mark.asyncio

async def test_real_monitoring_keeps_authorized_local_frames(pg,lengkap,monkeypatch,tmp_path):
 pin=os.environ.get('RAILWAY_GIT_COMMIT_SHA','local');out=Path(os.environ.get('DETAIL_OUT',str(tmp_path)));result={'status':'FAIL','source':pin,'scope':'Official synthetic company namespace, guarded PG, native MonitoringHTTP and real signed fixture sessions. No production.','inputs':[],'cases':[]}
 target=out/'monitoring-registry.json'
 # Established legacy tokens follow the official namespace fixture's own
 # explicit grace boundary; no live identity or grant is created.
 admin=await _klien(pg,role='admin')
 operator=await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2'])
 space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space)
 pasang_pagar(pg.kw['bind'],wajib=True)
 from app.web import kerangka_langsung as registry
 original=registry.lengkapi_dokumen
 async def observed(request,response):
  if request.url.path in ('/jasa','/pekerjaan'):
   result['inputs'].append({'path':request.url.path,'native_flag':bool(getattr(request.state,'dokumen_native_kerangka',False)),'content_length_present':'content-length' in response.headers,'content_encoding_present':'content-encoding' in response.headers})
  return await original(request,response)
 monkeypatch.setattr(registry,'lengkapi_dokumen',observed)
 before=await _sidik(pg)
 try:
  for role,client,path in [('admin',admin,'/jasa'),('operator',operator,'/pekerjaan')]:
   response=await client.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
   doc=BeautifulSoup(response.text,'html.parser');host=doc.select_one('#padi-kerangka-langsung')
   row={'role':role,'path':path,'status':response.status_code,'monitor_scripts':len(doc.select('script[src^="/monitoring/aktivitas.js"]')),'registry_present':host is not None};result['cases'].append(row)
   assert response.status_code==200 and row['monitor_scripts']==1
   assert host is not None,'Active MonitoringHTML must retain the authorized local-frame catalog'
   data=json.loads(host.string);assert registry.sah_rujukan(data)
   assert ('/jasa' in data['frames'])==(role=='admin')
   # Both server identity and namespace guards remain authoritative.
   if role=='operator':assert (await client.get('/jasa')).status_code==403
  result['status']='PASS'
 finally:
  result['fingerprint_unchanged']=await _sidik(pg)==before
  await admin.aclose();await operator.aclose()
  target.write_text(json.dumps(result,indent=2)+'\n')
 assert result['fingerprint_unchanged']
