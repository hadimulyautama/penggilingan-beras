"""Enam komponen QC berpengaruh sama besar pada nilai kualitas PK."""
import pytest

from app.services.stok import _nilai_kualitas, _kelas_kualitas

ANGKA_BAIK = [('Kadar air','13,5%'),('Butir patah','10,0%'),('Susut','10,0%')]
FISIK_BERSIH = [('Butir kuning','Bersih'),('Gabah','Bersih'),('Merang','Bersih')]


def test_enam_komponen_bersih_memperoleh_nilai_penuh():
    assert _nilai_kualitas(ANGKA_BAIK+FISIK_BERSIH) == (100,6)


@pytest.mark.parametrize('komponen', ['Butir kuning','Gabah','Merang'])
@pytest.mark.parametrize('nilai,skor', [('Bersih',100),('Sedikit',80),('Sedang',70),('Banyak',60),('Parah',10)])
def test_setiap_komponen_fisik_berbobot_sama_dengan_konversi_pemilik(komponen,nilai,skor):
    fisik=[(nama,nilai if nama==komponen else 'Bersih') for nama,_ in FISIK_BERSIH]
    total,n = _nilai_kualitas(ANGKA_BAIK+fisik)
    assert total == pytest.approx((5*100+skor)/6)
    assert n == 6


def test_penilaian_fisik_dapat_menurunkan_kelas_kualitas():
    total,n = _nilai_kualitas(ANGKA_BAIK+[(nama,'Parah') for nama,_ in FISIK_BERSIH])
    assert (total,n)==(55,6)
    assert _kelas_kualitas(total)=='D'


def test_fisik_saja_dapat_dinilai_dan_catatan_lab_tidak_dijadikan_angka():
    total,n=_nilai_kualitas([('Butir kuning','Bersih'),('Gabah','Sedikit'),
                            ('Merang','Parah'),('Catatan lab','100')])
    assert total==pytest.approx(190/3)
    assert n==3


def test_data_lama_kosong_tidak_dianggap_bersih_atau_nol():
    for kosong in ('Belum dinilai','',None):
        assert _nilai_kualitas(ANGKA_BAIK+[(nama,kosong) for nama,_ in FISIK_BERSIH])==(100,3)
    assert _nilai_kualitas([('Butir kuning','Belum dinilai'),('Catatan lab','Bersih')])==(None,0)


@pytest.mark.parametrize('jenis',['KL','KS','MIX'])
def test_asal_pk_tidak_menambah_atau_mengurangi_skor(jenis):
    assert _nilai_kualitas(ANGKA_BAIK+FISIK_BERSIH+[('Kondisi PK',jenis)])==(100,6)
