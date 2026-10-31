"""Penjumlahan hanya dari saldo lokasi, bukan bobot batch asal."""
from decimal import Decimal
from app.web.portal.barang import ringkas


def baris(jenis,kg,identitas,final=True):
    return dict(komoditas=jenis,nama=jenis,kg=kg,final=final,identitas=identitas,
                asal=[dict(kode='ASAL',kg=99999)])


def test_total_komoditas_tepat_dan_lokasi_tidak_dihitung_dua_kali():
    pertama=baris('gabah',1000.125,('silo',1))
    g=ringkas([pertama,dict(pertama),baris('gabah',2000.25,('silo',2)),baris('pk',500,('lot',1))])
    assert [r['kunci'] for r in g]==['gabah','pk']
    assert g[0]['kg']==Decimal('3000.375') and len(g[0]['rincian'])==2
    assert g[1]['kg']==500


def test_bobot_belum_diukur_dan_defisit_tetap_dijelaskan():
    g=ringkas([baris('gabah',None,1,False),baris('gabah',100,2),baris('beras',-5,3)])
    assert g[0]['kg']==100 and g[0]['belum_diukur']==1 and g[0]['sementara']
    assert g[1]['kg']==-5 and g[1]['perlu_periksa']
    assert ringkas([baris('gabah',None,1,False)])[0]['kg'] is None


def test_jenis_bahan_yang_belum_diketahui_tidak_ditebak_sebagai_pk():
    g=ringkas([baris('belum_dikenal',500,1)])
    assert g[0]['kunci']=='belum_dikenal' and g[0]['nama']=='Bahan belum teridentifikasi'
