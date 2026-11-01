from app.services.berjalan import Baris,Berjalan
from app.services.kelompok_kerja import bagi
from app.web.pekerjaan_ringkas import ringkasan_proses

def test_identitas_proses_bukan_jumlah_silo_atau_informasi():
 p=Baris('LOT-1','silo A','',fase='dryer',status_proses='Dijeda')
 p2=Baris('LOT-1','silo B','',fase='dryer',status_proses='Dijeda')
 info=Baris('PK-SISA','hasil proses yang sudah selesai','')
 action=Baris('WAJIB','perlu dikerjakan','',aksi='catat_packing')
 k=bagi(Berjalan(berjalan=[p,p2],menunggu=[info,action]))
 assert ringkasan_proses(k.berjalan)==dict(jumlah=1,status=[('Dijeda',1)])
 assert k.tindakan==[action] and k.informasi==[info]
