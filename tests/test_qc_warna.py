from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace as NS
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Table, SimpleDocTemplate
from app.web.qc_warna import warna, NilaiQC, GabunganQC, paragraf, warnai_tabel, penilaian_berwarna
from app.web.pdf_giling import rincian_gabah

@pytest.mark.parametrize('parameter,values,expected',[
 ('Lamur',[True,'Ya','Ada','Ya · 4 sak',False,'Tidak',None,'Tidak berlaku'],['merah']*4+['hijau']*2+['netral']*2),
 ('Biji hijau',['tidak_ada','hampir_tidak_ada','sedikit','sedang','banyak','lama',None],['hijau','hijau','kuning','oranye','merah','netral','netral']),
 ('Densiti',['empuk','sedang','padat',None,'keras'],['merah','kuning','hijau','netral','netral']),
 *[(p,['bersih','Tidak ada','sedikit','sedang','banyak','parah',None,'lama',0],['hijau','hijau','kuning','oranye','merah','merah','netral','netral','netral']) for p in ['Butir kuning','Kandungan gabah','Gabah','Merang']],
 ('Berat',['padat','sedang','bersih',0],[None]*4),
])
def test_pemetaan_berdasarkan_parameter(parameter,values,expected):
 assert [warna(parameter,v) for v in values]==expected


def test_latar_sel_penuh_tidak_mengubah_ukuran_atau_label():
 style=getSampleStyleSheet()['Normal']
 values=[NilaiQC('Densiti','sedang'),NilaiQC('Biji hijau','sedang'),NilaiQC('Merang','tidak dikenal')]
 table=warnai_tabel(Table([[paragraf(x,style) for x in values]],colWidths=[80]*3,rowHeights=[36]))
 assert len(table._bkgrndcmds)==3
 out=BytesIO();SimpleDocTemplate(out).build([table])
 page=PdfReader(BytesIO(out.getvalue())).pages[0]
 text=page.extract_text()
 assert text.count('sedang')==2 and 'tidak dikenal' in text
 content=page.get_contents().get_data().decode('latin1')
 assert content.count('80 -36 re')==3
 assert '.835294 .921569 .819608' not in content # unknown is neutral


def test_gabungan_tidak_mewarnai_angka_dan_label():
 values=GabunganQC(['Kadar air: 14%\nLamur: ',NilaiQC('Lamur','Ya · 2 sak'),'\nDensiti: ',NilaiQC('Densiti','sedang')],'')
 p=paragraf(values,getSampleStyleSheet()['Normal'])
 out=BytesIO();SimpleDocTemplate(out).build([warnai_tabel(Table([[p]],colWidths=[250]))])
 assert 'Kadar air: 14%' in PdfReader(BytesIO(out.getvalue())).pages[0].extract_text()
 assert not getattr(p.frags[0],'backColor',None)


def test_gabah_kering_tetap_memuat_lamur_tersimpan_dan_nol():
 now=datetime.now(timezone.utc)
 b=NS(id=1,kode_batch='GB-UJI',kondisi_gabah='kering',kadar_air_awal_persen=Decimal('7.0'))
 h=NS(id=2,lamur=True,jumlah_sak_lamur=3)
 rows=[NS(purchase_batch_qc_id=2,nomor_sampel=i,kadar_air_1=a,kadar_air_2=b,lamur=l,jumlah_sak_lamur=s,biji_hijau='sedikit',densiti='padat',created_at=now) for i,a,b,l,s in [(1,0,14,True,3),(2,14,0,False,0),(3,None,None,None,None)]]
 before=deepcopy([vars(q) for q in rows])
 result,summary=rincian_gabah([(b,None)],{1:h},[(q,'Pencatat') for q in rows])
 assert [x['lamur'] for x in result]==['Ya · 3 sak','Tidak · 0 sak','Tidak tercatat']
 assert [x['moisture'] for x in result]==['7,00%','7,00%','Belum dinilai']
 assert summary['GB-UJI']==dict(air=Decimal('7.0'),n=4,sak=3,lamur=True,legacy=False)
 assert [vars(q) for q in rows]==before


def test_macro_hanya_mewarnai_nilai_komponen():
 html='<tr data-komponen="Densiti"><td>Komponen</td><td data-label="Hasil QC">Sedang<span>2 pengukuran</span></td><td>70</td></tr>'
 from bs4 import BeautifulSoup
 s=BeautifulSoup(penilaian_berwarna(html),'html.parser')
 assert '#FFF0AB' in s.select_one('[data-label]')['style']
 assert not s.find_all('td')[-1].has_attr('style')
