"""Pencarian sebelum pagination pada PostgreSQL uji, bukan transaksi produksi."""
from datetime import datetime,date,timezone
from decimal import Decimal
from urllib.parse import urlsplit,parse_qs
import pytest
from sqlalchemy import select,text,event
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien,_tiket
from tests.pg.formulir import cap_formulir
from app.models import PurchaseBatch,User
from app.services import barang_masuk_daftar as service

pytestmark=pytest.mark.asyncio

async def seed(pg,n=80):
 async with pg() as db:
  from app.models import Supplier
  supplier=await db.scalar(select(Supplier.id).order_by(Supplier.id));user=await db.scalar(select(User.id).order_by(User.id))
  if supplier is None:
   sup=Supplier(nama_supplier='Supplier Sumber Uji');db.add(sup);await db.flush();supplier=sup.id
  ids=[]
  for i in range(n):
   tid=await _tiket(db,f'TB-CARI-{i:04}', 'GABAH_KERING',pihak='Nama 100%_Uji' if i==0 else 'Tani Serupa' if i%2 else 'Tani Sejahtera')
   await db.execute(text("UPDATE timbangan_transaksi SET tanggal=:d,nomor_polisi=:p WHERE id=:id"),dict(d=date(2020+i%6,1,1),p=f'AD {i:04} ZZ',id=tid))
   db.add(PurchaseBatch(kode_batch=f'GB-CARI-{i:04}',supplier_id=supplier,berat_total_kg=1000+i,kondisi_gabah='kering',tanggal_pembelian=date(2020+i%6,1,1),waktu_pembelian=datetime(2020+i%6,1,1,tzinfo=timezone.utc),input_by=user,status_batch='selesai',timbangan_transaksi_id=tid,sumber_berat='timbangan'))
   ids.append(tid)
  await db.commit();return ids

def soup(r):assert r.status_code==200,r.text[-1800:];return BeautifulSoup(r.text,'html.parser')
def rows(s):return s.select('.masuk-baris')

async def test_lintas_tahun_halaman_bobot_tersimpan_dan_literal(pg,lengkap):
 ids=await seed(pg)
 async with pg() as db:
  d=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima')
  assert d['jumlah']>=80 and len(d['riwayat'])==25 and d['halaman_akhir']>=4
  for q,expected in [('  tb-cari-0000  ',1),('ad 0001 zz',1),('100%_Uji',1),('tidak cocok',0)]:
   r=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari=q)
   assert r['jumlah']==expected,(q,r['jumlah'])
  r=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='TB-CARI-0000')
  assert r['riwayat'][0]['berat_diterima']==1000 and r['riwayat'][0]['catatan'][0]['status']=='selesai'
  r=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='Tani',halaman=2)
  assert len(r['riwayat'])==25 and r['jumlah']==79
  assert 'Nama 100%_Uji' in r['nama_saring']
 async with await _klien(pg,role='superadmin') as c:
  s=soup(await c.get('/barang-masuk?status=diterima&cari=TB-CARI&gudang=g1&jenis=gabah_kering&halaman=2'))
  tabs=s.select('nav[aria-label="Bagian Barang Masuk"] a')
  assert len(tabs)==3 and tabs[1].get('aria-current')=='page'
  assert not any(a.select('.pil__jml') for a in tabs)
  assert tabs[2]['href']=='/riwayat-retur-supplier'
  assert len(rows(s))==25 and '80 hasil' in s.get_text() and 'Halaman 2 dari 4' in s.get_text()
  assert not s.select('[data-saring-kerja]') and not s.select('script[src*="saring-kerja"]')
  href=s.select_one('.bm-halaman a')['href'];q=parse_qs(urlsplit(href).query)
  assert q['cari']==['TB-CARI'] and q['gudang']==['g1'] and q['jenis']==['gabah_kering']
  detail=rows(s)[0]['href'];q=parse_qs(urlsplit(detail).query)
  assert 'halaman=2' in q['kembali_kerja'][0]
  clear=s.select_one('.bm-jumlah a')['href'];q=parse_qs(urlsplit(clear).query)
  assert 'cari' not in q and 'halaman' not in q and q['gudang']==['g1']
  assert all('halaman=' not in a['href'] for a in s.select('.saring-kepemilikan a'))

