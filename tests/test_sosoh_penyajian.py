"""Rincian sosoh menamai ulang informasi tanpa mengubah angka/sumber bersama."""
from copy import deepcopy
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def test_bahan_awal_selalu_disebut_termasuk_nilai_sama_dan_belum_diketahui():
    akar = Path(__file__).resolve().parents[1]
    env = Environment(loader=FileSystemLoader([str(akar / 'app/web/templates'),
                                              str(akar / 'hmu_tampilan/templates')]))
    kelompok = [dict(nama='Silo B', berat='1.000 kg', status='Dilepaskan',
                      angka=[('Awal', '1.000 kg'), ('Tambahan', '0 kg'), ('Sisa akhir', '0 kg'), ('Terpakai', '1.000 kg')],
                      total_kg=1000, tambahan_kg=0, bahan=[], sumber=[]),
                dict(nama='Silo B', berat='Belum diketahui', status='Masih terikat proses',
                     angka=[('Awal', 'Belum diketahui'), ('Tambahan', 'Belum diketahui'), ('Sisa akhir', 'Belum dicatat')],
                     bahan=[], sumber=[]),
                dict(nama='Silo A', berat='Belum diketahui', status='Data proses lama',
                     bahan=[], sumber=[])]
    awal = deepcopy(kelompok)
    khusus = env.get_template('_bahan_silo_sosoh.html').module.bahan_silo(kelompok)
    bersama = env.get_template('_bahan_silo.html').module.bahan_silo(kelompok)
    assert khusus.count('<dt>Bahan awal</dt>') == 3
    assert khusus.count('<dt>Bahan awal</dt><dd>Belum diketahui</dd>') == 2
    assert '<dt>Bahan awal</dt><dd>1.000 kg</dd>' in khusus
    assert '<dt>Bahan awal</dt><dd>Belum diketahui</dd>' in khusus
    assert 'Pemakaian 1' in khusus and 'Pemakaian 2' in khusus
    assert 'Bahan awal' not in bersama  # Proses lain tetap memakai macro lama.
    assert kelompok == awal


def test_ringkasan_hasil_menjaga_seluruh_jenis_spek_dan_total_yang_diberikan():
    akar = Path(__file__).resolve().parents[1]
    env = Environment(loader=FileSystemLoader(str(akar / 'app/web/templates')), autoescape=True)
    spek = 'Mutu A, ukuran 5 · catatan panjang <uji>'
    baris = [['premium · ' + spek, '4.600 kg', 'Keterangan sumber'],
             ['beras_b', '200 kg', '—'], ['bekatul', '100 kg', '—'],
             ['jenis_baru · Spek warisan', '7 kg', '—']]
    bagian = dict(judul='Hasil sosoh keluar', jumlah=4, parameter=None,
                  keterangan='', baris=baris, halaman_total=1)
    awal = deepcopy(bagian)
    hasil = env.get_template('_hasil_sosoh_detail.html').render(bagian=bagian, d={'bagian':[bagian]})
    for label in ['Premium', 'Beras B', 'Bekatul', 'Jenis Baru']:
        assert f'<h3>{label}</h3>' in hasil
    assert 'Mutu A, ukuran 5 · catatan panjang &lt;uji&gt;' in hasil
    assert 'Keterangan sumber' in hasil and 'Spek warisan' in hasil
    for berat in ['4.600 kg', '200 kg', '100 kg', '7 kg']:
        assert f'<strong>{berat}</strong>' in hasil
    assert bagian == awal
