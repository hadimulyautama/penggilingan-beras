"""Penggilingan ringkas tetap memakai kumulatif/stock/QC/penyelesaian lama."""
import asyncio,json,re
import pytest
from sqlalchemy import select,func,delete
from app.models import (User,MillingProcess,MillingProcessSource,MillingProgressLog,MillingQcLog,MillingProcessVerification,ActivityLog)
from app.penggilingan.gudang1.services import milling as m,jeda
from tests.pg.test_form_hasil_penggilingan import hasil,g1,_isi_silo_g1,fakta
from tests.pg.test_form_selesai_penggilingan import lepas
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

def url(pr,act=None,step=None):return '/api/actions/giling-ringkas/'+pr.kode_proses+(f'/{act}/{step}' if act else '')
async def post(c,pr,act,step,body):return await c.post(url(pr,act,step),json=body,headers={'X-CSRF-Token':cap_formulir(c)})
async def preview(c,pr,act,**kw):
 d=(await c.get(url(pr))).json();body={'dasar':d['dasar'],**kw};r=await post(c,pr,act,'periksa',body);assert r.status_code==200,r.text
 return {**body,'pemeriksaan':r.json()['pemeriksaan'],'konfirmasi':True}

async def test_reader_semua_sumber_qc_kosong_dan_legacy_tanpa_mutasi(pg,hasil):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg,pr);r=await c.get(url(pr));assert r.status_code==200,r.text;d=r.json()
  assert d['tercatat']==6000 and d['dasar_stok']==6000 and d['stok_sebelum']==6000
  assert len(d['silos_aktif'])==2 and len(d['sumber'])==2 and d['qc']['putaran']==0 and d['qc']['nilai'] is None
  assert not d['siap'] and d['penghalang'];assert r.headers['cache-control']=='no-store';assert await fakta(pg,pr)==before
  page=await c.get('/proses-aktif/giling/'+pr.kode_proses+'?buka=hasil_giling');assert page.status_code==200,page.text
  assert 'data-giling-ringkas' in page.text and 'data-buka="hasil_giling"' in page.text;assert await fakta(pg,pr)==before

@pytest.mark.parametrize('total',[6400,5800,6000])
async def test_naik_turun_sama_mencatat_kumulatif_lama(pg,hasil,total):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'hasil',total=total);r=await post(c,pr,'hasil','simpan',b);assert r.status_code==200,r.text
  f=await fakta(pg,pr);assert len(f['logs'])==2 and float(f['logs'][-1][0])==total
  assert f['stok'].produced==total and f['stok'].tersedia==total
  before=await fakta(pg,pr);assert (await post(c,pr,'hasil','simpan',b)).status_code==409;assert await fakta(pg,pr)==before

async def test_verifikasi_admin_tidak_ditimpa_hasil_atau_selesai(pg,hasil):
 u,pr,_=hasil
 async with pg() as db:await m.verify_milling_output(db,user=u,kode_proses=pr.kode_proses,berat_output=5900)
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'hasil',total=6200);r=await post(c,pr,'hasil','simpan',b);assert r.status_code==200,r.text
  d=(await c.get(url(pr))).json();assert d['tercatat']==6200 and d['terverifikasi']==5900 and d['dasar_stok']==5900
  await lepas(pg,u,pr);b=await preview(c,pr,'selesai',akhir=6400);assert (await post(c,pr,'selesai','simpan',b)).status_code==200
  d=(await c.get(url(pr))).json();assert not d['aktif'] and d['tercatat']==6400 and d['terverifikasi']==5900 and d['stok_sebelum']==5900
  assert (await c.get('/proses-aktif/giling/'+pr.kode_proses)).status_code==200

@pytest.mark.parametrize('total',[None,6500])
async def test_hasil_akhir_opsional_atau_tetapkan_tanpa_ulang_stok(pg,hasil,total):
 u,pr,_=hasil;await lepas(pg,u,pr)
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'selesai',akhir=total);r=await post(c,pr,'selesai','simpan',b);assert r.status_code==200,r.text
  d=(await c.get(url(pr))).json();assert d['tercatat']==(6000 if total is None else total) and not d['aktif']
  assert [s['sisa'] for s in d['sumber']]==[0,500]
  before=await fakta(pg,pr);assert (await post(c,pr,'selesai','simpan',b)).status_code==409;assert await fakta(pg,pr)==before

