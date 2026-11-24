"""Batas struktur murni, tanpa database, akun, saldo atau request jaringan."""
import pytest
from app.web.stok_kerangka_langsung import sah_descriptor


def valid():
    return dict(versi=1,cap='cap-fixture',konteks='ctx-fixture',sesi='nonce-fixture',
                penyandian='baris-1',potongan=['<section>Struktur saja</section>\n'],
                frames={'bahan':[0],'produk':[0],'karung':[0]})


def test_struktur_tiga_atau_satu_jenis_dan_escape_bytes_dibatasi():
    data=valid();assert sah_descriptor(data)
    data['frames']={'bahan':[0]};assert sah_descriptor(data)
    # '<' di-escape oleh template menjadi enam byte. Batas JSON diperiksa
    # pada bentuk yang dipasang, bukan panjang string sebelum escape.
    data['potongan']=['<'*300000];assert not sah_descriptor(data)


@pytest.mark.parametrize('mutate',[
    lambda d:d.update(versi=2),lambda d:d.update(sesi=''),
    lambda d:d.update(frames={'produk':[0]}),lambda d:d.update(frames={'asing':[0]}),
    lambda d:d.update(potongan=[]),lambda d:d.update(potongan=['']),
    lambda d:d.update(potongan=['x'*524289]),
    lambda d:d['frames'].update(bahan=[True]),lambda d:d['frames'].update(bahan=[-1]),
    lambda d:d['frames'].update(bahan=[1]),lambda d:d['frames'].update(bahan=[]),
    lambda d:d['frames'].update(bahan=[0]*16385),
])
def test_descriptor_tidak_valid_tidak_dipasang(mutate):
    data=valid();mutate(data);assert not sah_descriptor(data)