@pytest.mark.parametrize('role,wh,view,g1,g2',[('superadmin',None,None,True,True),('admin',None,None,True,True),('operator','g1',None,True,False),('operator','g2',None,False,True),('superadmin',None,'operator:g1',True,False),('superadmin',None,'operator:g2',False,True)])
async def test_belum_diterima_scope_hitung_nama_detail(pg,lengkap,role,wh,view,g1,g2):
 async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(wh)) as c:
  if view:assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})).status_code==303
  r=await c.get('/barang-masuk?cari=TRX-391');s=soup(r)
  expected=5 if role in ['superadmin','admin'] and not view else 2 if g1 else 1
  assert f'{expected} hasil' in s.get_text()
  for kind,allow in [('GABAH_KERING',g1),('BERAS_PK',g2)]:
   r=await c.get('/barang-masuk',params=dict(cari='TRX-391-'+kind));assert ('1 hasil' if allow else '0 hasil') in r.text
   assert (await c.get('/barang-masuk/'+str(lengkap['tiket'][kind]))).status_code==(200 if allow else 403)
  # Unavailable warehouse is a restrictive filter, never authorization.
  s=soup(await c.get('/barang-masuk',params=dict(cari='TRX-391',gudang='g2' if not g2 else 'g1')))
  assert ('0 hasil' in s.get_text()) if not(g1 and g2) else True

async def test_pelanggan_filter_nama_dan_kombinasi_tidak_dilonggarkan(pg,lengkap):
 async with pg() as db:
  tid=lengkap['tiket']['GABAH_KERING']
  await db.execute(text('UPDATE timbangan_transaksi SET jasa=true,pelanggan_id=:p,jasa_id=:j WHERE id=:i'),dict(p=lengkap['pelanggan_id'],j=lengkap['jasa_id'],i=tid));await db.commit()
  base=dict(g1=True,g2=True,admin=True,status='belum',pid=lengkap['pelanggan_id'])
  a=await service.daftar(db,**base);assert a['jumlah']==1 and a['menunggu'][0].kode=='TRX-391-GABAH_KERING'
  name=a['nama_saring'][0]
  assert (await service.daftar(db,**base,pemasok=name,cari='391',jenis='gabah_kering',pemilik='jasa',gudang='g1'))['jumlah']==1
  assert (await service.daftar(db,**base,cari='391',pemilik='pabrik'))['jumlah']==0
  assert (await service.daftar(db,**base,pemasok='nama berbeda'))['jumlah']==0

async def test_hidrasi_terbatas_stabil_dan_tab_tidak_berubah(pg,lengkap,monkeypatch):
 await seed(pg,60)
 from app.services import barang_masuk
 old=barang_masuk.riwayat;seen=[]
 async def bounded(db,**kw):
  assert kw['ids_tiket'] is not None and len(kw['ids_tiket'])<=25
  seen.append(kw['ids_tiket']);return await old(db,**kw)
 monkeypatch.setattr(barang_masuk,'riwayat',bounded)
 async with pg() as db:
  a=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='CARI',halaman=1)
  b=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='CARI',halaman=2)
  assert not(set(seen[0])&set(seen[1])) and seen[0]==sorted(seen[0],reverse=True)
  assert a['jumlah']==b['jumlah']==60
  z=await service.daftar(db,g1=True,g2=True,admin=True,status='belum',cari='TB-CARI-0000')
  assert z['jumlah']==0 # Old received cannot be offered again for receipt.