async def test_hasil_belum_ada_dapat_diisi_saat_selesai(pg,hasil):
 u,pr,_=hasil
 async with pg() as db:await db.execute(delete(MillingProgressLog).where(MillingProgressLog.milling_process_id==pr.id));await db.commit()
 await lepas(pg,u,pr)
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(pr))).json();assert d['tercatat'] is None and not d['siap']
  assert (await post(c,pr,'selesai','periksa',{'dasar':d['dasar']})).status_code==409
  b=await preview(c,pr,'selesai',akhir=6100);assert (await post(c,pr,'selesai','simpan',b)).status_code==200
  assert (await c.get(url(pr))).json()['tercatat']==6100

async def test_jeda_tidak_ditutup_oleh_hasil_dan_akhir_tidak_melanjutkan_fiktif(pg,hasil):
 u,pr,_=hasil
 async with pg() as db:await jeda.hentikan(db,user=u,jenis='giling',kode=pr.kode_proses,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'hasil',total=6100);assert (await post(c,pr,'hasil','simpan',b)).status_code==200
  assert (await c.get(url(pr))).json()['jeda'];await lepas(pg,u,pr)
  b=await preview(c,pr,'selesai');assert (await post(c,pr,'selesai','simpan',b)).status_code==200
 async with pg() as db:
  from app.models import JedaCatatan
  assert (await db.scalars(select(JedaCatatan.aksi))).all()==['hentikan','akhir_proses']

async def test_qc_seluruh_putaran_null_nol_rata_warna_dan_tidak_mutasi_stok(pg,hasil):
 from app.services.mutu_pk import penilaian_dari_log
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  for air in [None,0,14]:
   q=dict(kode_proses=pr.kode_proses,kadar_air=air,broken=20,susut=12,butir_kuning='bersih',gabah='sedang',merang='parah',catatan_lab='Catatan '+str(air))
   if air==0:
    # Nol pada catatan historis tetap dihitung; endpoint lama sendiri
    # memakai PersenOpsional >0, dan tidak dilonggarkan oleh tampilan.
    d=(await c.get(url(pr))).json();assert (await post(c,pr,'qc','periksa',{'dasar':d['dasar'],'qc':q})).status_code==422
    async with pg() as db:await m.log_qc_milling(db,user=u,kondisi=None,**q)
   else:
    b=await preview(c,pr,'qc',qc=q);r=await post(c,pr,'qc','simpan',b);assert r.status_code==200,r.text
  d=(await c.get(url(pr))).json();assert d['qc']['putaran']==3 and d['qc']['rows'][0]['hasil']=='7,0%' and d['qc']['rows'][0]['n']==2
  assert len(d['riwayat_qc'])==3 and d['stok_sebelum']==6000
  assert [q['nilai']['kadar_air'] for q in d['riwayat_qc']]==[None,0,14]
  assert '#D5EBD1' in d['qc']['rows'][3]['gaya'] and '#FFD0A0' in d['qc']['rows'][4]['gaya'] and '#F5B5AF' in d['qc']['rows'][5]['gaya']
  async with pg() as db:assert d['qc']['nilai']==penilaian_dari_log((await db.scalars(select(MillingQcLog))).all())['nilai']

async def test_snapshot_data_hasil_atau_verifikasi_berubah(pg,hasil):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'hasil',total=6100)
  async with pg() as db:await m.verify_milling_output(db,user=u,kode_proses=pr.kode_proses,berat_output=5900)
  before=await fakta(pg,pr);assert (await post(c,pr,'hasil','simpan',b)).status_code==409;assert await fakta(pg,pr)==before

async def test_konkuren_satu_log_berdasar_snapshot_yang_sama(pg,hasil):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'hasil',total=6100)
  rs=await asyncio.gather(post(c,pr,'hasil','simpan',b),post(c,pr,'hasil','simpan',b));assert sorted(r.status_code for r in rs)==[200,409]
  assert len((await fakta(pg,pr))['logs'])==2

