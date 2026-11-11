"""Perjalanan nyata dengan PostgreSQL lokal: alokasi, timbang, buku stok dan balapan."""
from decimal import Decimal
import asyncio,json,uuid
import pytest
from sqlalchemy import select,text,func
from app.models import User,PermintaanPk,InternalTransfer,PengirimanPk,PengirimanPkItem
from app.services import pengiriman_pk as s,permintaan_pk as m,transfer
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_barang_keluar import _tiket
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def siap(pg,pabrik):
 async with pg() as db:
  r=await m.minta(db,user=await db.get(User,pabrik['op2']),kode_proses=pabrik['lot'],berat=6000);rid=r.id
 async with pg() as db:await s.setujui_banyak(db,user=await db.get(User,pabrik['admin']),items=[dict(permintaan_id=rid,berat_kg='6000',tujuan='ditumpuk')])
 return dict(**pabrik,rid=rid)

async def buat(pg,w,kg,kunci=None):
 async with pg() as db:return await s.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=w['rid'],berat_kg=kg)],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci=kunci or uuid.uuid4().hex)

async def tiket(pg,pid,berat):
 tid=await _tiket(pg,'TT-PK-'+str(pid),arah='TRANSFER',barang=Decimal(str(berat)))
 async with pg() as db:
  # Kolom kontrak dimiliki migrasi TeraFlow. Mirror uji PadiFlow hanya
  # menyediakan skema historis, maka dua kolom eksternal ditambahkan di fixture.
  await db.execute(text('ALTER TABLE timbangan_transaksi ADD COLUMN IF NOT EXISTS pengiriman_pk_id INTEGER'))
  await db.execute(text('ALTER TABLE timbangan_transaksi ADD COLUMN IF NOT EXISTS lintasan_transfer JSONB'))
  data=await s.rincian(db,pid);route=data['lintasan'];route['_pengiriman_pk']=dict(id=pid,sidik=data['sidik'])
  await db.execute(text('UPDATE timbangan_transaksi SET pengiriman_pk_id=:pid,lintasan_transfer=CAST(:route AS JSONB) WHERE id=:tid'),dict(pid=pid,tid=tid,route=json.dumps(route)));await db.commit()
 return tid

async def test_alokasi_perjalanan_sebagian_dan_penutupan_otomatis(pg,siap):
 w=siap
 async with pg() as db:assert await transfer.pending_transfer_kg(db,w['proses_id'])==0
 first=await buat(pg,w,'2000');second=await buat(pg,w,'4000')
 with pytest.raises(s.PengirimanError,match='sisa'):await buat(pg,w,'1')
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0
  r=await db.get(PermintaanPk,w['rid']);assert r.berat_kirim_kg==6000
 for j,weight in [(first,Decimal('1999')),(second,Decimal('4000'))]:
  tid=await tiket(pg,j['id'],weight)
  async with pg() as db:
   result=await s.sinkron(db,pid=j['id'],tid=tid);assert result['status']=='selesai'
  async with pg() as db:assert (await s.sinkron(db,pid=j['id'],tid=tid))['ulang']
 async with pg() as db:
  r=await db.get(PermintaanPk,w['rid']);assert r.status=='selesai' and r.berat_final_kg==6000
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==6000
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==2
  assert await transfer.saldo_pk(db,w['proses_id'])==0

@pytest.mark.parametrize('berat,expected',[('1990','menunggu_admin'),('2010','menunggu_admin'),('1990.01','selesai'),('2009.99','selesai')])
async def test_batas_kurang_dari_setengah_persen_bukan_sama_dengan(pg,siap,berat,expected):
 w=siap;j=await buat(pg,w,'2000');tid=await tiket(pg,j['id'],berat)
 async with pg() as db:assert (await s.sinkron(db,pid=j['id'],tid=tid))['status']==expected
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==(1 if expected=='selesai' else 0)
  if expected=='menunggu_admin':
   result=await s.sinkron(db,pid=j['id'],tid=tid,user=await db.get(User,w['admin']),alasan='Muatan asal sudah diperiksa; selisih diterima per perjalanan.');assert result['status']=='selesai'
   assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==2000

