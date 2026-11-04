from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlencode
import json,re
from starlette.requests import Request
from jinja2 import Environment,FileSystemLoader,ChoiceLoader,DictLoader
O=Path(__file__).resolve().parents[1];R=O
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}'}),FileSystemLoader(O),FileSystemLoader(R/'hmu_tampilan/templates'),FileSystemLoader(R/'app/web/templates')]),autoescape=True)
env.filters['jam']=lambda v,*_:str(v)
env.globals['JUMLAH_KOMPONEN_QC_PK']=6
views={}
for tab in ['bahan','produk','karung']:
 for owner in ['pabrik','jasa']:
  for gd in ['','g1','g2']:
   def url(t=tab,o=owner,g=gd):return '/stok?'+urlencode(dict(tab=t,pemilik=o,gudang=g))
   nav=NS(jenis=tab,pemilik=owner,pelanggan_id='',pelanggan=[(7,'Pak Pras')],gudang=gd,label='',nama_pemilik='Pabrik' if owner=='pabrik' else 'Titipan jasa',cakupan='Pabrik' if owner=='pabrik' else 'Titipan jasa · Semua pelanggan',lokasi={'':'Semua gudang','g1':'Gudang 1','g2':'Gudang 2'}[gd],url=url(),tab=[NS(nama=n,kunci=k,href=url(t=k),boleh=True) for k,n in [('bahan','Bahan & PK'),('produk','Produk'),('karung','Karung')]],milik=[NS(nama=n,kunci=k,href=url(o=k)) for k,n in [('pabrik','Pabrik'),('jasa','Titipan jasa')]],lokasi_pil=[NS(nama=n,kunci=k,href=url(g=k)) for k,n in [('', 'Semua gudang'),('g1','Gudang 1'),('g2','Gudang 2')]])
   lot=NS(kode='PK/00821',pemilik='Jasa Pak Pras' if owner=='jasa' else 'Pabrik',jasa_id=7 if owner=='jasa' else None,tanggal='04/11/2026',lama='1 hari',mutu=[('Kadar air','13,8%'),('Butir patah','12,4%'),('Susut','0,6%')],kelas='Baik',nilai_kualitas=82.4,kelas_kualitas='B',komponen_kualitas=4,belum_dicatat=False,tersedia=6800)
   tempat=NS(kode='PK/00819',pemilik='Jasa Pak Pras' if owner=='jasa' else '',jasa_id=7 if owner=='jasa' else None,intake_id=19,tanggal='03/11/2026',lama='2 hari',ringkasan_karung='85 karung × 50 kg',mutu=[('Kadar air','13,6%'),('Butir patah','14,1%'),('Susut','0,8%')],kelas='Baik',nilai_kualitas=80.2,kelas_kualitas='B',komponen_kualitas=4,bobot_final=True,tersedia=4250)
   lots=[] if gd=='g2' else [lot];tempats=[] if gd=='g1' else [tempat]
   premium=NS(jenis='premium',nama='Premium',hasil_kg=10000,keluar_kg=3000,dikemas_kg=6000,curah_kg=1000,sisa_kg=7000,curah_saja=False)
   samping=NS(jenis='bekatul',nama='Bekatul',hasil_kg=2500,keluar_kg=250,dikemas_otomatis_kg=2000,curah_otomatis_kg=250,sisa_kg=2250)
   beras=[] if gd=='g1' else [premium];samps=[] if gd=='g1' else [samping]
   karung=[dict(kode='laminasi',nama='Karung laminasi',merk='Hadi Mulya',ukuran=25,lembar=240,gudang='Gudang 2',menipis=False),dict(kode='biasa',nama='Karung biasa',merk='Tanpa merek',ukuran=50,lembar=18,gudang='Gudang 1',menipis=True)]
   karung=[k for k in karung if not gd or k['gudang']=={'g1':'Gudang 1','g2':'Gudang 2'}[gd]]
   common=dict(request=Request(dict(type='http',path='/stok',query_string=urlencode(dict(tab=tab,pemilik=owner,gudang=gd)).encode(),headers=[],scheme='http',server=('uji.local',80))),VERSI='508',STOK_NAV=nav,VIEW='super',V_POLESAN='polesan',V_MEJA=['super'],TAMPILAN_INDUK=True,JASA_SAJA=owner=='jasa',mutu_aktif=True,gudang=gd,detail=False,lot=lots,tempat=tempats,total=sum(x.tersedia for x in lots),kelompok_pk=[],boleh_ubah=False,boleh_minta=False,boleh_pindah_tumpukan=False,BOLEH_CATAT=False,BOLEH_PINDAH=owner=='pabrik',BOLEH_MASUKKAN_SILO=False,kemasan={},titipan={},beras=beras,samping=samps,sisa_beras=7000 if beras else 0,curah_beras=1000 if beras else 0,sisa_samping=2250 if samps else 0,curah_samping=250 if samps else 0,kartu=beras+samps,karung=karung)
   if tab=='bahan':
    name='stok.html'
    if owner=='jasa':common['kelompok_pk']=[dict(pemilik='Pak Pras',lot=lots,tempat=tempats,total=sum(x.tersedia for x in lots),pelanggan_id=7)]
   elif tab=='produk':
    name='stok_produk.html' if owner=='pabrik' else 'stok_produk_jasa.html'
    common['daftar']=[dict(pelanggan_id=7,pemilik='Pak Pras',beras=beras,samping=samps,sisa_beras=common['sisa_beras'],curah_beras=common['curah_beras'],sisa_samping=common['sisa_samping'],curah_samping=common['curah_samping'],kemasan={},broken_curah_kg=0,bekatul_curah_kg=0,jasa_ids=[7],bekatul_kg=0)] if beras else []
   else:
    name='stok_karung.html' if owner=='pabrik' else 'stok_karung_jasa.html';common['daftar']=[dict(pemilik='Pak Pras',karung=karung)] if karung else []
   body=env.get_template(name).render(**common)
   # Kedua rancangan sengaja memakai body yang persis sama.
   views['|'.join([tab,owner,gd])]=dict(body=body,before=env.get_template('_stok_navigasi.html').render(**common),after=env.get_template('_stok_navigasi.html').render(**common))
