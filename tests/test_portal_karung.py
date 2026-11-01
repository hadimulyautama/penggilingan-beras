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
    html='''<main class="pk-detail produk-detail"><header class="pk-detail__hero"><h1>Beras Medium</h1><div class="pk-detail__weight"><span>Sisa di gudang</span><strong>1.000 kg</strong></div></header>
    <section aria-labelledby="ringkasan-produk"><h2>Ringkasan stok</h2><p class="bantu">1.000 kg berasal dari proses berjalan. Hasilnya belum final.</p></section>
    <section aria-labelledby="rincian-produk"><div class="stok-produk-kartu"><details class="padat" open><summary>Ringkasan berulang 1.000 kg</summary>
    <div class="anak"><p>Perkiraan asal stok 1.000 kg</p><section class="pelanggan-kemasan-barang"><h2>Karung berisi</h2><p>20 karung</p></section></div></details></div></section></main>'''
    s=BeautifulSoup(read_only(html,'/stok-produk-jasa/detail?jenis=medium'),'html.parser')
    assert s.select_one('.pelanggan-status-berat').find_parent('details') is None
    assert 'Berat sementara' in s.select_one('.pelanggan-status-berat').get_text()
    assert s.select_one('.pelanggan-status-berat').parent.get('class')==['pk-detail__weight']
    assert s.find('p',string='1.000 kg berasal dari proses berjalan. Hasilnya belum final.').find_parent('details')
    assert s.select_one('.pelanggan-kemasan-barang').find_parent('details') is None
    assert 'Perkiraan asal stok' in s.get_text() and 'Ringkasan berulang' not in s.get_text()


def test_jumlah_karung_mempertahankan_perkiraan_tanpa_berat_kedua():
    from app.web.portal.karung import ringkasan_berisi
    r=ringkasan_berisi('sisa 2 karung ~ 158,4 kg')
    assert r==dict(jumlah='2 karung',label='Setara sekitar 2 karung',perkiraan=True)
    r=ringkasan_berisi('sisa 128 karung (bobot truk belum final)')
    assert r==dict(jumlah='128 karung',label='128 karung tercatat',perkiraan=False)
    assert ringkasan_berisi('kurang dari 1 karung — 0,4 kg')['jumlah']=='kurang dari 1 karung'


def test_ukuran_nominal_dan_berat_kelompok_tidak_dihitung_ulang():
    from types import SimpleNamespace
    from bs4 import BeautifulSoup
    from app.web.tampilan import templates
    template=templates.env.get_template('portal/_kemasan_barang.html')
    row=dict(bentuk='Kemasan',ukuran=50,karung=20,kg=1000,merk='Mitra',bahan='laminasi')
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='medium'),baris_kemasan=[row],PORTAL_BERAT_TUNGGAL=True),'html.parser')
    assert '20 karung' in s.get_text() and 'Ukuran karung: 50 kg (nominal)' in s.get_text()
    assert '1.000 kg' not in s.get_text() and 'Isi per karung' not in s.get_text()
    assert 'laminasi' in s.select_one('.pelanggan-tentang-kemasan').get_text()
    other=dict(bentuk='Kemasan',ukuran=25,karung=4,kg=100,merk='Mitra',bahan='laminasi')
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='medium'),baris_kemasan=[row,other],PORTAL_BERAT_TUNGGAL=False),'html.parser')
    assert '1.000 kg' in s.get_text() and '100 kg' in s.get_text()
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='broken'),baris_kemasan=[row],PORTAL_BERAT_TUNGGAL=True),'html.parser')
    assert '20 karung tercatat' in s.get_text() and 'Setara sekitar' not in s.get_text()


def test_pecahan_karung_memakai_bobot_batch_bukan_ukuran_nominal():
    from types import SimpleNamespace
    from app.web.portal.karung import ringkasan_berisi
    batch=SimpleNamespace(jumlah_karung=10,berat_total_kg=800,ukuran_karung_kg=100)
    r=ringkasan_berisi('sisa 2 karung ~ 175,0 kg',batch=batch,sisa_kg=175)
    assert r['label']=='Setara sekitar 2,19 karung' and r['perkiraan']
    r=ringkasan_berisi('kurang dari 1 karung — 0,4 kg',batch=batch,sisa_kg=0.4)
    assert r['label']=='Setara kurang dari 1 karung' and r['perkiraan']


def test_perkiraan_otomatis_dan_curah_terpisah_tanpa_menciptakan_karung_pecahan():
    from types import SimpleNamespace
    from bs4 import BeautifulSoup
    from app.web.tampilan import templates
    template=templates.env.get_template('portal/_kemasan_barang.html')
    auto=dict(bentuk='Kemasan otomatis',ukuran=50,karung=3,kg=150,merk='',bahan='Kemasan otomatis')
    curah=dict(bentuk='Curah',ukuran=0,karung=0,kg=25,merk='',bahan='')
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='broken'),baris_kemasan=[auto,curah],PORTAL_BERAT_TUNGGAL=False),'html.parser')
    groups=s.select('.pelanggan-kemasan-baris')
    assert 'Setara sekitar 3 karung' in groups[0].get_text() and '150 kg' in groups[0].get_text()
    assert 'Perkiraan sisa curah' in groups[1].get_text() and '25 kg' in groups[1].get_text()
    assert 'karung' not in groups[1].get_text() and 'nominal' not in groups[1].get_text()
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='medium'),baris_kemasan=[{**curah,'kg':0.375,'bentuk':'Curah tercatat'}],PORTAL_BERAT_TUNGGAL=False),'html.parser')
    assert '0,375 kg' in s.get_text() and 'Barang curah' in s.get_text() and 'karung' not in s.get_text()
    s=BeautifulSoup(template.render(k=SimpleNamespace(jenis='medium'),baris_kemasan=[{**curah,'kg':-20}],PORTAL_BERAT_TUNGGAL=False),'html.parser')
    assert 'Selisih berat' in s.get_text() and '-20 kg' in s.get_text() and 'Berat curah' not in s.get_text()


def test_mutu_stok_satu_pintu_tetapi_barang_dan_bahan_asal_tidak_dicampur():
    from bs4 import BeautifulSoup
    from app.web.portal.presentation import read_only
    html='''<main class="pk-detail"><header class="pk-detail__hero"><h1>LOT-1</h1></header><div class="pk-detail__grid">
    <section class="pk-detail__quality"><h2>Nilai kualitas</h2><p>Kadar air 13,5%</p></section></div>
    <section aria-labelledby="perhitungan-kualitas-pk"><h2>Perhitungan nilai kualitas</h2><p>Skor 88,75</p></section>
    <section aria-labelledby="riwayat-qc-pk"><p>Putaran 1 · catatan asli</p></section></main>
    <div class="qc-gabah-stok"><section class="qc-gabah-asal"><h2>QC gabah asal</h2><p>Gabah 24,5%</p></section></div>'''
    s=BeautifulSoup(read_only(html,'/stok/pk/detail?gudang=g1&kode=LOT-1'),'html.parser')
    groups=s.select('.pelanggan-mutu-stok');assert len(groups)==1
    group=groups[0];assert group.find_parent(class_='pk-detail') and not group.has_attr('open')
    assert [d.summary.get_text() for d in group.find_all('details',recursive=False)]==['Barang ini','Perhitungan nilai mutu','Riwayat pemeriksaan barang ini','Bahan asal']
    for text in ['Kadar air 13,5%','Skor 88,75','Putaran 1 · catatan asli','Gabah 24,5%']:
        assert group.get_text().count(text)==1
    assert not s.select('.qc-gabah-stok')
