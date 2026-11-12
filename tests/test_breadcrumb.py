from types import SimpleNamespace as NS
import pytest
from app.web.breadcrumb import susun

@pytest.mark.parametrize('path,ctx,title,labels,back',[
 ('/',{},'Beranda',['Beranda'],None),
 ('/stok',{},'Stok',['Beranda','Stok'],'/'),
 ('/stok?tab=produk',{},'Stok',['Beranda','Stok','Produk'],'/stok'),
 ('/stok-produk/detail',{'breadcrumb_detail':'Premium 25 kg'},'Detail produk',['Beranda','Stok','Produk','Premium 25 kg'],'/stok?tab=produk'),
 ('/stok/karung/detail',{'breadcrumb_detail':'PKP-01'},'Stok karung',['Beranda','Stok','Karung','PKP-01'],'/stok?tab=karung'),
 ('/kepemilikan',{'breadcrumb_detail':'Riwayat alih kepemilikan'},'Riwayat alih kepemilikan',['Beranda','Stok','Riwayat alih kepemilikan'],'/stok'),
 ('/kepemilikan/8',{'breadcrumb_detail':'PKM-008','kembali':'/kepemilikan?kind=pk&status=aktif'},'Riwayat alih kepemilikan',['Beranda','Stok','Riwayat alih kepemilikan','PKM-008'],'/kepemilikan?kind=pk&status=aktif'),
 ('/barang-keluar/3',{'k':{'rec':NS(kode='OUT-003')},'filter_query':'q=Suroto&status=dimuat'},'OUT-003',['Beranda','Barang Keluar','OUT-003'],'/barang-keluar?q=Suroto&status=dimuat'),
 ('/barang-keluar/3/verifikasi',{'k':{'rec':NS(kode='OUT-003')}},'Verifikasi pengiriman',['Beranda','Barang Keluar','OUT-003','Verifikasi pengiriman'],'/barang-keluar/3'),
 ('/muatan?perintah=3',{'PENGIRIMAN_URL':'/muatan'},'Catat muatan',['Beranda','Muatan'],'/'),
 ('/riwayat-giling/4',{'breadcrumb_induk':{'nama':'Riwayat Penggilingan','alamat':'/riwayat-giling'},'breadcrumb_detail':'LOT-004'},'Riwayat Penggilingan',['Beranda','Riwayat','Riwayat Penggilingan','LOT-004'],'/riwayat-giling'),
 ('/riwayat-sosoh/4',{'breadcrumb_detail':'POL-004'},'Riwayat sosoh',['Beranda','Riwayat','Riwayat Penyosohan','POL-004'],'/riwayat-sosoh'),
 ('/riwayat-qc/pk-luar/4',{'breadcrumb_detail':'QC-004'},'Hasil QC',['Beranda','Riwayat','Riwayat QC','PK luar','QC-004'],'/riwayat-qc/pk-luar'),
 ('/riwayat-retur-supplier/4',{'breadcrumb_detail':'RTR-004'},'Retur ke Supplier',['Beranda','Barang Masuk','Retur ke Supplier','RTR-004'],'/riwayat-retur-supplier'),
 ('/retur-supplier/4/tindakan',{'breadcrumb_detail':'RTR-004'},'Koreksi retur supplier',['Beranda','Barang Masuk','Retur ke Supplier','RTR-004','Koreksi retur supplier'],'/retur-supplier/4'),
 ('/proses-aktif/sosoh/POL-4',{'breadcrumb_detail':'POL-4'},'Proses sosoh POL-4',['Beranda','Pekerjaan','POL-4'],'/pekerjaan?tab=berjalan'),
 ('/koreksi-bahan/sosoh/POL-4',{'breadcrumb_detail':'POL-4','kembali':'/proses-aktif/sosoh/POL-4'},'Koreksi POL-4',['Beranda','Pekerjaan','POL-4','Koreksi bahan proses'],'/proses-aktif/sosoh/POL-4'),
 ('/pengaturan/silo',{},'Pengaturan silo',['Beranda','Pengaturan','Pengaturan silo'],'/pengaturan'),
])
def test_hierarki_dan_kembali_satu_induk(path,ctx,title,labels,back):
 d=susun(path,ctx,title);assert [x['nama'] for x in d['items']]==labels;assert d['kembali']==back
 assert d['items'][-1]['alamat'] is None
 assert not back or back==d['items'][-2]['alamat']
 assert all(a['nama'].casefold()!=b['nama'].casefold() for a,b in zip(d['items'],d['items'][1:]))

@pytest.mark.parametrize('target',['https://jahat.test/riwayat-giling','//jahat.test/riwayat-giling','/riwayat-giling/4','/stok','/riwayat-giling\\x'])
def test_kembali_tidak_boleh_melompati_keluarga_atau_ke_dirinya(target):
 d=susun('/riwayat-giling/4',{'breadcrumb_detail':'LOT-4','kembali':target},'Detail');assert d['kembali']=='/riwayat-giling'

def test_filter_terbaru_tidak_dikalahkan_link_kembali_tanpa_query():
 d=susun('/barang-keluar/3',{'breadcrumb_detail':'OUT-3','kembali':'/barang-keluar','filter_query':'q=Suroto&status=dimuat'},'Detail')
 assert d['kembali']=='/barang-keluar?q=Suroto&status=dimuat'
 d=susun('/proses-aktif/sosoh/POL-3',{'breadcrumb_detail':'POL-3','kembali':'/pekerjaan'},'Detail')
 assert d['kembali']=='/pekerjaan?tab=berjalan'
