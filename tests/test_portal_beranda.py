"""Status pelanggan tidak mengubah bahan menunggu menjadi proses/hasil siap ambil."""
import pytest

from app.web.portal.beranda import kelompok_barang,status_utama
from app.web.portal.navigation import active_menu,MENU,portal_url


def test_bahan_belum_diukur_tidak_hilang_atau_diubah_nol():
    d={'stok':[dict(nama='Gabah basah',kg=None,final=False,lokasi='Pengering')],
       'proses':[]}
    bahan,hasil=kelompok_barang(d)
    assert bahan[0]['kg'] is None and not hasil
    assert status_utama(d,[])['jenis']=='bahan'
    assert d['stok'][0].get('nama_pelanggan') is None  # proyeksi tidak menulis sumber


def test_transit_dan_proses_yang_benar_benar_dimulai_dibedakan():
    d={'stok':[],'proses':[]}
    assert status_utama(d,[{'nama':'Silo 2'}])['label']=='Menunggu proses'
    d['proses']=[dict(jenis='giling',status='proses')]
    assert status_utama(d,[{'nama':'Silo 2'}])['label']=='Sedang diproses'


def test_saldo_hasil_tidak_mengklaim_siap_diambil():
    d={'stok':[dict(nama='Beras',kg=100,final=False,lokasi='Gudang 2',kemasan_kg=0)],'proses':[]}
    bahan,hasil=kelompok_barang(d)
    assert not bahan and hasil[0]['kg']==100
    utama=status_utama(d,[])
    assert utama['label']=='Hasil tercatat' and 'siap' not in utama['judul']
    assert 'petugas' in utama['isi']


def test_tiket_menunggu_tidak_disebut_sudah_diterima():
    d={'penerimaan':[dict(status='Belum diterima')],'proses':[],'stok':[]}
    utama=status_utama(d,[])
    assert utama['label']=='Menunggu penerimaan'
    assert 'sudah diterima' not in utama['judul']


def test_tidak_ada_penjumlahan_lintas_tahap_dan_saldo_negatif_tetap_terlihat():
    d={'stok':[dict(nama='Gabah',kg=1000,final=True,lokasi='Silo'),
               dict(nama='PK',kg=500,final=True,lokasi='Tumpukan'),
               dict(nama='Beras',kg=-10,final=True,lokasi='G2',kemasan_kg=0),
               dict(nama='PK',kg=0,final=True,lokasi='Tumpukan')]}
    bahan,hasil=kelompok_barang(d)
    assert [r['kg'] for r in bahan]==[1000,500]
    assert [r['kg'] for r in hasil]==[-10]


@pytest.mark.parametrize('path,active',[
    ('/pelanggan/','ringkasan'),('/pelanggan/ringkasan','ringkasan'),
    ('/pelanggan/jasa-saya','pekerjaan'),('/pelanggan/barang-saya','stok'),
    ('/pelanggan/barang-keluar/5','stok'),('/pelanggan/retur/2','stok'),
    ('/pelanggan/jasa/3/nota','laporan'),('/pelanggan/jasa/3/nota.pdf','laporan'),
    ('/pelanggan/riwayat-qc/gabah-basah','pekerjaan'),('/pelanggan/riwayat-giling/4','pekerjaan'),
    ('/pelanggan/serah-terima','laporan'),('/jasa/pelanggan/1','pekerjaan')])
def test_menu_aktif_mengikuti_konteks_pelanggan(path,active):
    assert active_menu(path)==active


def test_hanya_empat_tujuan_utama_dan_tautan_baru_diizinkan():
    assert [label for _,label,_ in MENU]==['Beranda','Jasa Saya','Barang Saya','Dokumen']
    assert portal_url('/jasa-saya')=='/pelanggan/jasa-saya'
    assert portal_url('/barang-saya')=='/pelanggan/barang-saya'
