"""Penyelesaian dua tahap pada PG lokal; reader tidak mengubah proses/stok."""
import asyncio
import pytest
from sqlalchemy import select,delete,func
from tests.pg.test_form_hasil_penggilingan import hasil,g1,_isi_silo_g1,fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from app.models import MillingProcess,MillingProcessSource,MillingProgressLog,MillingProcessVerification,User,ActivityLog,Silo,SiloStorage
from app.penggilingan.gudang1.services import milling as m
pytestmark=pytest.mark.asyncio

async def lepas(pg,u,p):
 async with pg() as db:
  await m.tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='A',sisa_kg=0)
  await m.tutup_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='B',sisa_kg=500)

async def konteks(c,p,total=None):
 q={'kode_proses':p.kode_proses}
 if total is not None:q['berat_akhir']=total
 return await c.get('/api/actions/ringkasan-selesai-giling',params=q)
async def periksa(c,p,total=None):
 q={'jenis':'giling','kode_proses':p.kode_proses}
 if total is not None:q['berat_akhir']=total
 return await c.get('/api/actions/pratinjau-selesai-proses',params=q)
async def simpan(c,p,total,token):
 return await c.post('/api/actions/selesai-giling',json={'kode_proses':p.kode_proses,'berat_akhir':total,'dasar':token},headers={'X-CSRF-Token':cap_formulir(c)})

async def test_reader_kontrak_baca_saja_dan_semua_sumber(pg,hasil):
 u,p,_=hasil;before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  menu=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='selesai_giling')
  assert [x['name'] for x in menu['fields']]==['kode_proses','berat_akhir']
  assert menu['post']=='/api/actions/selesai-giling' and menu['pratinjau_proses']=='giling'
  r=await konteks(c,p,6400);assert r.status_code==200,r.text
  d=r.json();assert r.headers['cache-control']=='no-store'
  assert d['tercatat']==6000 and d['hasil_akhir']==6400 and d['perubahan']==400
  assert d['stok_sesudah']==6400 and d['sisa_lengkap'] is False
  assert len(d['sumber'])==2 and all(x['sisa'] is None for x in d['sumber'])
  assert (await periksa(c,p,6400)).status_code==409
 assert await fakta(pg,p)==before
 await lepas(pg,u,p);before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  r=await periksa(c,p,6400);assert r.status_code==200,r.text
  d=r.json();assert d['dasar'] and d['rincian']['terpakai']==9500
  assert [x['sisa'] for x in d['rincian']['sumber']]==[0,500]
 assert await fakta(pg,p)==before

@pytest.mark.parametrize('total,nlog',[(None,1),(6000,1),(6400,2),(5800,2),(6400.125,2)])
async def test_hasil_akhir_kumulatif_kosong_sama_turun_presisi(pg,hasil,total,nlog):
 u,p,_=hasil;await lepas(pg,u,p)
 async with await _klien(pg,peran='admin') as c:
  r=await periksa(c,p,total);assert r.status_code==200,r.text
  token=r.json()['dasar'];r=await simpan(c,p,total,token);assert r.status_code==200,r.text
  assert r.json()['ok'];assert (await simpan(c,p,total,token)).status_code==400
  d=(await konteks(c,p)).json();assert d['status']=='selesai' and d['detail']==f'/riwayat-giling/{p.id}'
 f=await fakta(pg,p);assert len(f['logs'])==nlog
 from decimal import Decimal,ROUND_HALF_UP
 expected=float(Decimal(str(total or 6000)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
 assert f['stok'].produced==expected and f['stok'].tersedia==expected
 assert f['status']=='selesai'
 async with pg() as db:
  from app.penggilingan.gudang1.services.silo import _silo_content_bobot
  for name,kg in [('Silo A',0),('Silo B',500)]:
   sid=await db.scalar(select(Silo.id).join(SiloStorage).join(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id,Silo.nama_silo==name));assert (await _silo_content_bobot(db,sid)).kg==kg
  audits=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='milling_process',ActivityLog.record_id==p.id))).all()
  assert any(x.changed_by and x.waktu_perubahan and x.new_value=='selesai' for x in audits)