async def test_balapan_dan_nonce_tidak_menggandakan_muatan(pg,siap):
 w=siap;key=uuid.uuid4().hex
 results=await asyncio.gather(buat(pg,w,'4000',key),buat(pg,w,'4000',key))
 assert results[0]['id']==results[1]['id']
 with pytest.raises(s.PengirimanError,match='berbeda'):await buat(pg,w,'3000',key)
 results=await asyncio.gather(buat(pg,w,'2000'),buat(pg,w,'2000'),return_exceptions=True)
 assert sum(isinstance(r,s.PengirimanError) for r in results)==1
 async with pg() as db:assert await db.scalar(select(func.sum(PengirimanPkItem.berat_kg)))==6000

async def test_operator_tujuan_tidak_bisa_membuat_pengiriman(pg,siap):
 w=siap
 async with pg() as db:
  with pytest.raises(PermissionError):await s.buat(db,user=await db.get(User,w['op2']),items=[dict(permintaan_id=w['rid'],berat_kg='1000')],nomor_polisi='K 1 A',nama_sopir='Kasidi',kunci=uuid.uuid4().hex)

async def lot_lain(pg,w):
 from app.models import MillingProcess,MillingProgressLog
 from app.database import now_local
 async with pg() as db:
  old=await db.get(MillingProcess,w['proses_id'])
  p=MillingProcess(kode_proses='LOT-LAIN',status='selesai',silo_id=old.silo_id,berat_gabah_masuk_kg=5000,waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=w['op1']);db.add(p);await db.flush()
  db.add(MillingProgressLog(milling_process_id=p.id,berat_kumulatif_kg=3000,waktu_update=now_local(),input_by=w['op1']));await db.commit()
 async with pg() as db:r=await m.minta(db,user=await db.get(User,w['op2']),kode_proses='LOT-LAIN',berat=3000)
 return r.id

async def test_multilot_satu_perjalanan_dan_rollback_seluruh_muatan(pg,siap):
 w=siap;rid=await lot_lain(pg,w)
 async with pg() as db:await s.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='3000',tujuan='ditumpuk')])
 async with pg() as db:j=await s.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=w['rid'],berat_kg='2000'),dict(permintaan_id=rid,berat_kg='1000')],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci=uuid.uuid4().hex)
 tid=await tiket(pg,j['id'],3000)
 async with pg() as db:assert (await s.sinkron(db,pid=j['id'],tid=tid))['status']=='selesai'
 async with pg() as db:
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==3000
  assert await s.sisa(db,await db.get(PermintaanPk,rid))==2000
  assert await s.sisa(db,await db.get(PermintaanPk,w['rid']))==4000

async def test_stok_dicadangkan_bukan_bisa_dijual_atau_dipindah_lagi(pg,siap):
 from app.services import pk_persediaan
 w=siap
 async with pg() as db:
  source=(await pk_persediaan.baca(db))['giling:'+str(w['proses_id'])]
  assert source.bebas(None)==0
  with pytest.raises(transfer.TransferError):await transfer.create_internal_transfer(db,user=await db.get(User,w['op1']),kode_proses=w['lot'],lokasi_tujuan='ditumpuk',berat=1)
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0

async def test_batal_hanya_perjalanan_tanpa_tiket_dan_tidak_menghapus_persetujuan(pg,siap):
 w=siap;j=await buat(pg,w,'2000')
 async with pg() as db:await s.batalkan(db,pid=j['id'],user=await db.get(User,w['admin']),alasan='Truk batal berangkat')
 async with pg() as db:
  assert await s.sisa(db,await db.get(PermintaanPk,w['rid']))==6000
  assert await transfer.pending_transfer_kg(db,w['proses_id'])==0
 j=await buat(pg,w,'1000');tid=await tiket(pg,j['id'],1000)
 async with pg() as db:
  assert (await s.rincian(db,j['id']))['tiket_id']==tid
  with pytest.raises(s.PengirimanError,match='sudah memiliki tiket'):await s.batalkan(db,pid=j['id'],user=await db.get(User,w['admin']),alasan='Tidak boleh menghapus hubungan timbang')

