from app.services.status_pengiriman import ringkasan
import pytest

@pytest.mark.parametrize('status,ticket,timbang,verifikasi',[
 (['dimuat'],dict(status_tiket='SELESAI',status_transaksi='AKTIF'),'Selesai timbang','Menunggu verifikasi pengiriman'),
 (['selesai'],dict(status_tiket='TERBUKA',status_transaksi='AKTIF'),'Menunggu timbang kedua','Pengiriman terverifikasi'),
 (['dimuat'],dict(status_tiket='SELESAI',status_transaksi='VOID'),'Tiket dibatalkan','Menunggu verifikasi pengiriman'),
 (['selesai','dimuat'],dict(status_tiket='SELESAI'),'Selesai timbang','Sebagian terverifikasi'),
 (['selesai','batal'],None,'Tanpa tiket tertaut','Pengiriman terverifikasi'),
 (['batal'],None,'Tanpa tiket tertaut','Pengiriman dibatalkan'),
 (['perintah'],None,'Tanpa tiket tertaut','Menunggu selesai muat'),
])
def test_dua_status_tidak_saling_menyimpulkan(status,ticket,timbang,verifikasi):
 d=ringkasan(status,ticket);assert d['timbang']==timbang and d['verifikasi']==verifikasi

def test_portal_gabungan_tidak_mengungkap_status_tiket_armada():
 d=ringkasan(['selesai'],None,tertaut=True,dibatasi=True)
 assert d['timbang']=='Tidak ditampilkan pada rincian pelanggan'

def test_tiket_hilang_tidak_dianggap_selesai_dan_jalur_kecil_tetap_admin():
 assert ringkasan(['dimuat'],None,tertaut=True)['timbang']=='Tiket belum dapat dibaca'
 assert ringkasan(['perintah'],None,cepat=True)['berikut'].startswith('Admin')
