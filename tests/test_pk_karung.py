"""Penjaga angka surat jalan dan keraguan alat, tanpa ambang usaha."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.penggilingan.gudang2.karung import bobot_per_karung, selisih_kiriman, peringatan_karung


def batch(n=128,w=10140,u=80,sumber='timbangan'):
    return SimpleNamespace(jumlah_karung=n, berat_total_kg=w, ukuran_karung_kg=u,sumber_berat=sumber)


@pytest.mark.parametrize('n,w',[(None,10140),(0,10140),(128,None)])
def test_r_tidak_dikarang_tanpa_n_atau_w(n,w):
    assert bobot_per_karung(batch(n,w)) is None


def test_r_milik_partai_bukan_ukuran_global():
    assert bobot_per_karung(batch()) == Decimal(10140)/128
    assert bobot_per_karung(batch(100,4950,50)) == Decimal('49.5')


@pytest.mark.parametrize('selisih',[-5,0,5])
def test_dalam_keraguan_tidak_disebut_kurang_kirim(selisih):
    teks=selisih_kiriman(batch(w=10240-selisih),'UD Karung')
    assert 'masih dalam keraguan pembacaan timbangan' in teks
    assert 'kurang terbaca' not in teks


@pytest.mark.parametrize('selisih,persen',[(6,'0,06%'),(100,'0,98%')])
def test_selisih_di_atas_lima_disebut_berikut_keraguan_dan_pemasok(selisih,persen):
    teks=selisih_kiriman(batch(w=10240-selisih),'UD Karung')
    assert 'UD Karung' in teks and 'kurang terbaca' in teks
    assert persen in teks and '±5 kg' in teks


def test_perkiraan_belum_disebut_selisih_kiriman():
    assert selisih_kiriman(batch(sumber='perkiraan'),'UD Karung') is None


def test_simpangan_karung_adalah_peringatan_bukan_penolakan():
    assert 'Periksa jumlah karung' in peringatan_karung(batch())
    assert 'tetap diterima' in peringatan_karung(batch())
    assert peringatan_karung(batch(128,10240)) is None


@pytest.mark.asyncio
async def test_pilihan_kg_tetap_dapat_dipilih_di_borang(monkeypatch):
    from tests.test_gudang2_operator import _menu_g2
    menu=await _menu_g2(monkeypatch)
    aksi=next(a for a in menu if a['id']=='pindah_tumpukan_silo')
    medan={f['name']:f for f in aksi['fields']}
    assert 'jumlah_karung' in medan
    assert medan['hasil_timbang']['options'][1][0] == 'ya'
    assert medan['hasil_timbang']['bawaan'] == 'karung'


def test_koreksi_komponen_tetap_tidak_menghitung_ulang_karung_dua_kali():
    from app.models import PkPurchaseBatch, PkTumpukanToSilo, PolishingSiloUsage
    b=PkPurchaseBatch(jumlah_karung=128,berat_total_kg=10140)
    m=PkTumpukanToSilo(jumlah_karung=2,batch=b,selama_proses=True)
    usage=PolishingSiloUsage(berat_awal_kg=0,berat_masuk_kg=10,pemindahan_karung=[m])
    usage.id=1
    usage.berat_masuk_kg=usage.berat_masuk_kg + 50
    assert usage.masuk_tetap_kg == 60
    assert usage.berat_masuk_kg == Decimal('218.4375')