@pytest.mark.parametrize('role,view,wh,ok,qcok',[('superadmin',None,'Gudang 1',True,True),('admin',None,'Gudang 1',True,True),('operator',None,'Gudang 1',True,False),('admin','operator:g1','Gudang 1',True,False),('operator',None,'Gudang 2',False,False),('admin','operator:g2','Gudang 2',False,False),('staff',None,'Gudang 1',False,False)])
async def test_hak_efektif_dan_izin_qc_lama(pg,hasil,role,view,wh,ok,qcok):
 from app.web.lihat_sebagai import NAMA_KUKI
 u,pr,_=hasil
 async with await _klien(pg,peran=role,gudang=wh) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  r=await c.get(url(pr));assert r.status_code==(200 if ok else 403)
  d=r.json() if ok else {};assert not ok or d['boleh_qc']==qcok
  body={'dasar':d.get('dasar','palsu'),'total':6100};assert (await post(c,pr,'hasil','periksa',body)).status_code==(200 if ok else 403)
  body={'dasar':d.get('dasar','palsu'),'qc':dict(kode_proses=pr.kode_proses,butir_kuning='bersih',gabah='bersih',merang='bersih')}
  assert (await post(c,pr,'qc','periksa',body)).status_code==(200 if qcok else 403)

from tests.pg.test_form_tambah_silo_giling import mix,snapshot

async def test_mix_satu_silo_banyak_batch_tetap_jeda_dan_tolak_snapshot_baru(pg,mix,g1):
 u,pr,_=mix
 async with pg() as db:await jeda.hentikan(db,user=u,jenis='giling',kode=pr.kode_proses,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'mix',silo='TONG SELATAN')
  await _isi_silo_g1(pg,g1,huruf='TONG SELATAN',kode='GB-MIX-SETELAH',kg=300)
  before=await snapshot(pg);assert (await post(c,pr,'mix','simpan',b)).status_code==409;assert await snapshot(pg)==before
  b=await preview(c,pr,'mix',silo='TONG SELATAN');r=await post(c,pr,'mix','simpan',b);assert r.status_code==200,r.text
  d=(await c.get(url(pr))).json();assert d['jeda'] and d['tercatat']==6000 and len(d['sumber'])==5

async def test_bebaskan_sumber_tepat_tidak_menutup_mesin_dan_siklus_baru(pg,hasil,g1):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(pr))).json();a=next(u for u in d['silos_aktif'] if u['silo']=='Silo A')
  before=await fakta(pg,pr);r=await post(c,pr,'bebaskan','periksa',{'dasar':d['dasar'],'silo':a['silo'],'sumber_ids':[99999],'sisa':0});assert r.status_code==409;assert await fakta(pg,pr)==before
  b=await preview(c,pr,'bebaskan',silo=a['silo'],sumber_ids=a['ids'],sisa=0);assert (await post(c,pr,'bebaskan','simpan',b)).status_code==200
  d=(await c.get(url(pr))).json();assert d['aktif'] and d['tercatat']==6000
  await _isi_silo_g1(pg,g1,huruf='A',kode='GB-SIKLUS-BARU',kg=600)
  b=await preview(c,pr,'mix',silo='A');assert (await post(c,pr,'mix','simpan',b)).status_code==200
  d=(await c.get(url(pr))).json();assert d['sumber'][0]['sisa']==0 and d['sumber'][-1]['bobot']==600 and d['sumber'][-1]['id']!=a['ids'][0]

@pytest.mark.parametrize('known',[True,False])
async def test_bobot_sementara_tidak_ditambah_larangan_selesai(pg,hasil,known):
 from app.models import PurchaseBatch
 u,pr,_=hasil
 async with pg() as db:
  p=await db.get(MillingProcess,pr.id);p.bobot_masuk_final=False;p.berat_gabah_masuk_kg=10000 if known else None
  for s in (await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id))).all():
   if not known:s.berat_kg=None
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(pr))).json();assert not d['bobot_final']
  if not known:assert d['bobot_acuan'] is None and d['rendemen'] is None
  for u_ in d['silos_aktif']:
   b=await preview(c,pr,'bebaskan',silo=u_['silo'],sumber_ids=u_['ids'],sisa=0);assert (await post(c,pr,'bebaskan','simpan',b)).status_code==200
  b=await preview(c,pr,'selesai',akhir=11000);assert (await post(c,pr,'selesai','simpan',b)).status_code==200
  assert not (await c.get(url(pr))).json()['aktif']