async def test_kegagalan_bukan_nol_dan_filter_tetap_ada(pg,lengkap,monkeypatch):
 from sqlalchemy.exc import OperationalError
 async def fail(*a,**kw):raise OperationalError('uji',{},RuntimeError('gagal baca'))
 monkeypatch.setattr(service,'daftar',fail)
 async with await _klien(pg,role='superadmin') as c:
  r=await c.get('/barang-masuk?status=diterima&cari=Nama+lama&jenis=pk&gudang=g2&pemasok=Pihak+lama')
  assert r.status_code==503
  s=BeautifulSoup(r.text,'html.parser')
  assert s.select_one('[name=cari][type=search]')['value']=='Nama lama'
  assert 'Jumlah hasil belum tersedia' in r.text and 'Tidak ada penerimaan yang cocok' not in r.text
  assert s.select_one('[data-bm-retry]') and s.select_one('[name=jenis] option[selected]')['value']=='pk'

async def test_produk_habis_dan_sumber_dihapus_tetap_arsip_bukan_stok_nol(pg,lengkap):
 from app.models import FinishedGoodsStock,ActivityLog
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);tid=lengkap['tiket']['BERAS_MASUK']
  assert (await c.post('/api/actions/catat-produk-timbang-masuk',json=dict(timbangan_transaksi_id=tid))).status_code==200
  async with pg() as db:
   row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==tid));await db.delete(row);await db.commit()
  r=await c.get('/barang-masuk?status=diterima&cari=TRX-391-BERAS_MASUK');s=soup(r)
  assert len(rows(s))==1 and 'Arsip penerimaan' in r.text and '9.800' in r.text
  r=await c.get(rows(s)[0]['href']);assert r.status_code==200 and 'Arsip penerimaan' in r.text and 'Sumber stok penerimaan ini tidak lagi tersedia' in r.text
  assert not BeautifulSoup(r.text,'html.parser').select('form[action^="/api/"]')
  r=await c.get('/barang-masuk?status=belum&cari=TRX-391-BERAS_MASUK');assert '0 hasil' in r.text
  async with pg() as db:assert not await db.scalar(select(FinishedGoodsStock.id).where(FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==tid))
 async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g1']) as c:
  assert '0 hasil' in (await c.get('/barang-masuk?status=diterima&cari=TRX-391-BERAS_MASUK')).text
  assert (await c.get('/barang-masuk/'+str(tid))).status_code==403

async def test_banyak_catatan_satu_tiket_tidak_berlipat_dan_data_tetap(pg,lengkap):
 from app.models import ByproductStock,FinishedGoodsStock
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);tid=lengkap['tiket']['BERAS_MASUK']
  assert (await c.post('/api/actions/catat-produk-timbang-masuk',json=dict(timbangan_transaksi_id=tid))).status_code==200
 async with pg() as db:
  f=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==tid))
  # Beberapa sumber pada satu tiket yang sudah ada tetap satu baris daftar.
  db.add(ByproductStock(source_type='timbangan',source_id=tid,jenis_produk='broken',berat_kg=200,tanggal=date.today(),waktu=datetime.now(timezone.utc),input_by=f.input_by,jasa_id=f.jasa_id))
  await db.commit()
  a=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='TRX-391-BERAS_MASUK')
  assert a['jumlah']==1 and len(a['riwayat'])==1 and len(a['riwayat'][0]['catatan'])==2
  assert a['riwayat'][0]['berat_diterima']==10000
  before=[tuple(r) for r in (await db.execute(text('SELECT id,berat_total_kg FROM finished_goods_stock ORDER BY id'))).all()]
  await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='TRX-391-BERAS_MASUK')
  assert before==[tuple(r) for r in (await db.execute(text('SELECT id,berat_total_kg FROM finished_goods_stock ORDER BY id'))).all()]

