"""Status pelanggan tidak mengubah bahan menunggu menjadi proses/hasil siap ambil."""
import pytest

from app.web.portal.beranda import kelompok_barang,status_utama,progres_berjalan
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
    ('/pelanggan/barang-keluar/5','pengambilan'),('/pelanggan/retur/2','stok'),
    ('/pelanggan/jasa/3/nota','laporan'),('/pelanggan/jasa/3/nota.pdf','laporan'),
    ('/pelanggan/riwayat-qc/gabah-basah','pekerjaan'),('/pelanggan/riwayat-giling/4','pekerjaan'),
    ('/pelanggan/serah-terima','laporan'),('/jasa/pelanggan/1','pekerjaan')])
def test_menu_aktif_mengikuti_konteks_pelanggan(path,active):
    assert active_menu(path)==active


def test_menu_barang_dan_riwayat_memiliki_tujuan_tersendiri():
    assert [label for _,label,_ in MENU]==['Beranda','Barang masuk','Barang Saya','Jasa Saya','Riwayat proses','Pengambilan barang','Dokumen']
    assert portal_url('/jasa-saya')=='/pelanggan/jasa-saya'
    assert portal_url('/barang-saya')=='/pelanggan/barang-saya'


def test_kemajuan_asli_terpisah_dari_rendemen_dan_tugas_operator():
    from types import SimpleNamespace
    from app.services.berjalan import Baris
    rows=[Baris(kode='PGR-1',isi='',keadaan='',fase='dryer',maju=0),
          Baris(kode='LOT-1',isi='',keadaan='',fase='giling',rendemen_sementara=65),
          Baris(kode='ASING',isi='',keadaan='',fase='giling')]
    p=progres_berjalan(rows,SimpleNamespace(codes={'PGR-1','LOT-1'}))
    assert len(p)==2 and p[0]['maju']==0
    assert p[1]['maju'] is None and p[1]['rendemen']==65
    assert all('aksi' not in r and 'tombol' not in r for r in p)


def test_penerimaan_hanya_barang_diterima_bukan_antrean_atau_penolakan():
    from app.web.portal.beranda import penerimaan_diterima
    rows=[dict(jenis='Gabah basah',catatan=[dict(model='gabah',status='baru',berat=None),dict(model='gabah',status='ditolak',berat=100)]),
          dict(jenis='PK',catatan=[dict(model='pk',status='baru',berat=0)]),
          dict(jenis='PK',catatan=[dict(model='pk',status='diterima',berat=None)]),
          dict(jenis='Gabah kering',status='Belum diterima',catatan=[])]
    result=penerimaan_diterima(rows)
    assert len(result)==2 and all(r['status']=='Sudah diterima' for r in result)
    assert all(len(r['catatan'])==1 and r['catatan'][0]['berat'] is None for r in result)
    assert len(rows[0]['catatan'])==2  # pembaca asal tidak dimutasi
