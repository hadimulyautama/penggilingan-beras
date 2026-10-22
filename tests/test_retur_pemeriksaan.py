from decimal import Decimal as D

import pytest

from app.services.retur_pemeriksaan import BarisBobot, periksa_bobot


def periksa(bobot, **opsi):
    return periksa_bobot([BarisBobot(D('500'), 20, D('.1'))],
                         tiket_selesai=True, berat_tiket_kg=bobot, **opsi)


@pytest.mark.parametrize('bobot', ['498', '499.99', '500', '500.01', '502'])
def test_batas_positif_negatif_inklusif(bobot):
    hasil = periksa(D(bobot))
    assert hasil.status == 'sesuai'
    assert hasil.toleransi_kg == D('2')
    assert hasil.berat_rincian_kg == D('500')  # Tara tidak dipotong dari stok.


@pytest.mark.parametrize('bobot', ['497.99', '502.01'])
def test_di_luar_batas_melekatkan_kewajiban_manual(bobot):
    hasil = periksa(D(bobot))
    assert hasil.status == 'perlu_koreksi'
    assert hasil.wajib_manual
    setelah = periksa(D('500'), pernah_selisih_besar=hasil.wajib_manual)
    assert setelah.status == 'calon_manual'
    assert setelah.wajib_manual


def test_tidak_memakai_batas_lama_dua_kg_atau_persentase():
    hasil = periksa_bobot([BarisBobot(D('25000'), 1000, D('.01'))],
                         tiket_selesai=True, berat_tiket_kg=D('25011'))
    assert hasil.status == 'perlu_koreksi'  # Batas lama 50 kg akan meloloskan.
    kecil = periksa_bobot([BarisBobot(D('25'), 1, D('.1'))],
                         tiket_selesai=True, berat_tiket_kg=D('26'))
    assert kecil.status == 'perlu_koreksi'  # Tidak ada lantai 2 kg.


@pytest.mark.parametrize('tara', [None, D('0'), D('-1'), D('NaN'), D('Infinity')])
def test_tara_belum_lengkap_tidak_dianggap_nol(tara):
    hasil = periksa_bobot([BarisBobot(D('500'), 20, tara)],
                         tiket_selesai=True, berat_tiket_kg=D('500'))
    assert hasil.status == 'tertahan'
    assert hasil.toleransi_kg is None


def test_toleransi_menjumlah_semua_jenis_kemasan():
    hasil = periksa_bobot([BarisBobot(D('500'), 20, D('.1')),
                          BarisBobot(D('100'), 10, D('.04'))],
                         tiket_selesai=True, berat_tiket_kg=D('602.4'))
    assert hasil.status == 'sesuai'
    assert hasil.toleransi_kg == D('2.4')


def test_tiket_terbuka_tidak_dapat_meloloskan():
    hasil = periksa_bobot([BarisBobot(D('500'), 20, D('.1'))],
                         tiket_selesai=False, berat_tiket_kg=D('500'))
    assert hasil.status == 'menunggu_timbang'


@pytest.mark.parametrize('bobot', ['NaN', 'Infinity', '-1'])
def test_bobot_tidak_sah_ditolak(bobot):
    with pytest.raises(ValueError):
        periksa(D(bobot))


def test_curah_tanpa_karung_tidak_membutuhkan_tara():
    hasil = periksa_bobot([BarisBobot(D('100'), 0, None)],
                         tiket_selesai=True, berat_tiket_kg=D('100'))
    assert hasil.status == 'sesuai'
    assert hasil.toleransi_kg == 0
