"""Bahasa laporan menerjemahkan snapshot; tidak membuat keputusan kontrol."""
from copy import deepcopy
from decimal import Decimal
import pytest
from app.web.pdf_penerimaan import kalimat_selisih,potongan_kemasan,kesimpulan


@pytest.mark.parametrize('delta,persen,status,expected',[
    (-14,-.14,'NORMAL','Lebih ringan 14,00 kg (0,14%) dari nota; masih dalam batas kontrol.'),
    (14,.14,'NORMAL','Lebih berat 14,00 kg (0,14%) dari nota; masih dalam batas kontrol.'),
    (0,0,'NORMAL','Sama dengan nota (0,00%); masih dalam batas kontrol.'),
    (-140,-1.4,'PERLU_PEMERIKSAAN','Lebih ringan 140,00 kg (1,40%) dari nota; perlu pemeriksaan.'),
    (240,2.4,'INVESTIGASI','Lebih berat 240,00 kg (2,40%) dari nota; memerlukan investigasi.'),
    (140,1.4,'KONTROL_LAMA','Lebih berat 140,00 kg (1,40%) dari nota; status kontrol tersimpan: KONTROL LAMA.'),
])
def test_kalimat_mengikuti_angka_dan_status_tersimpan(delta,persen,status,expected):
    t=dict(berat_acuan_kg=10000,selisih_kg=delta,selisih_persen=persen,status_kontrol=status)
    sebelum=deepcopy(t)
    assert kalimat_selisih(t,True)==expected
    assert t==sebelum


def test_kontrol_belum_ada_tidak_disebut_cocok_dan_tanda_lama_tidak_diperbaiki():
    t=dict(berat_acuan_kg=0,selisih_kg=0,selisih_persen=0,status_kontrol='TANPA_KONTROL')
    assert 'tanpa kontrol pembanding' in kalimat_selisih(t)
    assert 'Sama dengan' not in kalimat_selisih(t)
    t.update(berat_acuan_kg=10000,selisih_kg=14,selisih_persen=-.14,status_kontrol=None)
    assert 'persentase tersimpan -0,14%' in kalimat_selisih(t)
    assert 'hasil kontrol belum tersedia' in kalimat_selisih(t)
    t.update(selisih_kg=None,selisih_persen=None)
    assert 'Selisih terhadap nota/acuan belum tercatat' in kalimat_selisih(t)


@pytest.mark.parametrize('total,lain,expected',[(16,1,Decimal(15)),(0,0,Decimal(0)),
    (16,None,None),(None,0,None),(1,16,None)])
def test_potongan_hanya_memisahkan_total_yang_tersimpan(total,lain,expected):
    t=dict(total_tara_kg=total,tara_lain_kg=lain,muatan=[dict(jumlah_karung=200,tara_per_karung_kg=88)])
    awal=deepcopy(t)
    assert potongan_kemasan(t)==expected
    assert t==awal


def test_kesimpulan_historis_tidak_mengaku_punya_putaran_asli():
    d=dict(berat=100,jenis='gabah_kering',qc=[dict(kode='GB-LAMA',jenis='gabah_kering',
        putaran=[dict(nomor=None)],rata=dict(air=Decimal('14.25')))])
    s=kesimpulan(d)
    assert 'jumlah putaran asli tidak lengkap' in s
    assert 'kadar air tersimpan 14,25%' in s
    assert 'rata-rata kadar air' not in s
