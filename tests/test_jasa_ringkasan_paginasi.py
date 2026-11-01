"""Pagination hanya memilih baris tampilan, bukan mengurangi sumber saldo."""
from copy import deepcopy
from app.services.jasa_pelanggan import halaman_pesanan


def rows():
 return [dict(id=i,kode=f'JAS-{i:03}',status='berjalan' if i%2 else 'selesai',catatan='Catatan pelanggan') for i in range(101,0,-1)]


def test_seluruh_pesanan_dapat_ditelusuri_tanpa_mengubah_sumber():
 source=rows();before=deepcopy(source);seen=[]
 for page in range(1,7):
  result=halaman_pesanan(source,{'halaman':page})
  assert result['jumlah']==101 and len(result['baris'])<=20
  seen.extend(x['id'] for x in result['baris'])
 assert seen==[x['id'] for x in source] and source==before


def test_filter_status_dan_pencarian_hanya_di_pelanggan_tersebut():
 source=rows();r=halaman_pesanan(source,{'status':'selesai','cari':'jas-002'})
 assert [x['id'] for x in r['baris']]==[2]
 assert len(source)==101
 r=halaman_pesanan(source,{'cari':'pelanggan lain'})
 assert r['jumlah']==0 and r['dari']==r['sampai']==0 and r['akhir']==1


def test_fokus_tautan_lama_menemukan_halaman_dan_menjelaskan_filter():
 r=halaman_pesanan(rows(),{'fokus':1,'status':'selesai'})
 assert r['halaman']==6 and r['baris'][0]['id']==1 and r['fokus_di_luar_filter']
 assert r['cari']==r['status']==''
 r=halaman_pesanan(rows(),{'fokus':999999})
 assert r['halaman']==1 and all(x['id']!=999999 for x in r['baris'])


def test_parameter_halaman_tidak_valid_ditangani_tanpa_batas_pesanan_baru():
 for page in ('tidak sah',None,-50):assert halaman_pesanan(rows(),{'halaman':page})['halaman']==1
 assert halaman_pesanan(rows(),{'halaman':999999})['halaman']==6
