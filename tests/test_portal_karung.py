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
    assert 'Hasil sementara' in s.select_one('.pelanggan-peringatan-stok').get_text()
    assert s.find('p',string='1.000 kg berasal dari proses berjalan. Hasilnya belum final.').find_parent('details')
    assert s.select_one('.pelanggan-kemasan-barang').find_parent('details') is None
    assert 'Perkiraan asal stok' in s.get_text() and 'Ringkasan berulang' not in s.get_text()


def test_jumlah_karung_mempertahankan_perkiraan_tanpa_berat_kedua():
    from app.web.portal.karung import ringkasan_berisi
    r=ringkasan_berisi('sisa 2 karung ~ 158,4 kg')
    assert r==dict(jumlah='2 karung',label='Perkiraan sisa: 2 karung',perkiraan=True)
    r=ringkasan_berisi('sisa 128 karung (bobot truk belum final)')
    assert r==dict(jumlah='128 karung',label='128 karung tercatat',perkiraan=False)
    assert ringkasan_berisi('kurang dari 1 karung — 0,4 kg')['jumlah']=='kurang dari 1 karung'


def test_ukuran_nominal_dan_berat_kelompok_tidak_dihitung_ulang():
    from types import SimpleNamespace
    from bs4 import BeautifulSoup
    from app.web.tampilan import templates
    template=templates.env.get_template('portal/_kemasan_barang.html')
    row=dict(ukuran=50,karung=20,kg=1000,merk='Mitra',bahan='laminasi')
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='medium'),baris_kemasan=[row],PORTAL_BERAT_TUNGGAL=True),'html.parser')
    assert '20 karung' in s.get_text() and 'Ukuran nominal karung: 50 kg' in s.get_text()
    assert '1.000 kg' not in s.get_text() and 'Isi per karung' not in s.get_text()
    assert s.find('p',string='laminasi').find_parent('details')
    other=dict(ukuran=25,karung=4,kg=100,merk='Mitra',bahan='laminasi')
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='medium'),baris_kemasan=[row,other],PORTAL_BERAT_TUNGGAL=False),'html.parser')
    assert '1.000 kg' in s.get_text() and '100 kg' in s.get_text()
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='broken'),baris_kemasan=[row],PORTAL_BERAT_TUNGGAL=True),'html.parser')
    assert s.get_text().count('Perkiraan')==1 and '20 karung' in s.get_text()