@pytest.mark.parametrize('total',[0,-1,'NaN','Infinity','6.400,1'])
async def test_tidak_sah_tidak_menulis(pg,hasil,total):
 u,p,_=hasil;await lepas(pg,u,p);before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  r=await simpan(c,p,total,'token');assert r.status_code in (400,409,422),r.text
  if total!='6.400,1':assert (await periksa(c,p,total)).status_code in (409,422)
 assert await fakta(pg,p)==before

async def test_hasil_operator_wajib_meski_sudah_verifikasi_admin(pg,hasil):
 u,p,_=hasil;await lepas(pg,u,p)
 async with pg() as db:
  await db.execute(delete(MillingProgressLog).where(MillingProgressLog.milling_process_id==p.id))
  db.add(MillingProcessVerification(milling_process_id=p.id,berat_output_final_kg=5900,verified_by=u.id));await db.commit()
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  d=(await konteks(c,p)).json();assert d['tercatat'] is None and d['hasil_akhir'] is None and d['stok_sesudah'] is None
  assert d['terverifikasi']==5900
  assert (await periksa(c,p)).status_code==409
 assert await fakta(pg,p)==before

@pytest.mark.parametrize('total,final,ditolak',[(10000,True,True),(9500,True,True),(9600,True,True),(9500,False,False),(10001,False,False)])
async def test_batas_final_terpakai_dan_sementara(pg,hasil,total,final,ditolak):
 u,p,_=hasil;await lepas(pg,u,p)
 async with pg() as db:
  proc=await db.get(MillingProcess,p.id);proc.bobot_masuk_final=final
  if not final:proc.berat_gabah_masuk_kg=None
  await db.commit()
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  d=(await konteks(c,p,total)).json();assert d['bobot_final']==final
  if not final:assert d['bobot_acuan'] is None
  r=await periksa(c,p,total);assert r.status_code==(409 if ditolak else 200),r.text
  if not ditolak:assert (await simpan(c,p,total,r.json()['dasar'])).status_code==200
 if ditolak:assert await fakta(pg,p)==before

@pytest.mark.parametrize('ubah',['progres','sumber','pemilik'])
async def test_token_basi_tidak_menyelesaikan(pg,hasil,ubah):
 u,p,jid=hasil;await lepas(pg,u,p)
 async with await _klien(pg,peran='admin') as c:
  token=(await periksa(c,p,6400)).json()['dasar']
  async with pg() as db:
   if ubah=='progres':await m.log_progress(db,user=u,kode_proses=p.kode_proses,berat_kumulatif=6100)
   elif ubah=='sumber':
    src=await db.scalar(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id));src.berat_akhir_kg=100;await db.commit()
   else:
    pr=await db.get(MillingProcess,p.id);pr.jasa_id=jid;await db.commit()
  before=await fakta(pg,p);r=await simpan(c,p,6400,token)
  assert r.status_code==400 and 'berubah' in r.text,r.text
  assert await fakta(pg,p)==before

async def test_dua_konfirmasi_bersamaan_hanya_satu_penyelesaian(pg,hasil):
 from app.services.penyelesaian_proses import ringkasan_selesai
 u,p,_=hasil;await lepas(pg,u,p)
 async with pg() as db:token=(await ringkasan_selesai(db,jenis='giling',kode=p.kode_proses,berat_akhir=6400))['dasar']
 async def finish():
  async with pg() as db:
   try:await m.finish_milling(db,user=u,kode_proses=p.kode_proses,berat_akhir=6400,dasar=token);return 'ok'
   except m.MillingError:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(finish(),finish()))==['ditolak','ok']
 assert len((await fakta(pg,p))['logs'])==2

