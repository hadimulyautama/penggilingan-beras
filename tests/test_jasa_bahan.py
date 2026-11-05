from decimal import Decimal
from app.services.jasa_bahan import ringkas


def row(stage,kg,source,**extra):
 return dict(tahap_bahan=stage,jenis_bahan='Gabah',label_bahan=stage,kg=kg,
             final=True,lokasi='Gudang baru',sumber_bahan=source,**extra)


def test_suroto_produk_nol_tetapi_gabah_tiap_tahap_terlihat():
 values={r['tahap']:r for r in ringkas([row('pengering',10839,'b:1'),row('pengering',10498,'b:2'),row('silo_giling',32843.5,'s:1')])}
 assert values['pengering']['kg']==Decimal('21337')
 assert values['silo_giling']['kg']==Decimal('32843.5')
 assert values['tumpukan']['kg']==0
 assert all('total' not in r for r in values.values())


def test_bobot_belum_diketahui_tidak_disamarkan_menjadi_nol():
 values={r['tahap']:r for r in ringkas([row('pengering',None,'b:1'),row('pengering',1100.25,'b:2')])}
 assert values['pengering']['kg']==Decimal('1100.25')
 assert values['pengering']['belum_diketahui']==1


def test_semua_tahap_terpisah_dan_sumber_tidak_terhitung_dua_kali():
 a=row('silo_giling',1000,'s:1',terikat_proses=True)
 values={r['tahap']:r for r in ringkas([row('penempatan',2000,'b:1'),row('tumpukan',1500,'b:2'),a,a])}
 assert values['silo_giling']['kg']==1000 and values['silo_giling']['jumlah']==1
 assert values['silo_giling']['belum_final']
 assert values['penempatan']['kg']==2000 and values['tumpukan']['kg']==1500


def test_bahan_proses_tidak_ditebak_sebagai_pk():
 material=row('silo_sosoh',700,'g2:1');material.update(jenis_bahan='Broken',label_bahan='Broken di silo / proses sosoh')
 result=ringkas([material]);assert result[-1]['jenis']=='Broken' and result[-1]['kg']==700
 assert not any(r['jenis']=='PK' for r in result)
