"""Form G1 baru membaca siklus lama, menyimpan melalui layanan/token lama."""
import asyncio
import pytest
from sqlalchemy import select,func
from tests.pg.test_form_hasil_penggilingan import hasil,g1,_isi_silo_g1,fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from app.models import MillingProcess,MillingProcessSource,MillingProgressLog,User,ActivityLog,Silo,SiloStorage,Warehouse
from app.penggilingan.gudang1.services import milling as m
pytestmark=pytest.mark.asyncio
async def baca(c,p,silo='A',sisa=500):
 q=dict(kode_proses=p.kode_proses,silo=silo)
 if sisa is not None:q['sisa']=sisa
 return await c.get('/api/actions/ringkasan-bebaskan-silo-giling',params=q)
async def periksa(c,p,silo='A',sisa=500):
 return await c.get('/api/actions/pratinjau-bebaskan-silo',params=dict(jenis='giling',kode_proses=p.kode_proses,silo=silo,sisa=sisa))
async def simpan(c,p,sisa,token,silo='A'):
 return await c.post('/api/actions/tutup-silo-giling',json=dict(kode_proses=p.kode_proses,silo=silo,sisa=sisa,dasar=token),headers={'X-CSRF-Token':cap_formulir(c)})
async def test_kontrak_dan_reader_tanpa_mutasi_semua_sumber(pg,hasil,g1):
 u,p,_=hasil
 await _isi_silo_g1(pg,g1,huruf='A',kode='GB-TAMBAHAN-BS',kg=300)
 async with pg() as db:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['A'])
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='tutup_silo_giling')
  assert [f['name'] for f in a['fields']]==['kode_proses','silo','sisa'];assert a['pratinjau_silo']=='giling' and a['post']=='/api/actions/tutup-silo-giling'
  assert (await c.get('/api/actions/silo-giling-terbuka')).json()==[]
  r=await baca(c,p);assert r.status_code==200,r.text;d=r.json();assert d['bahan']==6300 and d['terpakai']==5800 and len(d['sumber'])==2
  assert r.headers['cache-control']=='no-store'
  token=(await periksa(c,p)).json();assert token['rincian']['bahan']==6300 and token['dasar']
 assert await fakta(pg,p)==before
@pytest.mark.parametrize('sisa',[0,500,6000,500.25])
async def test_sisa_nol_positif_seluruh_dan_presisi_pk_tetap(pg,hasil,sisa):
 u,p,_=hasil;before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  token=(await periksa(c,p,sisa=sisa)).json()['dasar'];r=await simpan(c,p,sisa,token);assert r.status_code==200,r.text
  d=(await baca(c,p)).json();assert not d['terbuka'];assert d['status']=='berjalan' and d['hasil_pk']==6000 and d['stok_pk']==6000
  assert (await simpan(c,p,sisa,token)).status_code==400
 after=await fakta(pg,p);assert after['logs']==before['logs'] and after['stok']==before['stok'] and after['status']=='proses'
 async with pg() as db:
  rows=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id).order_by(MillingProcessSource.id))).all()
  a,b=rows;assert float(a.berat_akhir_kg)==sisa and float(a.berat_terpakai_kg)==6000-sisa and b.berat_akhir_kg is None
  st=await db.get(SiloStorage,a.silo_storage_id);assert st.milling_process_id is None and st.status==('kosong' if sisa==0 else 'terisi')
  other=await db.get(SiloStorage,b.silo_storage_id);assert other.milling_process_id==p.id
  audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='milling_process_sources',ActivityLog.record_id==a.id));assert audit and audit.changed_by and audit.waktu_perubahan
@pytest.mark.parametrize('sisa',[None,'',-1,'NaN','Infinity','1.000,25',6001])
async def test_tidak_sah_tanpa_perubahan(pg,hasil,sisa):
 u,p,_=hasil;before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  r=await simpan(c,p,sisa,'token');assert r.status_code in (400,409,422),r.text
 assert await fakta(pg,p)==before
