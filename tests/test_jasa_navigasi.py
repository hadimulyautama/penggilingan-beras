"""Konteks kembali tidak boleh menjadi pengalihan ke alamat asing."""
import pytest
from app.web.jasa_navigasi import kembali_aman


@pytest.mark.parametrize('nilai',[
    'https://contoh.invalid/jasa','//contoh.invalid/jasa','/barang-keluar/1',
    '/jasa/pelanggan/0','/jasa/pelanggan/-1','/jasa/pelanggan/1/nota',
    '/jasa\\contoh.invalid','javascript:alert(1)','/jasa/%2f%2fcontoh.invalid',
])
def test_tolak_alamat_di_luar_konteks_pelanggan(nilai):
    assert kembali_aman(nilai)==''


def test_hanya_parameter_tampilan_dipertahankan():
    assert kembali_aman('/jasa/pelanggan/4?tab=stok&cari=Catur&buka=undo')=='/jasa/pelanggan/4?tab=stok&cari=Catur'
    assert kembali_aman('/jasa?status=selesai&halaman=2')=='/jasa?status=selesai&halaman=2'