async def test_jeda_ditutup_tanpa_lanjut_dan_waktu_lama(pg,hasil):
 from app.penggilingan.gudang1.services import jeda as j
 from datetime import timedelta
 u,p,_=hasil;await lepas(pg,u,p)
 async with pg() as db:
  await j.hentikan(db,user=u,jenis='giling',kode=p.kode_proses,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  assert (await konteks(c,p)).json()['status']=='dijeda'
  token=(await periksa(c,p)).json()['dasar']
  assert (await simpan(c,p,None,token)).status_code==200
 async with pg() as db:
  assert await j.jeda_terbuka(db,'giling',p.id) is None
  pr=await db.get(MillingProcess,p.id);assert pr.waktu_selesai>=pr.waktu_mulai

@pytest.mark.parametrize('peran,view,gudang,izin',[('admin',None,'Gudang 1',True),('superadmin',None,'Gudang 1',True),('operator',None,'Gudang 1',True),('admin','operator:g1','Gudang 1',True),('operator',None,'Gudang 2',False),('admin','operator:g2','Gudang 2',False),('superadmin','operator:g2','Gudang 2',False),('staff',None,'Gudang 1',False)])
async def test_hak_efektif_tiga_endpoint(pg,hasil,peran,view,gudang,izin):
 from app.models import Warehouse
 from app.web.lihat_sebagai import NAMA_KUKI
 u,p,_=hasil;await lepas(pg,u,p)
 async with pg() as db:
  if not await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2')):db.add(Warehouse(nama_gudang='Gudang 2 - Polesan',kode_fungsi='g2'))
  await db.commit()
 before=await fakta(pg,p)
 async with await _klien(pg,peran=peran,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  r=await konteks(c,p);assert r.status_code==(200 if izin else 403),r.text
  r=await periksa(c,p,6400);assert r.status_code==(200 if izin else 403),r.text
  assert (await simpan(c,p,6400,r.json().get('dasar',''))).status_code==(200 if izin else 403)
 if not izin:assert await fakta(pg,p)==before

async def test_anonim_csrf_kode_kosong_token_wajib(pg,hasil):
 import httpx
 from app.main import app
 u,p,_=hasil;await lepas(pg,u,p);before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  assert (await c.post('/api/actions/selesai-giling',json={'kode_proses':p.kode_proses})).status_code==403
  assert (await simpan(c,p,None,'')).status_code==409
  assert (await c.get('/api/actions/ringkasan-selesai-giling',params={'kode_proses':'tidak-ada'})).status_code==400
  assert (await c.get('/api/actions/pratinjau-selesai-proses',params={'jenis':'giling','kode_proses':''})).status_code==409
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  assert (await konteks(c,p)).status_code==401
  assert (await periksa(c,p)).status_code==401
  assert (await simpan(c,p,6400,'token')).status_code in (401,403)
 assert await fakta(pg,p)==before

@pytest.mark.parametrize('verified',[None,5900])
async def test_pratinjau_saldo_sama_dengan_helper_setelah_selesai(pg,hasil,verified):
 from app.models import InternalTransfer,OutgoingRecord,OutgoingItem,CustomerReturn,CustomerReturnItem
 from app.penggilingan.inventory.models import ReturRincian
 from app.database import now_local
 u,p,_=hasil;await lepas(pg,u,p);now=now_local()
 async with pg() as db:
  if verified is not None:db.add(MillingProcessVerification(milling_process_id=p.id,berat_output_final_kg=verified,verified_by=u.id))
  db.add_all([InternalTransfer(kode_transfer='TRF-SG-1',milling_process_id=p.id,berat_kg=1000,lokasi_tujuan='ditumpuk',waktu=now,created_by=u.id,status='terkirim'),InternalTransfer(kode_transfer='TRF-SG-2',milling_process_id=p.id,berat_kg=500,lokasi_tujuan='ditumpuk',waktu=now,created_by=u.id,status='dibatalkan')])
  out=OutgoingRecord(kode='OUT-SG',tanggal=now.date(),waktu=now,input_by=u.id,status='selesai');db.add(out);await db.flush()
  item=OutgoingItem(outgoing_record_id=out.id,item_type='pk_langsung',milling_process_id=p.id,berat_kg=1000);db.add(item);await db.flush()
  ret=CustomerReturn(kode='RET-SG',timbangan_transaksi_id=99999,kode_tiket='RTP-SG',berat_tiket_kg=100,berat_rincian_kg=100,selisih_kg=0,input_by=u.id,waktu=now);db.add(ret);await db.flush()
  db.add(CustomerReturnItem(customer_return_id=ret.id,outgoing_item_id=item.id,jumlah_karung=2,berat_total_kg=100))
  db.add(ReturRincian(timbangan_transaksi_id=99998,outgoing_record_id=out.id,muatan=[{'berat_kg':'999'}],input_by=u.id,status_pemeriksaan='menunggu_timbang'))
  await db.commit()
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  d=(await konteks(c,p,6400)).json();assert d['transfer']==1000 and d['penjualan']==1000 and d['retur']==100
  assert d['terverifikasi']==verified and d['stok_sesudah']==(verified or 6400)+100-1000-1000
  assert await fakta(pg,p)==before
  r=await periksa(c,p,6400);assert r.status_code==200,r.text
  assert r.json()['rincian']['stok_sesudah']==d['stok_sesudah']
  assert (await simpan(c,p,6400,r.json()['dasar'])).status_code==200
 after=await fakta(pg,p);assert after['stok'].tersedia==d['stok_sesudah']
 assert len(after['logs'])==len(before['logs'])+1 and after['stok'].transferred==1000

async def test_waktu_sebelum_mulai_ditolak_tanpa_progres_setengah_selesai(pg,hasil):
 from datetime import timedelta
 u,p,_=hasil;await lepas(pg,u,p);before=await fakta(pg,p)
 async with pg() as db:
  proc=await db.get(MillingProcess,p.id)
  with pytest.raises(m.MillingError):await m.finish_milling(db,user=u,kode_proses=p.kode_proses,berat_akhir=6400,tanggal=(proc.waktu_mulai-timedelta(days=1)).date(),jam=proc.waktu_mulai.time().replace(tzinfo=None))
  await db.rollback()
 assert await fakta(pg,p)==before

async def test_siklus_ulang_silo_tidak_disembunyikan_namanya(pg,hasil,g1):
 u,p,_=hasil;await lepas(pg,u,p)
 await _isi_silo_g1(pg,g1,huruf='A',kode='GB-SG-TAMBAHAN',kg=300)
 async with pg() as db:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['A'])
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  d=(await konteks(c,p,6400)).json();assert len(d['sumber'])==3 and len({x['id'] for x in d['sumber']})==3
  a=[x for x in d['sumber'] if x['silo']=='Silo A'];assert len(a)==2
  assert a[0]['sisa']==0 and a[1]['sisa'] is None and not d['sisa_lengkap']
  r=await periksa(c,p,6400);assert r.status_code==409 and 'Silo A' in r.text
 assert await fakta(pg,p)==before

async def test_portal_pelanggan_tidak_mendapat_konteks_atau_aksi(pg,hasil):
 import httpx
 from app.main import app
 from app.models import Jasa
 from app.models.portal import PortalAccount
 from app.web.portal.security import COOKIE,issue
 from app.web import csrf,security
 u,p,jid=hasil;await lepas(pg,u,p)
 async with pg() as db:
  pr=await db.get(MillingProcess,p.id);pr.jasa_id=jid;jasa=await db.get(Jasa,jid)
  account=PortalAccount(username='uji-selesai-giling',pelanggan_id=jasa.pelanggan_id,password_hash=security.hash_sandi('uji-aman-123'),active=True,token_version=1);db.add(account);await db.commit()
 before=await fakta(pg,p)
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  c.cookies.set(COOKIE,issue(account));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
  for r in [await konteks(c,p),await periksa(c,p,6400),await simpan(c,p,6400,'token')]:assert r.status_code in (401,403)
 assert await fakta(pg,p)==before
