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


@pytest.mark.parametrize('label,nilai,skor', [
    ('Kadar air',10.9,0),('Kadar air',11,50),('Kadar air',12,90),
    ('Kadar air',13,100),('Kadar air',14,90),('Kadar air',14.5,80),
    ('Kadar air',15,70),('Kadar air',15.5,60),('Kadar air',16,50),
    ('Kadar air',16.5,50),('Kadar air',16.6,10),
    ('Butir patah',19.9,100),('Butir patah',20,90),('Butir patah',25,80),
    ('Butir patah',30,70),('Butir patah',35,60),('Butir patah',40,60),
    ('Butir patah',40.1,50),('Butir patah',50,50),('Butir patah',50.1,10),
    ('Susut',12,100),('Susut',12.1,90),('Susut',13,90),('Susut',13.1,80),
    ('Susut',14.1,70),('Susut',15.1,60),('Susut',16.1,50),('Susut',17.1,10),
])
def test_rentang_yang_dijelaskan_sama_dengan_perhitungan_kartu(label,nilai,skor):
    from app.services.mutu_pk import aturan_angka
    assert _nilai_kualitas([(label,str(nilai)+'%')])==(skor,1)
    assert aturan_angka(label,nilai)[0]==skor


def test_rincian_mempertahankan_enam_baris_dan_pembagi_per_komponen():
    from types import SimpleNamespace as Log
    from app.services.mutu_pk import penilaian_dari_log
    p=penilaian_dari_log([
        Log(kadar_air=13,broken_persen=None,butir_kuning='bersih'),
        Log(kadar_air=14,broken_persen=0,butir_kuning='sedikit'),
    ])
    assert len(p['rows'])==6 and p['n']==3 and p['putaran']==2
    ka,broken,susut,kuning,gabah,merang=p['rows']
    assert (ka['hasil'],ka['n'],ka['skor'])==('13,5%',2,100)
    assert (broken['hasil'],broken['n'],broken['skor'])==('0,0%',1,100)
    assert (kuning['hasil'],kuning['skala'],kuning['kategori'],kuning['skor'])==('Sedikit','0,50',1,80)
    assert all(r['skor'] is None and r['n']==0 for r in [susut,gabah,merang])
    assert p['nilai']==pytest.approx(280/3) and p['kelas']=='A2'
    assert p['rumus']=='100 + 100 + 80' and not p['lengkap']


def test_bersih_dan_parah_dirata_skala_sebelum_konversi_skor():
    from types import SimpleNamespace as Log
    from app.services.mutu_pk import penilaian_dari_log
    p=penilaian_dari_log([Log(butir_kuning='bersih'),Log(butir_kuning='parah')])
    assert p['nilai']==70 and p['rows'][3]['skala']=='2,00'
    assert p['rows'][3]['hasil']=='Sedang'
    kosong=penilaian_dari_log([])
    assert len(kosong['rows'])==6 and kosong['nilai'] is None
    assert kosong['kelas'] is None and kosong['n']==0 and kosong['total']==0
