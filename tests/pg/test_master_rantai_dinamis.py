"""Audit independen: spek baru harus lolos seluruh jalur, bukan hanya daftar master."""
import pytest
from app.database import now_local
from sqlalchemy import select
from app.models import User,PolishingProcess,PolishingOutputLog,FinishedGoodsStock
from app.services import spesifikasi_beras as master,jenis_hasil_samping as hs,stok
from app.penggilingan.gudang2 import polishing as p,service as g2
from app.penggilingan.inventory import finished_goods as fg
from tests.pg.test_masukkan_beras_silo import sosoh
from tests.pg.test_barang_keluar import _klien

async def siapkan(pg,s):
 async with pg() as db:
  u=await db.get(User,s['user']);grade=await master.simpan(db,user=u,nama='Ramos audit',broken='5',sosoh='110');proc=await db.get(PolishingProcess,s['proc_id']);proc.status='proses';proc.waktu_selesai=None
  db.add(PolishingOutputLog(polishing_process_id=proc.id,jenis=grade.kode,berat_kg=600,waktu_update=now_local(),input_by=u.id));await db.commit()
  return grade.kode

async def test_spek_baru_bisa_diselesaikan_dengan_riwayat_lama(pg,sosoh):
 kode=await siapkan(pg,sosoh)
 async with pg() as db:
  r=await p.akhiri_penyosohan(db,user=await db.get(User,sosoh['user']),kode=sosoh['kode_pol'])
  assert r.selesai and r.beras_total==8600
  assert (await stok.output_sosoh(db,sosoh['proc_id']))[kode]==600

@pytest.mark.fondasi_multi
async def test_spek_baru_packing_silo_tidak_menggandakan_stok(pg,sosoh):
 kode=await siapkan(pg,sosoh)
 async with pg() as db:
  u=await db.get(User,sosoh['user'])
  await fg.catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='beras_putih',grade=kode,material_kode='biasa',ukuran=25,jumlah_karung=4)
  row=await db.scalar(select(FinishedGoodsStock));sku=row.product_sku_id
  await g2.masukkan_beras_ke_silo(db,user=u,jenis=kode,nama_silo='C',berat_kg=100,sumber_stok='sku:'+str(sku))
  card=next(k for k in await stok.stok_produk(db) if k.jenis==kode)
  assert card.sisa_kg==500 and await g2.hitung_stok_silo(db,sosoh['silo_beras'])==100

async def test_samping_baru_bisa_masuk_silo_untuk_dicampur(pg,sosoh):
 async with pg() as db:
  u=await db.get(User,sosoh['user']);kode=await hs.simpan(db,user=u,aksi='tambah',nama='Menir audit',bentuk='karung',kg_karung='30')
  db.add(PolishingOutputLog(polishing_process_id=sosoh['proc_id'],jenis=kode,berat_kg=95,waktu_update=now_local(),input_by=u.id));await db.commit()
  r=await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=kode,jasa_id=None,nama_silo='C',berat_kg=60)
  assert r['moved_kg']==60

async def test_data_lama_dipertahankan_saat_ganti_nama_dan_acuan(pg,sosoh):
 async with pg() as db:
  u=await db.get(User,sosoh['user']);before=await stok.output_sosoh(db,sosoh['proc_id'])
  row=next(x for x in await master.rincian(db) if x['kode']=='medium')
  await master.simpan(db,user=u,id_=row['id'],versi=row['versi'],nama='Medium audit baru',broken='9',sosoh='105',aksi='ubah');await db.commit()
  assert await stok.output_sosoh(db,sosoh['proc_id'])==before
  assert next(k for k in await stok.stok_produk(db) if k.jenis=='medium').sisa_kg==8000

async def test_nonaktif_tidak_menghalangi_packing_stok_lama(pg,sosoh):
 async with pg() as db:
  u=await db.get(User,sosoh['user']);r=next(x for x in await master.rincian(db) if x['kode']=='medium')
  await master.simpan(db,user=u,id_=r['id'],versi=r['versi'],aksi='nonaktifkan');await db.commit()
  await fg.catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=4)
  assert next(k for k in await stok.stok_produk(db) if k.jenis=='medium').sisa_kg==8000