async def test_tiket_palsu_dan_izin_keputusan_selisih_ditolak(pg,siap):
 w=siap;j=await buat(pg,w,'2000');tid=await tiket(pg,j['id'],1900)
 async with pg() as db:
  with pytest.raises(PermissionError):await s.sinkron(db,pid=j['id'],tid=tid,user=await db.get(User,w['op1']),alasan='Operator tidak menyetujui sendiri')
 async with pg() as db:
  await db.execute(text("UPDATE timbangan_transaksi SET lintasan_transfer=jsonb_set(lintasan_transfer,'{_pengiriman_pk,sidik}','\"palsu\"') WHERE id=:id"),dict(id=tid));await db.commit()
 async with pg() as db:
  with pytest.raises(s.PengirimanError,match='Cuplikan'):await s.sinkron(db,pid=j['id'],tid=tid)
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0

async def test_silo_langsung_dan_tujuan_berbeda_tidak_digabung(pg,siap):
 from app.models import Silo
 w=siap;rid=await lot_lain(pg,w)
 async with pg() as db:await s.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='3000',tujuan='Silo A')])
 async with pg() as db:
  with pytest.raises(s.PengirimanError,match='tujuan yang sama'):await s.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=w['rid'],berat_kg='500'),dict(permintaan_id=rid,berat_kg='500')],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci=uuid.uuid4().hex)
 async with pg() as db:j=await s.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=rid,berat_kg='1000')],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci=uuid.uuid4().hex)
 tid=await tiket(pg,j['id'],999)
 async with pg() as db:assert (await s.sinkron(db,pid=j['id'],tid=tid))['status']=='selesai'
 async with pg() as db:
  t=await db.scalar(select(InternalTransfer));assert t.berat_kg==1000
  silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'));assert silo.status!='kosong'

async def test_kapasitas_silo_menolak_seluruh_perjalanan_lalu_bisa_diulang(pg,siap):
 from app.models import Silo
 from app.penggilingan.gudang2.service import Gudang2Error
 w=siap;rid=await lot_lain(pg,w)
 async with pg() as db:await s.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='3000',tujuan='Silo A')])
 async with pg() as db:
  silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'));silo.kapasitas_ton=Decimal('.5');await db.commit()
  j=await s.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=rid,berat_kg='1000')],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci=uuid.uuid4().hex)
 tid=await tiket(pg,j['id'],1000)
 async with pg() as db:
  with pytest.raises((s.PengirimanError,transfer.TransferError,Gudang2Error)):await s.sinkron(db,pid=j['id'],tid=tid)
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0
  assert (await db.get(PengirimanPk,j['id'])).status=='dalam_perjalanan'
  silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'));silo.kapasitas_ton=2;await db.commit()
 async with pg() as db:assert (await s.sinkron(db,pid=j['id'],tid=tid))['status']=='selesai'
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(InternalTransfer))==1

async def test_tutup_sisa_mempertahankan_persetujuan_dan_hanya_melepas_yang_belum_berangkat(pg,siap):
 w=siap;j=await buat(pg,w,'2000')
 async with pg() as db:
  with pytest.raises(s.PengirimanError,match='belum selesai'):await s.tutup_sisa(db,rid=w['rid'],user=await db.get(User,w['admin']),alasan='Cukup satu perjalanan')
 tid=await tiket(pg,j['id'],2000)
 async with pg() as db:await s.sinkron(db,pid=j['id'],tid=tid)
 async with pg() as db:await s.tutup_sisa(db,rid=w['rid'],user=await db.get(User,w['admin']),alasan='Kebutuhan gudang tujuan sudah terpenuhi')
 async with pg() as db:
  r=await db.get(PermintaanPk,w['rid']);assert r.berat_setuju_kg==6000 and r.berat_final_kg==2000
  assert await transfer.pending_transfer_kg(db,w['proses_id'],bebas=True)==4000
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==2000
