"""PDF memakai histori FIFO sekali, angka utuh, serta seluruh audit jeda."""
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import pytest
from pypdf import PdfReader
from sqlalchemy import select
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import pabrik, _giling_selesai, _klien
from tests.pg.test_riwayat_pengeringan import pabrik as pabrik_dryer, _lot_selesai
from tests.pg.test_riwayat_sosoh import _sosoh_selesai
pytestmark=pytest.mark.asyncio
OUT=Path('output/audit-pdf-20261019/perbaikan354')
OUT.mkdir(parents=True,exist_ok=True)

def baca(response,nama):
 assert response.status_code==200,response.text[:100] if response.status_code!=200 else ''
 (OUT/(nama+'.pdf')).write_bytes(response.content)
 return '\n'.join(p.extract_text() for p in PdfReader(BytesIO(response.content)).pages)

async def test_sosoh_asal_ulang_tidak_mengambil_lagi_sumber_lama(pg,gudang2):
 from app.penggilingan.gudang2.polishing import mulai_penyosohan,selesai_penyosohan,tambah_silo_penyosohan,catat_output,akhiri_penyosohan
 from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
 from app.web.laporan_sosoh import ambil_data
 u=gudang2['user']
 async with pg() as db:
  pr=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
  await selesai_penyosohan(db,user=u,kode=pr.kode_proses,nama_silo='B',sisa_kg=0)
 async with pg() as db:
  await pindah_tumpukan_ke_silo(db,user=u,intake_id=gudang2['intake_tumpukan'],nama_silo='B',berat=500)
  await tambah_silo_penyosohan(db,user=u,kode=pr.kode_proses,nama_silos=['B'])
  await catat_output(db,user=u,kode=pr.kode_proses,jenis='medium',berat_kumulatif=1000)
  await selesai_penyosohan(db,user=u,kode=pr.kode_proses,nama_silo='B',sisa_kg=100)
  await akhiri_penyosohan(db,user=u,kode=pr.kode_proses)
 d=await ambil_data(pr.id)
 rows=d['source_rows']
 assert sum(x['weight'] for x in rows if x['code']=='PKB-20260912-02')==9800
 assert sum(x['weight'] for x in rows if x['code']=='PKB-20260912-01')==400
 assert sum(x['used'] for x in d['silos'])==10200
 assert [x['remaining'] for x in d['silos']]==[0,100]
 async with await _klien(pg,peran='admin') as c:
  pdf=await c.get(f'/riwayat-sosoh/{pr.id}/laporan.pdf')
  detail=await c.get(f'/riwayat-sosoh/{pr.id}')
 text=baca(pdf,'sosoh-ulang')
 (OUT/'sosoh-ulang-detail.html').write_text(detail.text)
 for value in ['Tanpa tambahan','Kosong','100 kg','Dilepaskan','10.200 kg','1.000 kg']:
  assert value in text,value
 assert 'Total bahan baku' in detail.text
 assert 'Bahan PK' not in detail.text

@pytest.mark.parametrize('jenis',['giling','pengeringan','penyosohan'])
async def test_pdf_seluruh_jeda_identitas_terlambat_dan_batal(pg,pabrik,pabrik_dryer,jenis):
 from app.models import MillingProcess,DryingLot,PolishingProcess,JedaProses,JedaCatatan,User,DryingMoistureLog
 from app.database import now_local
 if jenis=='giling':
  kode=await _giling_selesai(pg,pabrik,masuk_kg=10883.75)
  model=MillingProcess;field='milling_process_id';path='riwayat-giling';uid=pabrik['user']
 elif jenis=='pengeringan':
  kode=await _lot_selesai(pg,pabrik_dryer)
  model=DryingLot;field='drying_lot_id';path='riwayat-pengeringan';uid=pabrik_dryer['user']
 else:
  kode=await _sosoh_selesai(pg,pabrik['user'])
  model=PolishingProcess;field='polishing_process_id';path='riwayat-sosoh';uid=pabrik['user']
 async with pg() as db:
  pr=await db.scalar(select(model).where((model.kode_lot if jenis=='pengeringan' else model.kode_proses)==kode))
  t=now_local()-timedelta(days=2)
  if jenis=='pengeringan':
   pr.waktu_mulai_pengeringan=t;pr.waktu_selesai_pengeringan=t+timedelta(hours=2)
   pr.waktu_mulai_pendinginan=t+timedelta(hours=2);pr.waktu_selesai_pendinginan=t+timedelta(hours=3)
   db.add_all([DryingMoistureLog(drying_lot_id=pr.id,waktu_update=t+timedelta(minutes=5),kadar_air_tes_manual=26,input_by=uid),
               DryingMoistureLog(drying_lot_id=pr.id,waktu_update=t+timedelta(minutes=65),kadar_air_tes_manual=25,input_by=uid)])
  else:
   pr.waktu_mulai=t;pr.waktu_selesai=t+timedelta(hours=2)
  u=User(nama='Operator Pelanjut Uji',role='operator',status='aktif');db.add(u);await db.flush()
  for i in range(22):
   a=t+timedelta(minutes=i*2);b=a+timedelta(minutes=1)
   j=JedaProses(jenis=jenis,**{field:pr.id},sebab=f'Penyebab uji {i}',mulai=a,selesai=b,dicatat_oleh=uid,dibatalkan_pada=now_local() if i==21 else None)
   db.add(j);await db.flush()
   for aksi,at,user in [('hentikan',a,uid),('lanjutkan',b,u.id)]:
    db.add(JedaCatatan(jeda_id=j.id,aksi=aksi,waktu_kejadian=at,dicatat_pada=at+timedelta(minutes=5),dicatat_oleh=user,sebab=j.sebab,alasan_terlambat='Operator terlambat mencatat'))
  await db.commit();pid=pr.id
 async with await _klien(pg,peran='admin') as c:
  response=await c.get(f'/{path}/{pid}/laporan.pdf')
  detail=await c.get(f'/{path}/{pid}')
 text=baca(response,jenis+'-jeda')
 (OUT/(jenis+'-detail.html')).write_text(detail.text)
 for v in ['Penyebab uji 0','Penyebab uji 21','Dibatalkan','Operator Pelanjut Uji','Dihentikan oleh','Dilanjutkan oleh','Alasan terlambat','1 jam 39 menit','21 menit','Durasi efektif']:
  assert v in text,v
 if jenis=='giling':
  assert '10.883,75 kg' in text and '10.883,75' in detail.text
 if jenis=='pengeringan':
  assert 'Turun 1,00 poin persentase/jam' in ' '.join(text.split())

async def test_sisa_belum_dicatat_tidak_disebut_kosong_di_pdf(pg,pabrik):
 from app.models import PolishingProcess,PolishingSiloUsage
 kode=await _sosoh_selesai(pg,pabrik['user'])
 async with pg() as db:
  pr=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
  usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pr.id))
  usage.berat_akhir_kg=None;usage.berat_terpakai_kg=None
  await db.commit();pid=pr.id
 async with await _klien(pg,peran='admin') as c:
  response=await c.get(f'/riwayat-sosoh/{pid}/laporan.pdf')
 text=baca(response,'sisa-belum-dicatat')
 assert 'Belum dicatat' in text
 assert 'Belum dapat dipastikan' in text
 assert 'Kosong' not in text