async def test_http_spek_baru_muncul_di_packing_dan_detail(pg,sosoh):
 kode=await siapkan(pg,sosoh)
 async with await _klien(pg,sosoh['user'],'master-rantai',mode='admin') as c:
  options=(await c.get('/api/actions/beras-belum-dikemas')).json()
  assert any(x['value']==sosoh['kode_pol']+'|'+kode for x in options)
  kemasan=await c.get('/api/actions/kemasan-untuk',params={'induk':sosoh['kode_pol']+'|'+kode});assert kemasan.status_code==200 and kemasan.json()
  detail=await c.get('/stok-produk/detail',params={'jenis':kode});assert detail.status_code==200 and 'Ramos audit' in detail.text

@pytest.mark.parametrize('jasa',[False,True])
@pytest.mark.fondasi_multi
async def test_campur_pk_beras_spek_baru_dan_samping_lama_sampai_selesai(pg,sosoh,jasa):
 from app.models import PkPurchaseBatch,PkGudang2Intake,Silo,Pelanggan,Jasa,Supplier
 async with pg() as db:
  u=await db.get(User,sosoh['user']);owner=None
  if jasa:
   pel=Pelanggan(nama_pelanggan='Pemilik campuran audit');db.add(pel);await db.flush();order=Jasa(kode='JAS-AUDIT-CAMPUR',pelanggan_id=pel.id);db.add(order);await db.flush();owner=order.id
  proc=await db.get(PolishingProcess,sosoh['proc_id']);proc.jasa_id=owner
  grade=await master.simpan(db,user=u,nama='Hasil campuran audit',broken='5',sosoh='100')
  for jenis,kg in [(grade.kode,600),('menir',100),('reject',100),('broken',100)]:db.add(PolishingOutputLog(polishing_process_id=proc.id,jenis=jenis,berat_kg=kg,waktu_update=now_local(),input_by=u.id))
  wid=(await db.get(Silo,sosoh['silo_beras'])).warehouse_id
  supplier=Supplier(nama_supplier='Pemasok audit PK');db.add(supplier);await db.flush()
  batch=PkPurchaseBatch(supplier_id=supplier.id if owner is None else None,kode_batch='PKB-CAMPUR-AUDIT',berat_total_kg=1000,tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=u.id,status_batch='diterima',sumber_berat='manual',jasa_id=owner);db.add(batch);await db.flush()
  db.add(PkGudang2Intake(sumber_tipe='beli_luar',pk_purchase_batch_id=batch.id,tujuan='silo',silo_id=sosoh['silo_beras'],berat_kg=1000,bobot_final=True,tanggal_masuk=now_local().date(),waktu_masuk=now_local(),input_by=u.id,jasa_id=owner));await db.commit()
  await g2.masukkan_beras_ke_silo(db,user=u,jenis=grade.kode,nama_silo='C',berat_kg=100,jasa_id=owner,sumber_stok='curah')
  for jenis,kg in [('menir',50),('reject',25)]:await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=jenis,jasa_id=owner,nama_silo='C',berat_kg=kg)
  await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=u,jasa_id=owner,nama_silo='C',berat_kg=75)
  assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==1250
  baru=await p.mulai_penyosohan(db,user=u,nama_silos=['C'])
  assert baru.berat_awal_total==1250 and baru.proc.jasa_id==owner
  await p.catat_output(db,user=u,kode=baru.proc.kode_proses,jenis=grade.kode,berat_kumulatif=1000)
  await p.selesai_penyosohan(db,user=u,kode=baru.proc.kode_proses,nama_silo='C',sisa_kg=100)
  result=await p.akhiri_penyosohan(db,user=u,kode=baru.proc.kode_proses)
  assert result.selesai and result.pk_terpakai_total==1150 and result.beras_total==1000
  assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==100
  cards={k.jenis:k for k in await stok.stok_produk(db,jasa_id=owner)}
  assert cards[grade.kode].sisa_kg==1500
  assert cards['menir'].sisa_kg==50 and cards['reject'].sisa_kg==75 and cards['broken'].sisa_kg==25
