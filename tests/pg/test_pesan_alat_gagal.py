"""Kegagalan konfigurasi tidak menyimpan perubahan atau mengirim pesan sukses."""
import json,re
from html.parser import HTMLParser
import pytest
from sqlalchemy import select
from app.models import Warehouse,Dryer,Silo,LiniProduksi
from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import master,klien,kirim
from tests.pg.test_pengaturan_simpan_terpisah import snapshot
from tests.pg.test_pengaturan_terpadu import fisik
from tests.pg.test_qc_berjalan import giling

pytestmark=pytest.mark.asyncio
class Fields(HTMLParser):
    def __init__(self):super().__init__();self.fields={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='input' and a.get('name'):self.fields.setdefault(a['name'],[]).append(a)

@pytest.mark.parametrize('case',['dryer-angka','dryer-nol','dryer-kembar','dryer-edit-target','dryer-edit-angka','silo-kembar','silo-edit-filter','silo-edit-kosong'])
async def test_gagal_pesan_dan_isian(pg,master,giling,case):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with pg() as db:
        d=await db.scalar(select(Dryer).order_by(Dryer.id));sid=await db.scalar(select(Silo.id).where(Silo.jenis_isi=='gabah').order_by(Silo.id))
        s=await db.get(Silo,sid);lid=await db.scalar(select(LiniProduksi.id).where(LiniProduksi.dryer_id==d.id));wid=d.warehouse_id
        add_d=dict(nama='Dryer isian gagal',kapasitas_kg='12345',warehouse_id=wid,kembali_pengaturan='/pengaturan/mesin')
        edit_d=dict(dryer_id=d.id,nama='Dryer gagal edit',kapasitas_kg='23456',target_kadar_air='14,2',tungku='Tungku isian tetap',kembali_pengaturan=f'/pengaturan/mesin/{lid}')
        add_s=dict(nama=s.nama_silo,warehouse_id=s.warehouse_id,jenis_isi='gabah',kembali_pengaturan='/pengaturan/silo')
        edit_s=dict(silo_id=s.id,nama='Silo gagal edit',komoditas=['gabah_kering'],kembali_pengaturan='/pengaturan/silo')
        cases={
          'dryer-angka':('dryer',dict(add_d,kapasitas_kg='bukan-angka'),'Kapasitas harus angka.'),
          'dryer-nol':('dryer',dict(add_d,kapasitas_kg='0'),'Kapasitas harus lebih dari 0'),
          'dryer-kembar':('dryer',dict(add_d,nama=d.nama),'Sudah ada alat'),
          'dryer-edit-target':('dryer/edit',dict(edit_d,target_kadar_air='31'),'5% dan 30%'),
          'dryer-edit-angka':('dryer/edit',dict(edit_d,kapasitas_kg='bukan-angka'),'harus berupa angka'),
          'silo-kembar':('silo',add_s,'Sudah ada alat'),
          'silo-edit-filter':('silo/edit',dict(edit_s,komoditas=['bekatul']),'Pilih komoditas'),
          'silo-edit-kosong':('silo/edit',{k:v for k,v in edit_s.items() if k!='komoditas'},'Pilih komoditas'),
        }
    path,data,msg=cases[case]
    before=await snapshot(pg);stock=await fisik(pg)
    async with c:
        r=await kirim(c,'/pengaturan/alat/'+path,data)
        assert r.status_code==200 and msg in r.text
        assert 'role="alert"' in r.text
        assert 'role="status"' not in r.text
        for success in ['Dryer baru ditambahkan.','Silo baru ditambahkan.','Alat diperbarui.','Nama dan filter komoditas silo berhasil disimpan.']:
            assert success not in r.text
        if path.startswith('dryer'):
            fields=Fields();fields.feed(r.text)
            for k in ('nama','kapasitas_kg','target_kadar_air','tungku'):
                if k in data:assert any(x.get('value')==data[k] for x in fields.fields[k]),k
            if path=='dryer':assert f'value="{wid}" selected' in r.text
        else:
            recovered=json.loads(re.search(r'id="pengaturan-isian">(.*?)</script>',r.text,re.S)[1])
            for k in ('nama','warehouse_id','silo_id','komoditas'):
                expected=data.get(k,[] if k=='komoditas' and path=='silo/edit' else None)
                if expected is not None:
                    assert recovered['isian'][k]==(expected if isinstance(expected,list) else [str(expected)])
    assert await snapshot(pg)==before
    assert await fisik(pg)==stock
