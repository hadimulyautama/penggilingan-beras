from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as N
import pytest
from app.web.pdf_proses import laju_kadar_air,angka
from app.services.asal_silo_pdf import alokasi_sumber

@pytest.mark.parametrize('minutes,awal,kini,expected',[(60,25,24,'Turun 1,00 poin persentase/jam'),(120,25,23,'Turun 1,00 poin persentase/jam'),(.5,25,24,'Turun 1,00 poin dalam 30 detik (belum 1 jam)'),(60,24,25,'Naik 1,00 poin persentase/jam'),(0,25,24,'Belum dapat dihitung'),(60,None,24,'Belum dapat dihitung')])
def test_laju_bukan_ekstrapolasi_detik(minutes,awal,kini,expected):
 t=datetime(2026,10,19,tzinfo=timezone.utc)
 assert expected in laju_kadar_air(awal,kini,t,t+timedelta(minutes=minutes))

@pytest.mark.parametrize('value,text',[(10883.75,'10.883,75'),(.001,'0,001'),(0,'0'),(None,'Belum dicatat')])
def test_angka_utuh(value,text):
 assert angka(value)==text

def test_fifo_semua_pemakaian_dan_pemilik_tidak_mengulang_saldo():
 t=datetime(2026,10,19,tzinfo=timezone.utc)
 a=dict(code='A',owner='Pemilik A');b=dict(code='B',owner='Pemilik B')
 movements={1:[(t,1,100,a),(t+timedelta(hours=2),1,50,b)]}
 def use(i,kg):
  return N(id=i,silo_id=1,berat_awal_kg=kg,berat_masuk_kg=0,berat_akhir_kg=0,berat_terpakai_kg=kg),N(waktu_selesai=t+timedelta(hours=4),waktu_mulai=t)
 histories=[use(1,100),use(2,50)]
 closed={1:t+timedelta(hours=1),2:t+timedelta(hours=3)}
 r=alokasi_sumber(movements,histories,closed)
 assert [(x['code'],x['weight'],x['owner']) for x in r[1]]==[('A',100,'Pemilik A')]
 assert [(x['code'],x['weight'],x['owner']) for x in r[2]]==[('B',50,'Pemilik B')]

def test_pernyataan_kosong_mengakhiri_saldo_asal_warisan():
 t=datetime(2026,10,19,tzinfo=timezone.utc)
 movements={1:[(t,1,112.5,dict(code='Lama')),(t+timedelta(hours=2),1,50,dict(code='Baru'))]}
 proc=N(waktu_selesai=t+timedelta(hours=4),waktu_mulai=t)
 a=N(id=1,silo_id=1,berat_awal_kg=100,berat_masuk_kg=0,berat_akhir_kg=0,berat_terpakai_kg=100)
 b=N(id=2,silo_id=1,berat_awal_kg=50,berat_masuk_kg=0,berat_akhir_kg=0,berat_terpakai_kg=50)
 r=alokasi_sumber(movements,[(a,proc),(b,proc)],{1:t+timedelta(hours=1),2:t+timedelta(hours=3)})
 assert [(x['code'],x['weight']) for x in r[2]]==[('Baru',50)]
