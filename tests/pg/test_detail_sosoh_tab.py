"""Tautan lama membuka lembar kerja; seluruh riwayat tetap tersedia."""
import json,re
import pytest
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
pytestmark=pytest.mark.asyncio

def data(r):return json.loads(re.search(r'<script id="sosoh-awal" type="application/json">(.*?)</script>',r.text,re.S)[1])

@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_lembar_konteks_hasil_penuh_dan_jeda(pg,gudang2,peran):
 from app.penggilingan.gudang2 import polishing as p
 from app.penggilingan.gudang1.services import jeda
 u=gudang2['user']
 async with pg() as db:
  pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
  for i in range(1,23):await p.catat_output(db,user=u,kode=pr.kode_proses,jenis='medium',berat_kumulatif=i*10,spek=f'SPEK-{i}')
 asal='/pekerjaan?tab=berjalan&jenis=sosoh&gudang=g2&kepemilikan=pabrik'
 from urllib.parse import urlencode
 async with await _klien(pg,peran=peran,gudang='Gudang 2') as c:
  for params in [{'tab_detail':'ringkasan'},{'tab_detail':'bahan'},{'halaman_hasil':2},{'tab_detail':'riwayat'}]:
   r=await c.get('/proses-aktif/sosoh/'+pr.kode_proses+'?'+urlencode(dict(params,kembali_kerja=asal)))
   assert r.status_code==200 and 'data-sosoh-ringkas' in r.text
   d=data(r);assert next(h['kg'] for h in d['hasil'] if h['jenis']=='medium')==220
   assert len(d['riwayat_hasil'])==22 and {h['spek'] for h in d['riwayat_hasil']}=={f'SPEK-{i}' for i in range(1,23)}
   assert d['sumber'][0]['awal']==9800 and d['kepemilikan']=='Milik pabrik';assert d['sementara']['bahan']==9800
   assert 'MOCKUP' not in r.text and 'Peran contoh' not in r.text
   assert asal.replace('&','&amp;') in r.text
  r=await c.get('/proses-sosoh/'+pr.kode_proses+'?buka=hasil_penyosohan&nilai='+pr.kode_proses)
  assert r.status_code==200 and 'data-buka="hasil_penyosohan"' in r.text
  async with pg() as db:await jeda.hentikan(db,user=u,jenis='penyosohan',kode=pr.kode_proses,sebab='Listrik padam')
  d=data(await c.get('/proses-aktif/sosoh/'+pr.kode_proses));assert d['jeda']['sebab']=='Listrik padam' and d['status']=='dijeda'

async def test_operator_gudang_efektif_dan_endpoint_langsung(pg,gudang2):
 from app.models import Warehouse
 from app.penggilingan.gudang2.polishing import mulai_penyosohan
 from app.web.lihat_sebagai import NAMA_KUKI
 async with pg() as db:
  db.add(Warehouse(nama_gudang='Gudang 1 - Selepan',kode_fungsi='g1'));await db.commit()
  pr=(await mulai_penyosohan(db,user=gudang2['user'],nama_silos=['B'])).proc
 async with await _klien(pg,peran='operator',gudang='Gudang 2',lihat='operator:g1') as c:
  c.cookies.set(NAMA_KUKI,'operator:g1')
  for path in ['/proses-aktif/sosoh/','/proses-sosoh/','/api/actions/sosoh-ringkas/']:assert (await c.get(path+pr.kode_proses)).status_code==403

async def test_neraca_aktif_mempertahankan_selisih_negatif(pg,gudang2):
 from app.database import now_local
 from app.models import PolishingOutputLog
 from app.penggilingan.gudang2.polishing import mulai_penyosohan
 async with pg() as db:
  pr=(await mulai_penyosohan(db,user=gudang2['user'],nama_silos=['B'])).proc
  db.add(PolishingOutputLog(polishing_process_id=pr.id,jenis='medium',berat_kg=10000,waktu_update=now_local(),input_by=gudang2['user'].id));await db.commit()
 async with await _klien(pg,peran='admin') as c:
  r=await c.get('/proses-aktif/sosoh/'+pr.kode_proses);assert r.status_code==200
  d=data(r);assert d['sementara']['timpang'] and d['sementara']['selisih']==-200
