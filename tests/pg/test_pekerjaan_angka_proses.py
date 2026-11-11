"""Jumlah memakai kelompok lama, informasi terlipat tidak hilang."""
from datetime import timedelta
import pytest
from bs4 import BeautifulSoup
from app.services.berjalan import Baris,Berjalan
from app.services.kelompok_kerja import bagi
from app.web.pekerjaan_ringkas import ringkasan_proses
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_riwayat_giling import _klien as klien_g1
from app.database import now_local
from app.models import User

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('states',[['Berjalan'],['Dijeda'],['Pendinginan'],[],['Berjalan','Dijeda','Pendinginan']])
async def test_ringkasan_tanpa_mengubah_partisi_dan_tindakan(pg,monkeypatch,states):
 from app.web import layar_pekerjaan as web
 proses=[Baris(f'P-{i}','data asli','',fase='dryer' if s=='Pendinginan' else 'sosoh',status_proses=s,jeda_sejak=now_local() if s=='Dijeda' else None,nota='Mesin pendukung diperiksa' if s=='Dijeda' else None,aksi='selesai_pendinginan' if s=='Pendinginan' else 'hasil_penyosohan',gudang='g2') for i,s in enumerate(states)]
 info=[Baris('INFO','Menunggu keputusan Admin','',fase='pindah_pk',gudang='g2')]
 action=Baris('WAJIB','Tugas wajib','',aksi='catat_packing',gudang='g2')
 b=Berjalan(berjalan=proses,menunggu=info+[action]);k=bagi(b)
 async def fake(*a):return b,k,''
 monkeypatch.setattr(web,'siapkan_daftar_pekerjaan',fake)
 async with await _klien(pg,role='superadmin') as c:
  r=await c.get('/pekerjaan?tab=berjalan');assert r.status_code==200,r.text[-1000:]
  s=BeautifulSoup(r.text,'html.parser')
  assert s.select_one('.pekerjaan-ringkasan') is None
  assert s.select_one('.pekerjaan-informasi') and not s.select_one('.pekerjaan-informasi').has_attr('open')
  assert 'Menunggu keputusan Admin' in s.get_text()
  assert s.select_one('.pekerjaan-informasi summary').get_text(strip=True)=='Informasi pendukung · 1'
  assert 'Pencarian kartu' in s.select_one('#pk-panduan').get_text()
  assert s.select_one('nav[aria-label="Tab pekerjaan"] a[href*="tab=tindakan"] .pil__jml').text.strip()=='1'
  assert s.select_one('nav[aria-label="Tab pekerjaan"] a[href*="tab=berjalan"] .pil__jml').text.strip()==str(len(states))
  if 'Dijeda' in states:assert 'Jeda sejak' in r.text and 'Mesin pendukung diperiksa' in r.text
  if not states:assert 'Informasi pendukung tetap tersedia' in r.text
  # Pencarian kini di server agar menjangkau kartu pada halaman lain.
  form=s.select_one('form[role="search"]')
  assert form and form.get('method')=='get' and form.get('action')=='/pekerjaan'
  assert form.select_one('input[name="cari"]') and form.select_one('button[type="submit"]')
  assert form.select_one('input[name="tab"]').get('value')=='berjalan'
  assert (await c.get('/pekerjaan?tab=tindakan')).status_code==200
 assert k.tindakan==[action] and k.informasi==info and k.berjalan==proses

async def test_proses_banyak_deduplikasi_dan_cakupan_filter(pg,monkeypatch):
 from app.web.layar_pekerjaan import daftar_tab_pekerjaan
 xs=[Baris(f'LOT-{i}','asal bahan','',fase='dryer',status_proses='Berjalan',gudang='g1',kepemilikan='jasa') for i in range(200)]
 duplicate=Baris('LOT-0','bahan kedua','',fase='dryer',status_proses='Berjalan',gudang='g1',kepemilikan='jasa')
 b=Berjalan(berjalan=xs+[duplicate],menunggu=[Baris('Selesai','Stok masih ada','',gudang='g1',kepemilikan='jasa')]);k=bagi(b)
 assert ringkasan_proses(k.berjalan)['jumlah']==200
 assert daftar_tab_pekerjaan(k,'jasa','g1','pengeringan')[-1]==200
 assert daftar_tab_pekerjaan(k,'pabrik','g1','pengeringan')[-1]==0
 assert daftar_tab_pekerjaan(k,'jasa','g2','pengeringan')[-1]==0

async def test_status_dari_kejadian_jeda_pendinginan_dan_selesai_asli(pg,pengeringan):
 from app.penggilingan.gudang1.services import jeda,drying
 from app.services import berjalan
 from app.services.kelompok_kerja import bagi
 async with pg() as db:
  u=await db.get(User,pengeringan['user']);kode=pengeringan['kode']
  before=bagi(await berjalan.untuk(db,u));assert ringkasan_proses(before.berjalan)['status']==[('Berjalan',1)]
  await jeda.hentikan(db,user=u,jenis='pengeringan',kode=kode,sebab='Listrik padam')
  b=bagi(await berjalan.untuk(db,u));row=next(x for x in b.berjalan if x.kode==kode)
  assert row.status_proses=='Dijeda' and row.jeda_sejak is not None and 'Listrik padam' in row.nota
  assert ringkasan_proses(b.berjalan)['status']==[('Dijeda',1)]
  await drying.finish_drying(db,user=u,kode_lot=kode,kadar_air_akhir=13)
  b=bagi(await berjalan.untuk(db,u));assert ringkasan_proses(b.berjalan)['status']==[('Pendinginan',1)]
  await drying.finish_cooling(db,user=u,kode_lot=kode)
  b=bagi(await berjalan.untuk(db,u));assert ringkasan_proses(b.berjalan)['jumlah']==0
