"""Pengambilan tetap terikat pelanggan, pesanan asal, dan stok titipan."""
from sqlalchemy import select,func
import pytest
from tests.pg.test_pk_g2_keluar import pabrik,_masuk_tumpukan
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
from app.models import OutgoingRecord,OutgoingItem,User,Jasa
from app.penggilingan.gudang2.service import hitung_stok_tumpukan
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('barang',[None,[]])
async def test_barang_kosong_diberi_pesan_bukan_500(pg,pabrik,barang):
 async with await _klien(pg,pabrik['user'],'uji_ambil_kosong') as c:
  r=await c.post('/api/actions/ambil-jasa',json={'pelanggan':str(pabrik['pelanggan_a']),'barang':barang},headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==400,r.text
  assert 'barang' in r.text.lower()

@pytest.mark.parametrize('kasus',['pelanggan-lain','tanpa-pesanan'])
async def test_request_tidak_mengambil_barang_diluar_pelanggan_terpilih(pg,pabrik,pemasok,kasus):
 jid=pabrik['jasa_a'] if kasus=='pelanggan-lain' else None
 await _masuk_tumpukan(pg,pabrik['user'],'PKB-PAGAR-AMBIL',2000,jid,pemasok.id if jid is None else None)
 async with await _klien(pg,pabrik['user'],'uji_ambil_pagar') as c:
  selected=pabrik['pelanggan_b'] if kasus=='pelanggan-lain' else pabrik['pelanggan_a']
  pick=f'g2:tumpukan@{jid}' if jid is not None else 'g2:tumpukan'
  r=await c.post('/api/actions/ambil-jasa',json={'pelanggan':str(selected),'barang':[{'pilih':pick,'jumlah':1000}]},headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==400,r.text
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0
  assert await db.scalar(select(func.count()).select_from(OutgoingItem))==0
  assert await hitung_stok_tumpukan(db,jasa_id=jid)==2000

async def test_beberapa_pesanan_pelanggan_sama_tetap_bisa_diperintahkan(pg,pabrik):
 async with pg() as db:
  j=Jasa(kode='JAS-AMBIL-TAMBAH',pelanggan_id=pabrik['pelanggan_a'],status='berjalan');db.add(j);await db.commit();jid=j.id
 for i,j in enumerate([pabrik['jasa_a'],jid]):await _masuk_tumpukan(pg,pabrik['user'],f'PKB-AMBIL-PERINTAH-{i}',2000,j)
 async with await _klien(pg,pabrik['user'],'uji_ambil_sah') as c:
  r=await c.post('/api/actions/ambil-jasa',json={'pelanggan':str(pabrik['pelanggan_a']),'barang':[{'pilih':f'g2:tumpukan@{j}','jumlah':1000} for j in [pabrik['jasa_a'],jid]]},headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200,r.text
 async with pg() as db:
  rec=await db.scalar(select(OutgoingRecord));assert rec.pelanggan_id==pabrik['pelanggan_a']
  items=(await db.scalars(select(OutgoingItem))).all()
  assert {i.jasa_id for i in items}=={pabrik['jasa_a'],jid}
  assert all(float(i.berat_kg)==0 for i in items)
  assert await hitung_stok_tumpukan(db,jasa_id=pabrik['jasa_a'])==2000
  assert await hitung_stok_tumpukan(db,jasa_id=jid)==2000

@pytest.mark.parametrize('peran,gudang,lihat',[
 ('operator','g1',None),('operator','g2',None),
 ('superadmin',None,'operator:g1'),('superadmin',None,'operator:g2')])
async def test_hak_akses_efektif_tetap_berlaku(pg,pabrik,peran,gudang,lihat):
 async with pg() as db:
  user=await db.get(User,pabrik['user']);user.role=peran
  if gudang:user.default_warehouse_id=pabrik[gudang]
  await db.commit()
 async with await _klien(pg,pabrik['user'],'uji_ambil_akses',mode=peran) as c:
  if lihat:
   assert (await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)})).status_code==303
  r=await c.post('/api/actions/ambil-jasa',json={'pelanggan':str(pabrik['pelanggan_a']),'barang':[]},headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==403,r.text
  assert (await c.get('/api/actions/pelanggan-ada-barang-jasa')).status_code==403

async def test_pemanggil_layanan_tidak_mengabaikan_pelanggan_yang_disebut(pg,pabrik):
 from app.services import barang_keluar as bk
 await _masuk_tumpukan(pg,pabrik['user'],'PKB-AMBIL-LAYANAN',2000,pabrik['jasa_a'])
 async with pg() as db:
  with pytest.raises(bk.BarangKeluarError,match='pelanggan yang dipilih'):
   await bk.buat_perintah(db,user=await db.get(User,pabrik['user']),pelanggan_id=pabrik['pelanggan_b'],jasa_id=pabrik['jasa_a'],baris=[bk.BarisPerintah(tipe='pk_g2',berat_kg=1000)])
  await db.rollback()
  assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0

async def test_dua_pesanan_curah_saldo_reservasi_dan_gagal_tanpa_parsial(pg,pabrik):
 from app.services import barang_keluar as bk
 async with pg() as db:
  j=Jasa(kode='JAS-UJI-LINTAS-CURAH',pelanggan_id=pabrik['pelanggan_a'],status='berjalan')
  db.add(j);await db.commit();kedua=j.id
 ids=[pabrik['jasa_a'],kedua]
 for i,jid in enumerate(ids):await _masuk_tumpukan(pg,pabrik['user'],f'PKB-LINTAS-CURAH-{i}',2000,jid)
 async with await _klien(pg,pabrik['user'],'uji-lintas-curah') as c:
  body={'pelanggan':str(pabrik['pelanggan_a']),'barang':[{'pilih':f'g2:tumpukan@{ids[0]}','jumlah':1000},{'pilih':f'g2:tumpukan@{ids[1]}','jumlah':2500}]}
  r=await c.post('/api/actions/ambil-jasa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==400,r.text
  async with pg() as db:
   assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0
   for jid in ids:assert await hitung_stok_tumpukan(db,jasa_id=jid)==2000
  body['barang'][1]['jumlah']=1000
  assert (await c.post('/api/actions/ambil-jasa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})).status_code==200
 async with pg() as db:
  rec=await db.scalar(select(OutgoingRecord));items=(await db.scalars(select(OutgoingItem))).all()
  mapping={x.jasa_id:x.id for x in items};uid=pabrik['user']
  for jid,jumlah in [(ids[0],400),(ids[1],600),(ids[0],350),(ids[0],350)]:
   await bk.catat_muatan(db,user=await db.get(User,uid),item_id=mapping[jid],rec_id=rec.id,berat_kg=jumlah)
  assert await hitung_stok_tumpukan(db,jasa_id=ids[0])==1650
  assert await hitung_stok_tumpukan(db,jasa_id=ids[1])==1400
  for jid in ids:
   available,_=await bk.tersedia(db,bk.BarisPerintah(tipe='pk_g2',jasa_id=jid))
   assert available==1000