async def test_bobot_belum_diketahui_dan_sementara_bukan_nol(pg,hasil):
 u,p,_=hasil
 async with pg() as db:
  src=await db.scalar(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id).order_by(MillingProcessSource.id));src.berat_kg=None
  pr=await db.get(MillingProcess,p.id);pr.bobot_masuk_final=False;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,p)).json();assert d['bahan'] is None and d['terpakai'] is None
  assert (await periksa(c,p,sisa=1)).status_code==409
  token=(await periksa(c,p,sisa=0)).json()['dasar'];assert (await simpan(c,p,0,token)).status_code==200
 async with pg() as db:
  row=await db.get(MillingProcessSource,src.id);assert row.berat_terpakai_kg is None and float(row.berat_akhir_kg)==0
async def test_jeda_dan_silo_terakhir_tidak_menutup_proses_legacy_tunggal(pg,hasil):
 from app.penggilingan.gudang1.services import jeda as j
 u,p,_=hasil
 async with pg() as db:await j.hentikan(db,user=u,jenis='giling',kode=p.kode_proses,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  assert (await baca(c,p)).json()['status']=='dijeda'
  assert (await periksa(c,p,silo='',sisa=0)).status_code==409
  token=(await periksa(c,p,sisa=0)).json()['dasar'];assert (await simpan(c,p,0,token)).status_code==200
  r=await periksa(c,p,silo='',sisa=500);assert r.status_code==200,r.text;assert r.json()['rincian']['silo']=='Silo B'
  assert (await simpan(c,p,500,r.json()['dasar'],silo='')).status_code==200
 async with pg() as db:
  assert await j.jeda_terbuka(db,'giling',p.id) is not None
  proc=await db.get(MillingProcess,p.id);assert proc.status=='proses' and proc.waktu_selesai is None
async def test_dua_konfirmasi_hanya_satu_audit(pg,hasil):
 from app.services.penyelesaian_proses import ringkasan_bebaskan
 u,p,_=hasil
 async with pg() as db:token=(await ringkasan_bebaskan(db,jenis='giling',kode=p.kode_proses,silo='A',sisa=500))['dasar']
 async def lepas():
  async with pg() as db:
   try:await m.tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='A',sisa_kg=500,dasar=token);return 'ok'
   except m.MillingError:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(lepas(),lepas()))==['ditolak','ok']
 async with pg() as db:
  row=await db.scalar(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id).order_by(MillingProcessSource.id));assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='milling_process_sources',ActivityLog.record_id==row.id))==1
@pytest.mark.parametrize('peran,view,gudang,izin',[('admin',None,'Gudang 1',True),('superadmin',None,'Gudang 1',True),('operator',None,'Gudang 1',True),('admin','operator:g1','Gudang 1',True),('operator',None,'Gudang 2',False),('admin','operator:g2','Gudang 2',False),('superadmin','operator:g2','Gudang 2',False),('staff',None,'Gudang 1',False)])
async def test_hak_efektif_reader_preview_post(pg,hasil,peran,view,gudang,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 u,p,_=hasil
 async with pg() as db:
  if not await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2')):db.add(Warehouse(nama_gudang='Gudang 2 - Polesan',kode_fungsi='g2'))
  await db.commit()
 before=await fakta(pg,p)
 async with await _klien(pg,peran=peran,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  assert (await baca(c,p)).status_code==(200 if izin else 403)
  r=await periksa(c,p);assert r.status_code==(200 if izin else 403),r.text
  assert (await simpan(c,p,500,r.json().get('dasar','token'))).status_code==(200 if izin else 403)
 if not izin:assert await fakta(pg,p)==before
async def test_csrf_anonim_proses_hilang_token_wajib(pg,hasil):
 import httpx
 from app.main import app
 u,p,_=hasil;before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  assert (await c.post('/api/actions/tutup-silo-giling',json=dict(kode_proses=p.kode_proses,silo='A',sisa=0,dasar='token'))).status_code==403
  assert (await simpan(c,p,0,'')).status_code==409
  assert (await c.get('/api/actions/ringkasan-bebaskan-silo-giling',params=dict(kode_proses='hilang'))).status_code==400
  assert (await periksa(c,p,silo='Z')).status_code==409
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  assert (await baca(c,p)).status_code==401
  assert (await periksa(c,p)).status_code==401
 assert await fakta(pg,p)==before

async def test_reader_siklus_baru_token_lama_ditolak_dan_fifo(pg,hasil,g1):
 u,p,_=hasil
 async with await _klien(pg,peran='admin') as c:
  token=(await periksa(c,p,sisa=0)).json()['dasar'];assert (await simpan(c,p,0,token)).status_code==200
  await _isi_silo_g1(pg,g1,huruf='A',kode='GB-SIKLUS-BARU-BS',kg=300)
  async with pg() as db:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['A'])
  d=(await baca(c,p,sisa=50)).json();assert d['bahan']==300 and len(d['sumber'])==1 and len(d['sumber_proses'])==3
  before=await fakta(pg,p);r=await simpan(c,p,0,token);assert r.status_code==400 and 'berubah' in r.text;assert await fakta(pg,p)==before
  token=(await periksa(c,p,sisa=50)).json()['dasar'];assert (await simpan(c,p,50,token)).status_code==200
  d=(await baca(c,p)).json();assert d['silo_sekarang'][0]['bobot']=='50 kg'

async def test_gagal_audit_rollback_seluruh_sumber_tanpa_sisa_setengah(pg,hasil,g1,monkeypatch):
 u,p,_=hasil
 await _isi_silo_g1(pg,g1,huruf='A',kode='GB-ROLLBACK-BS',kg=300)
 async with pg() as db:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['A'])
 before=await fakta(pg,p)
 async def gagal(*a,**kw):raise RuntimeError('Gangguan audit uji')
 monkeypatch.setattr(m,'log_activity',gagal)
 async with pg() as db:
  with pytest.raises(RuntimeError):await m.tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='A',sisa_kg=500)
  await db.rollback()
 assert await fakta(pg,p)==before
 async with pg() as db:
  rows=(await db.scalars(select(SiloStorage).join(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id))).all()
  assert len(rows)==3 and all(x.milling_process_id==p.id and x.status=='terisi' for x in rows)