async def test_5000_tiket_hanya_satu_halaman_dan_rencana_query(pg,lengkap):
 import time,json
 from pathlib import Path
 from app.models import Supplier
 async with pg() as db:
  u=await db.scalar(select(User.id).order_by(User.id));sp=Supplier(nama_supplier='Supplier Beban Uji');db.add(sp);await db.flush()
  await db.execute(text('''INSERT INTO timbangan_transaksi(kode,tanggal,arah,jenis_kode,cara_timbang,pihak_nama,nomor_polisi,timbang1_kg,timbang1_waktu,netto_timbangan_kg,berat_acuan_kg,status_tiket,status_transaksi)
   SELECT 'TB-BESAR-'||n,'2020-01-01'::date+(n%2000),'MASUK','GABAH_KERING','DUA_KALI',CASE WHEN n=1 THEN 'Pihak Lama Dicari' ELSE 'Nama Mirip '||(n%7) END,'AD '||n||' UJI',12000,now(),1000,0,'SELESAI','AKTIF' FROM generate_series(1,5000) n'''))
  await db.execute(text('''INSERT INTO purchase_batches(kode_batch,supplier_id,berat_total_kg,kondisi_gabah,tanggal_pembelian,waktu_pembelian,input_by,status_batch,timbangan_transaksi_id,sumber_berat,flag_unverified)
   SELECT 'GB-BESAR-'||id,:s,1000,'kering',tanggal,timbang1_waktu,:u,'selesai',id,'timbangan',false FROM timbangan_transaksi WHERE kode LIKE 'TB-BESAR-%' '''),dict(s=sp.id,u=u));await db.commit()
  queries=[]
  engine=db.bind.sync_engine
  def capture(conn,cursor,statement,parameters,context,many):queries.append(statement)
  event.listen(engine,'before_cursor_execute',capture)
  try:
   started=time.perf_counter();a=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari='Nama Mirip',halaman=2);elapsed=time.perf_counter()-started
  finally:event.remove(engine,'before_cursor_execute',capture)
  assert a['jumlah']==4999 and len(a['riwayat'])==25 and a['halaman_akhir']==200
  b=await service.daftar(db,g1=True,g2=True,admin=True,status='diterima',cari=' pihak lama dicari ')
  assert b['jumlah']==1 and b['riwayat'][0]['kode']=='TB-BESAR-1'
  assert sum('LIMIT' in q.upper() for q in queries)>=1 and len(queries)<20
  params=dict(jenis='',pemilik='',gudang='',pid=None,cari='%Nama Mirip%',pemasok='',limit=25,offset=25)
  plan=(await db.execute(text('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+service.dasar_diterima(True,True)+' SELECT id FROM dasar WHERE '+service._filter()+" AND cari ILIKE :cari ORDER BY id DESC LIMIT :limit OFFSET :offset"),params)).scalar_one()
  out=Path('output/barang-masuk-pencarian-a-20261101');out.mkdir(parents=True,exist_ok=True)
  (out/'beban-5000.json').write_text(json.dumps(dict(tiket_uji=5000,cocok=a['jumlah'],halaman_dimuat=len(a['riwayat']),query=len(queries),detik=elapsed,plan=plan),indent=2))

async def test_arsip_tak_lengkap_netral_tanpa_membocorkan_teks_audit(pg,lengkap):
 from app.models import ActivityLog
 tid=lengkap['tiket']['BERAS_MASUK']
 async with pg() as db:
  db.add(ActivityLog(table_name='finished_goods_stock',record_id=987654,action='INSERT',
   aksi='produk_timbang_masuk',field_name='timbangan_transaksi_id',old_value=str(tid),new_value='TRX-391-BERAS_MASUK · harga_terlarang_untuk_operator'))
  await db.commit()
 async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
  r=await c.get('/barang-masuk?status=diterima&cari=TRX-391-BERAS_MASUK');assert r.status_code==200 and 'Arsip penerimaan' in r.text
  r=await c.get('/barang-masuk/'+str(tid));assert r.status_code==200
  assert 'Tidak tersedia pada arsip' in r.text and 'harga_terlarang_untuk_operator' not in r.text
  assert not BeautifulSoup(r.text,'html.parser').select('a[href^="/audit"]')
