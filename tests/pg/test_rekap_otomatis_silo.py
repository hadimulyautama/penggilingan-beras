from datetime import timedelta
from sqlalchemy import select
import pytest
from app.models import User,Jasa,Pelanggan,PolishingProcess,PolishingSiloUsage,ByproductStock,BrokenKeSilo
from app.database import now_local
from app.services.jasa import rekap_barang_jasa,sisa_jasa
from app.services.stok import stok_produk
from tests.pg.test_barang_keluar import gudang
from tests.pg.test_pengemasan_asal import seed
pytestmark=pytest.mark.asyncio
async def test_stok_tersimpan_dan_broken_di_silo_tidak_hilang_atau_ganda(pg,gudang):
 pid,_=await seed(pg,gudang,True)
 async with pg() as db:
  c=Pelanggan(nama_pelanggan='Uji sisa silo',kledo_contact_id=99301);db.add(c);await db.flush();j=Jasa(kode='JAS-SISA-AUTO',pelanggan_id=c.id,hasil_ditahan='');db.add(j);await db.flush();jid=j.id
  pr=await db.get(PolishingProcess,pid);pr.jasa_id=jid
  usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid));usage.updated_at=now_local()-timedelta(hours=2)
  stock=ByproductStock(jenis_produk='broken',berat_kg=500,source_type='polishing',source_id=pid,jasa_id=jid,waktu=now_local()-timedelta(hours=1),input_by=gudang['op'],tanggal=now_local().date());db.add(stock);await db.flush()
  db.add(BrokenKeSilo(kode_pindah='BKS-UJI-AUTO',byproduct_stock_id=stock.id,silo_id=gudang['silo'],berat_kg=200,jasa_id=jid,waktu=now_local()-timedelta(hours=1),input_by=gudang['op'],tanggal=now_local().date()));await db.commit()
  before=await sisa_jasa(db,jid);d=await rekap_barang_jasa(db,jid);cards=await stok_produk(db,jasa_id=jid)
  assert next(x for x in cards if x.jenis=='broken').sisa_kg==1050
  assert next(x['kg'] for x in d['sisa'] if x['nama']=='Broken')==1050
  assert next(x['kg'] for x in d['sisa'] if x['nama']=='Broken di silo')==200
  assert await sisa_jasa(db,jid)==before
  # Pemakaian berikutnya hanya mengurangi sisa di silo, bukan saldo luar
  # atau seluruh catatan pemindahan historis yang ditambahkan lagi.
  second=PolishingProcess(kode_proses='POL-UJI-ULANG',status='selesai',jasa_id=jid,created_by=gudang['op'],waktu_mulai=now_local()-timedelta(minutes=30),waktu_selesai=now_local());db.add(second);await db.flush()
  db.add(PolishingSiloUsage(polishing_process_id=second.id,silo_id=gudang['silo'],berat_awal_kg=200,berat_masuk_kg=0,berat_akhir_kg=100,berat_terpakai_kg=100));await db.commit()
  d=await rekap_barang_jasa(db,jid)
  assert next(x['kg'] for x in d['sisa'] if x['nama']=='Broken')==1050
  assert next(x['kg'] for x in d['sisa'] if x['nama']=='Broken di silo')==100