async def test_bobot_sementara_angka_tetap_divalidasi_dan_proses_selesai(pg,hasil):
 u,p,_=hasil
 async with pg() as db:pr=await db.get(MillingProcess,p.id);pr.bobot_masuk_final=False;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,p)).json();assert d['bahan']==6000 and d['bobot_final'] is False
  assert (await periksa(c,p,sisa=6001)).status_code==409
  token=(await periksa(c,p,sisa=6000)).json()['dasar'];assert (await simpan(c,p,6000,token)).status_code==200
  async with pg() as db:pr=await db.get(MillingProcess,p.id);pr.status='selesai';await db.commit()
  assert (await baca(c,p,silo='B')).json()['status']=='selesai'
  assert (await periksa(c,p,silo='B')).status_code==409
  assert (await simpan(c,p,0,'token',silo='B')).status_code==400

async def test_portal_pelanggan_tidak_membaca_atau_mencatat(pg,hasil):
 import httpx
 from app.main import app
 from app.models import Jasa
 from app.models.portal import PortalAccount
 from app.web.portal.security import COOKIE,issue
 from app.web import csrf,security
 u,p,jid=hasil
 async with pg() as db:
  pr=await db.get(MillingProcess,p.id);pr.jasa_id=jid;jasa=await db.get(Jasa,jid)
  account=PortalAccount(username='uji-bebaskan-giling',pelanggan_id=jasa.pelanggan_id,password_hash=security.hash_sandi('uji-aman-123'),active=True,token_version=1);db.add(account);await db.commit()
 before=await fakta(pg,p)
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  c.cookies.set(COOKIE,issue(account));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
  for r in [await baca(c,p),await periksa(c,p),await simpan(c,p,500,'token')]:assert r.status_code in (401,403)
 assert await fakta(pg,p)==before

async def test_sumber_lama_tidak_dipulihkan_oleh_pembaca(pg,hasil):
 from sqlalchemy import delete
 u,p,_=hasil
 async with pg() as db:
  await db.execute(delete(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id))
  pr=await db.get(MillingProcess,p.id);pr.silo_storage_id=None;await db.commit()
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,p)).json();assert d['sumber']==[] and not d['terbuka'] and d['bahan'] is None
  assert (await periksa(c,p,sisa=0)).status_code==409
 async with pg() as db:
  with pytest.raises(m.MillingError,match='tidak dapat dipastikan'):await m.tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='A',sisa_kg=0)
  await db.rollback()
 assert await fakta(pg,p)==before
