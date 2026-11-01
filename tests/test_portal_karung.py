from app.web.portal.karung import baris_kosong


def test_karung_kosong_mempertahankan_saldo_asli_dan_tidak_menampilkan_kombinasi_nol():
    base=dict(nama='Karung laminasi',merk='Mitra',ukuran=50,gudang='Gudang 2',kode='laminasi')
    rows=baris_kosong([{**base,'lembar':280},{**base,'merk':'Milik orang lain','lembar':0},
        {**base,'merk':'Perlu diperiksa','lembar':-2}])
    assert [r['lembar'] for r in rows]==[280,-2]
    assert all('kode' not in r for r in rows)


def test_berat_sementara_tetap_terlihat_di_luar_lipatan_riwayat_stok():
    from bs4 import BeautifulSoup
    from app.web.portal.presentation import read_only
    html='''<main class="pk-detail produk-detail"><header class="pk-detail__hero"><h1>Beras Medium</h1></header>
    <section aria-labelledby="ringkasan-produk"><h2>Ringkasan stok</h2><p class="bantu">1.000 kg berasal dari proses berjalan. Hasilnya belum final.</p></section>
    <section aria-labelledby="rincian-produk"><div class="stok-produk-kartu"><details class="padat" open><summary>Ringkasan berulang 1.000 kg</summary>
    <div class="anak"><p>Perkiraan asal stok 1.000 kg</p><section class="pelanggan-kemasan-barang"><h2>Karung berisi</h2><p>20 karung</p></section></div></details></div></section></main>'''
    s=BeautifulSoup(read_only(html,'/stok-produk-jasa/detail?jenis=medium'),'html.parser')
    assert s.select_one('.pelanggan-peringatan-stok').find_parent('details') is None
    assert '1.000 kg' in s.select_one('.pelanggan-peringatan-stok').get_text()
    assert s.select_one('.pelanggan-kemasan-barang').find_parent('details') is None
    assert 'Perkiraan asal stok' in s.get_text() and 'Ringkasan berulang' not in s.get_text()