async def test_csrf_cap_konfirmasi_tamper_dan_qc_proses_lain(pg,hasil):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(pr))).json();before=await fakta(pg,pr)
  body={'dasar':d['dasar'],'total':6100}
  assert (await c.post(url(pr,'hasil','simpan'),json=body)).status_code==403
  assert (await post(c,pr,'hasil','simpan',body)).status_code==409
  b=await preview(c,pr,'hasil',total=6100)
  assert (await post(c,pr,'hasil','simpan',{**b,'konfirmasi':False})).status_code==400
  assert (await post(c,pr,'hasil','simpan',{**b,'total':6200})).status_code==409
  q=dict(kode_proses='PROSES-PELANGGAN-LAIN',butir_kuning='bersih',gabah='bersih',merang='bersih')
  assert (await post(c,pr,'qc','periksa',{'dasar':d['dasar'],'qc':q})).status_code==400
  assert await fakta(pg,pr)==before

async def test_presisi_database_di_pratinjau_dan_log_lama(pg,hasil):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(pr))).json();body={'dasar':d['dasar'],'total':6500.125}
  r=await post(c,pr,'hasil','periksa',body);assert r.status_code==200,r.text
  assert r.json()['rencana']['tersimpan']==6500.13
  body.update(pemeriksaan=r.json()['pemeriksaan'],konfirmasi=True)
  assert (await post(c,pr,'hasil','simpan',body)).status_code==200
  assert (await fakta(pg,pr))['logs'][-1][0]==pytest.approx(6500.13)

async def test_gagal_sebelum_commit_rollback_log_dan_saldo(pg,hasil,monkeypatch):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'hasil',total=6100);before=await fakta(pg,pr)
  async def gagal(db,**kw):
   from app.database import now_local
   db.add(MillingProgressLog(milling_process_id=pr.id,berat_kumulatif_kg=6100,input_by=u.id,waktu_update=now_local()))
   await db.flush();raise m.MillingError('Kegagalan uji sebelum commit')
  monkeypatch.setattr(m,'log_progress',gagal)
  assert (await post(c,pr,'hasil','simpan',b)).status_code==409
  assert await fakta(pg,pr)==before

async def test_selesai_menutup_semua_tindakan_aktif_dan_qc_lanjutan_izin_lama(pg,hasil):
 u,pr,_=hasil;await lepas(pg,u,pr)
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,pr,'selesai');assert (await post(c,pr,'selesai','simpan',b)).status_code==200
  d=(await c.get(url(pr))).json();before=await fakta(pg,pr)
  for act in ['hasil','mix','bebaskan','selesai']:
   assert (await post(c,pr,act,'periksa',{'dasar':d['dasar'],'total':6100})).status_code==409
  assert await fakta(pg,pr)==before
  q=dict(kode_proses=pr.kode_proses,butir_kuning='bersih',gabah='bersih',merang='bersih')
  b=await preview(c,pr,'qc',qc=q);assert (await post(c,pr,'qc','simpan',b)).status_code==200
  assert (await c.get(url(pr))).json()['qc']['putaran']==1

async def test_korelasi_pemeriksaan_qc_memakai_nilai_database_dan_label_normal(pg,hasil):
 u,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(pr))).json()
  q=dict(kode_proses=pr.kode_proses,kadar_air=14.125,broken=21.456,susut=11.555,butir_kuning='Sedikit',gabah='bersih',merang='bersih',catatan_lab='  Lab uji  ')
  body={'dasar':d['dasar'],'qc':q};r=await post(c,pr,'qc','periksa',body);assert r.status_code==200,r.text
  expected=r.json()['rencana']['qc_tersimpan'];body.update(pemeriksaan=r.json()['pemeriksaan'],konfirmasi=True)
  assert (await post(c,pr,'qc','simpan',body)).status_code==200
  d=(await c.get(url(pr))).json();assert d['riwayat_qc'][-1]['nilai']==expected
