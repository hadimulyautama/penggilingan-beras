"""Koreksi lokasi satu penerimaan pada PostgreSQL terisolasi, tanpa stok tandingan."""
import asyncio,copy,uuid
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import (PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,
    Peristiwa,ActivityLog,Silo,SiloStorage,MillingProcess,MillingProcessSource)
from app.services import koreksi_gudang_penerimaan as s
from tests.pg.test_fasilitas import dunia
from tests.pg.test_tiket_antrean_produksi import _tiket,_klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

async def terima(pg,data,jenis='GABAH_KERING'):
    u,wh,ops=data
    async with pg() as db:
        tid=await _tiket(db,'TB-KOREKSI-GUDANG-'+jenis,jenis);await db.commit()
    if jenis.startswith('GABAH'):
        kind='gabah';ep='gabah-masuk';fields={'tujuan':'tumpuk'}
    elif jenis=='BERAS_PK':kind='pk';ep='catat-pk-luar';fields={'jenis_pk':'kl'}
    else:kind='beras' if jenis=='BERAS_MASUK' else 'broken';ep='catat-produk-timbang-masuk';fields={}
    async with await _klien(pg,role='admin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.post('/api/actions/'+ep,json=dict(timbangan_transaksi_id=tid,warehouse_id=wh[0].id,**fields));assert r.status_code==200,r.text
    model=s.MODELS[kind]
    async with pg() as db:
        q=select(model).where(model.timbangan_transaksi_id==tid) if kind in ('gabah','pk') else select(model).where(model.source_type=='timbangan',model.source_id==tid)
        row=await db.scalar(q)
        return dict(tid=tid,kind=kind,id=row.id,user=u,wh=wh,ops=ops)

def kw(d):return {k:d[k] for k in ('tid','kind','id','user')}
async def request(db,d,**changes):
    ctx=await s.konteks(db,**kw(d))
    return dict(warehouse_id=d['wh'][1].id,alasan='Salah memilih gudang saat mencatat penerimaan',dasar=ctx['dasar'],kunci=uuid.uuid4().hex,**changes)
async def preview(db,d,req):
    p=await s.periksa(db,**kw(d),req=req)
    return {**req,'pemeriksaan':p['pemeriksaan'],'konfirmasi':True},p['rencana']

@pytest.mark.parametrize('jenis',['GABAH_BASAH','GABAH_KERING','BERAS_PK','BERAS_MASUK','BROKEN_MASUK'])
async def test_lima_jenis_baca_tinjauan_simpan_retry_dan_konservasi(pg,jenis):
    data=await dunia(pg);d=await terima(pg,data,jenis)
    async with pg() as db:
        model=s.MODELS[d['kind']];row=await db.get(model,d['id']);before=s.raw(row)
        req=await request(db,d);body,plan=await preview(db,d,req)
        assert plan['boleh_simpan'] and plan['sebelum']['versi']==1
        assert (await db.get(model,d['id'])).warehouse_id==d['wh'][0].id
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.JENIS))==0
        result=await s.simpan(db,**kw(d),req=body);await db.commit()
        event=await db.get(Peristiwa,result['peristiwa_id']);assert event.muatan['sebelum']['warehouse_id']==d['wh'][0].id
        after=s.raw(await db.get(model,d['id']))
        assert after['warehouse_id']==d['wh'][1].id
        for key,value in before.items():
            if key not in ('warehouse_id','updated_at'):assert after[key]==value,key
        retry=await s.simpan(db,**kw(d),req=body);await db.commit()
        assert retry['sudah_tercatat'] and retry['peristiwa_id']==result['peristiwa_id']
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.JENIS))==1
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi==s.JENIS))==2
        from app.services.undo import _undo_one,UndoError
        audit=await db.scalar(select(ActivityLog).where(ActivityLog.aksi==s.JENIS).order_by(ActivityLog.id))
        with pytest.raises(UndoError,match='detail Barang Masuk'):await _undo_one(db,audit,actor_id=d['user'].id)
        from app.services.barang_masuk import riwayat
        assert not await riwayat(db,g1=True,g2=True,tid=d['tid'],user=d['ops'][0])
        assert len(await riwayat(db,g1=True,g2=True,tid=d['tid'],user=d['ops'][1]))==1

@pytest.mark.parametrize('status',['terisi','kosong'])
async def test_silo_asal_menghalangi_tanpa_mengubah_sisa(pg,status):
    d=await terima(pg,await dunia(pg))
    async with pg() as db:
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==d['wh'][0].id).order_by(Silo.id))
        st=SiloStorage(silo_id=silo.id,purchase_batch_id=d['id'],status=status,tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=d['user'].id)
        db.add(st);await db.commit();before=s.raw(st);stid=st.id
        req=await request(db,d);body,plan=await preview(db,d,req)
        assert not plan['boleh_simpan'] and any('Isi silo' in x['kode'] for x in plan['penghalang'])
        with pytest.raises(s.Konflik):await s.simpan(db,**kw(d),req=body)
        await db.rollback()
        assert s.raw(await db.get(SiloStorage,stid))==before

@pytest.mark.parametrize('selaras',[False,True])
async def test_sudah_diproses_termasuk_silo_dilepas_periksa_lokasi_bukan_larangan_menyeluruh(pg,selaras):
    d=await terima(pg,await dunia(pg))
    async with pg() as db:
        silo=Silo(nama_silo='Silo gabah uji relasi',warehouse_id=d['wh'][1 if selaras else 0].id,jenis_isi='gabah',aktif=True);db.add(silo);await db.flush()
        st=SiloStorage(silo_id=silo.id,purchase_batch_id=d['id'],status='kosong',tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=d['user'].id);db.add(st);await db.flush()
        pr=MillingProcess(kode_proses='LOT-KOREKSI-LOKASI',status='proses',silo_id=silo.id,purchase_batch_id=d['id'],berat_gabah_masuk_kg=9800,bobot_masuk_final=True,waktu_mulai=now_local(),created_by=d['user'].id);db.add(pr);await db.flush()
        src=MillingProcessSource(milling_process_id=pr.id,silo_storage_id=st.id,purchase_batch_id=d['id'],berat_kg=9800,berat_akhir_kg=1800,berat_terpakai_kg=8000);db.add(src)
        b=await db.get(PurchaseBatch,d['id']);b.status_batch='digiling';await db.commit();st_id=st.id;pr_id=pr.id;src_id=src.id
        before=[s.raw(x) for x in (st,pr,src)]
        req=await request(db,d);body,plan=await preview(db,d,req)
        assert plan['boleh_simpan']==selaras
        if selaras:await s.simpan(db,**kw(d),req=body);await db.commit()
        else:
            assert any(x['kode']==pr.kode_proses for x in plan['penghalang'])
            with pytest.raises(s.Konflik):await s.simpan(db,**kw(d),req=body)
            await db.rollback()
        after=[s.raw(await db.get(m,i)) for m,i in [(SiloStorage,st_id),(MillingProcess,pr_id),(MillingProcessSource,src_id)]]
        assert before==after

async def test_konflik_versi_saldo_dan_gagal_audit_rollback_atomik(pg,monkeypatch):
    d=await terima(pg,await dunia(pg))
    async with pg() as db:
        req=await request(db,d);body,_=await preview(db,d,req)
        row=await db.get(PurchaseBatch,d['id']);row.berat_total_kg=9700;await db.commit()
        with pytest.raises(s.Konflik,match='berubah'):await s.simpan(db,**kw(d),req=body)
        await db.rollback();req=await request(db,d);body,_=await preview(db,d,req)
        async def fail(*a,**k):raise RuntimeError('uji gagal sebelum commit')
        monkeypatch.setattr(s,'log_activity',fail)
        with pytest.raises(RuntimeError):await s.simpan(db,**kw(d),req=body)
        await db.rollback()
        assert (await db.get(PurchaseBatch,d['id'])).warehouse_id==d['wh'][0].id
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.JENIS))==0

async def test_dua_request_bersamaan_tepat_satu_versi_dan_replay(pg):
    d=await terima(pg,await dunia(pg))
    async with pg() as db:req=await request(db,d);body,_=await preview(db,d,req)
    async def write():
        async with pg() as db:
            result=await s.simpan(db,**kw(d),req=body);await db.commit();return result
    a,b=await asyncio.gather(write(),write())
    assert a['peristiwa_id']==b['peristiwa_id'] and sum(not x['sudah_tercatat'] for x in (a,b))==1
    async with pg() as db:
        ctx=await s.konteks(db,**kw(d));assert ctx['versi']==2
        event=await db.get(Peristiwa,a['peristiwa_id']);await s.terapkan_peristiwa(db,event);await s.terapkan_peristiwa(db,event);await db.commit()
        assert (await db.get(PurchaseBatch,d['id'])).berat_total_kg==9800

@pytest.mark.parametrize('role,view,expected',[('operator',None,403),('admin',None,200),('superadmin','operator:g1',403),('superadmin','operator:g2',403)])
async def test_hak_endpoint_langsung_dan_lihat_sebagai(pg,role,view,expected):
    d=await terima(pg,await dunia(pg))
    async with await _klien(pg,role=role,gudang_id=d['wh'][0].id) as c:
        if view:
            r=await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)});assert r.status_code==303,r.text
        url=f'/api/actions/koreksi-gudang-penerimaan/{d["tid"]}/{d["kind"]}/{d["id"]}'
        r=await c.get(url);assert r.status_code==expected,r.text
        req=dict(warehouse_id=d['wh'][1].id,alasan='Koreksi',dasar='usang',kunci=uuid.uuid4().hex)
        r=await c.post(url+'/periksa',json=req,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==(409 if expected==200 else 403),r.text
        r=await c.post(url+'/simpan',json=req,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==(409 if expected==200 else 403),r.text
        r=await c.get('/api/actions/koreksi-gudang-penerimaan/status/'+req['kunci'])
        assert r.status_code==expected,r.text
        page=await c.get(f'/barang-masuk/{d["tid"]}')
        if page.status_code==200:assert ('data-koreksi-gudang' in page.text)==(expected==200)

async def test_koreksi_berurutan_versi_efektif_dan_kunci_tidak_boleh_berganti_isian(pg):
    d=await terima(pg,await dunia(pg))
    async with pg() as db:
        req=await request(db,d);body,_=await preview(db,d,req);await s.simpan(db,**kw(d),req=body);await db.commit()
        ctx=await s.konteks(db,**kw(d));req2=dict(warehouse_id=d['wh'][0].id,alasan='Pemeriksaan ulang lokasi',dasar=ctx['dasar'],kunci=uuid.uuid4().hex)
        body2,_=await preview(db,d,req2);await s.simpan(db,**kw(d),req=body2);await db.commit()
        assert (await s.konteks(db,**kw(d)))['versi']==3
        with pytest.raises(s.Konflik,match='berbeda'):await s.simpan(db,**kw(d),req={**body2,'alasan':'Isian lain dengan kunci sama'})
        await db.rollback()
        assert (await db.get(PurchaseBatch,d['id'])).warehouse_id==d['wh'][0].id

async def test_relasi_baru_dan_gudang_nonaktif_memaksa_tinjauan_ulang(pg):
    d=await terima(pg,await dunia(pg))
    async with pg() as db:
        req=await request(db,d);body,_=await preview(db,d,req)
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==d['wh'][0].id).order_by(Silo.id))
        db.add(SiloStorage(silo_id=silo.id,purchase_batch_id=d['id'],status='terisi',tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=d['user'].id));await db.commit()
        with pytest.raises(s.Konflik,match='berubah'):await s.simpan(db,**kw(d),req=body)
        await db.rollback()
        from app.models import Warehouse
        wh=await db.get(Warehouse,d['wh'][1].id);wh.aktif=False;await db.commit()
        ctx=await s.konteks(db,**kw(d));body['dasar']=ctx['dasar']
        with pytest.raises(PermissionError):await s.periksa(db,**kw(d),req=body)

async def test_bobot_belum_diketahui_tetap_null(pg):
    d=await terima(pg,await dunia(pg),'GABAH_BASAH')
    async with pg() as db:
        row=await db.get(PurchaseBatch,d['id']);row.berat_total_kg=None;row.sumber_berat='menunggu';await db.commit()
        req=await request(db,d);body,plan=await preview(db,d,req);assert plan['bobot'] is None
        await s.simpan(db,**kw(d),req=body);await db.commit()
        assert (await db.get(PurchaseBatch,d['id'])).berat_total_kg is None

@pytest.mark.parametrize('jenis',['BERAS_PK','BERAS_MASUK','BROKEN_MASUK'])
async def test_relasi_pk_beras_broken_ke_silo_dan_proses_lama_sesuai_tujuan(pg,jenis):
    from app.models import PkGudang2Intake,PkTumpukanToSilo,BerasKeSilo,BrokenKeSilo,PolishingProcess,PolishingSiloUsage
    d=await terima(pg,await dunia(pg),jenis)
    async with pg() as db:
        silo=Silo(nama_silo='Silo relasi uji',warehouse_id=d['wh'][1].id,jenis_isi='pk',aktif=True);db.add(silo);await db.flush()
        common=dict(silo_id=silo.id,kode_pindah='PINDAH-UJI-01',berat_kg=1000,tanggal=now_local().date(),waktu=now_local(),input_by=d['user'].id)
        if jenis=='BERAS_PK':
            intake=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==d['id']))
            move=PkTumpukanToSilo(pk_gudang2_intake_id=intake.id,**common)
        elif jenis=='BROKEN_MASUK':move=BrokenKeSilo(byproduct_stock_id=d['id'],**common)
        else:
            row=await db.get(FinishedGoodsStock,d['id']);move=BerasKeSilo(source_type='timbangan',source_id=d['tid'],product_sku_id=row.product_sku_id,jenis='medium',**common)
        db.add(move)
        pr=PolishingProcess(kode_proses='POL-KOREKSI-GUDANG',status='proses',waktu_mulai=now_local(),created_by=d['user'].id);db.add(pr);await db.flush()
        usage=PolishingSiloUsage(polishing_process_id=pr.id,silo_id=silo.id,berat_awal_kg=1000,berat_masuk_kg=0,berat_akhir_kg=100,berat_terpakai_kg=900);db.add(usage);await db.commit()
        before=[s.raw(x) for x in (move,pr,usage)]
        req=await request(db,d);body,plan=await preview(db,d,req);assert plan['boleh_simpan'],plan
        assert any(x['kode']=='POL-KOREKSI-GUDANG' for x in plan['relasi'])
        await s.simpan(db,**kw(d),req=body);await db.commit()
        assert [s.raw(x) for x in (move,pr,usage)]==before

async def test_http_konfirmasi_csrf_status_retry_dan_angka_pdf(pg):
    from io import BytesIO
    from pypdf import PdfReader
    d=await terima(pg,await dunia(pg))
    async with await _klien(pg,role='admin') as c:
        url=f'/api/actions/koreksi-gudang-penerimaan/{d["tid"]}/{d["kind"]}/{d["id"]}'
        ctx=(await c.get(url)).json();req=dict(warehouse_id=d['wh'][1].id,alasan='Salah pilih gudang',dasar=ctx['dasar'],kunci=uuid.uuid4().hex)
        assert (await c.post(url+'/periksa',json=req)).status_code==403
        headers={'X-CSRF-Token':cap_formulir(c)}
        pre=await c.post(url+'/periksa',json=req,headers=headers);assert pre.status_code==200,pre.text
        body={**req,'pemeriksaan':pre.json()['pemeriksaan']}
        assert (await c.post(url+'/simpan',json=body,headers=headers)).status_code==409
        before=await c.get(f'/barang-masuk/{d["tid"]}/laporan.pdf');assert before.status_code==200
        response=await c.post(url+'/simpan',json={**body,'konfirmasi':True},headers=headers);assert response.status_code==200,response.text
        retry=await c.post(url+'/simpan',json={**body,'konfirmasi':True},headers=headers);assert retry.status_code==200 and retry.json()['sudah_tercatat']
        status=await c.get('/api/actions/koreksi-gudang-penerimaan/status/'+req['kunci']);assert status.json()['peristiwa_id']==response.json()['peristiwa_id']
        after=await c.get(f'/barang-masuk/{d["tid"]}/laporan.pdf');assert after.status_code==200
        for pdf in (before,after):
            text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
            assert '9.800' in text and 'Laporan Penerimaan Barang' in text
        page=await c.get(f'/barang-masuk/{d["tid"]}');assert 'Gudang 2' in page.text
        from pathlib import Path
        Path('../koreksi-gudang-detail-uji.html').write_text(page.text)
        import json
        latest=(await c.get(url)).json()
        reverse={**req,'warehouse_id':d['wh'][0].id,'dasar':latest['dasar']}
        review=await c.post(url+'/periksa',json=reverse,headers=headers)
        assert review.status_code==200
        Path('../koreksi-gudang-konteks-uji.json').write_text(json.dumps(latest))
        Path('../koreksi-gudang-dampak-uji.json').write_text(json.dumps(review.json()))
        assert (await c.get(url.replace('/'+str(d['tid'])+'/', '/99999/'))).status_code==403

async def test_retur_dan_alokasi_pool_ditahan(pg):
    from app.models import ReturSupplier,ReturSupplierItem,OutgoingRecord,OutgoingItem
    d=await terima(pg,await dunia(pg),'BROKEN_MASUK')
    async with pg() as db:
        row=await db.get(ByproductStock,d['id'])
        out=OutgoingRecord(kode='OUT-UJI-LOKASI',status='perintah',warehouse_id=d['wh'][0].id,tanggal=now_local().date(),waktu=now_local(),input_by=d['user'].id)
        db.add(out);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=out.id,item_type='byproduct_curah',jenis_byproduct='broken',jasa_id=row.jasa_id,berat_perintah_kg=100,berat_kg=0))
        await db.commit()
        req=await request(db,d);_,plan=await preview(db,d,req)
        assert not plan['boleh_simpan'] and any(p['kode']==out.kode for p in plan['penghalang'])
        out.status='batal';await db.commit()
        supplier=await db.scalar(select(s.MODELS['gabah'].supplier_id).limit(1))
        if supplier is None:
            from app.models import Supplier
            sup=Supplier(nama_supplier='Supplier uji retur');db.add(sup);await db.flush();supplier=sup.id
        ret=ReturSupplier(kode='RT-UJI-LOKASI',penerimaan_tiket_id=d['tid'],supplier_id=supplier,alasan='Uji hubungan',sumber={},kunci=uuid.uuid4().hex,sidik='uji',input_by=d['user'].id,waktu=now_local())
        db.add(ret);await db.flush()
        db.add(ReturSupplierItem(retur_supplier_id=ret.id,kunci_sumber='broken:'+str(row.id),byproduct_stock_id=row.id,warehouse_id=d['wh'][0].id,jumlah=100,satuan='kg',bobot_kg=100,tipe_pool='byproduct_curah',jenis_produk='broken',snapshot={}))
        await db.commit()
        req=await request(db,d);_,plan=await preview(db,d,req)
        assert not plan['boleh_simpan'] and any(p['kode']==ret.kode for p in plan['penghalang'])
        assert not any(p['kode']==out.kode for p in plan['penghalang'])

async def test_beberapa_penerimaan_satu_tiket_hanya_baris_dipilih_berubah(pg):
    d=await terima(pg,await dunia(pg),'BERAS_MASUK')
    async with pg() as db:
        original=await db.get(FinishedGoodsStock,d['id'])
        values={c.key:getattr(original,c.key) for c in original.__mapper__.column_attrs if c.key not in ('id','created_at','updated_at','kode_batch')}
        other=FinishedGoodsStock(**values);db.add(other);await db.commit()
        before=s.raw(other);oid=other.id
        req=await request(db,d);body,plan=await preview(db,d,req)
        assert plan['boleh_simpan']
        await s.simpan(db,**kw(d),req=body);await db.commit()
        assert s.raw(await db.get(FinishedGoodsStock,oid))==before

@pytest.mark.parametrize('jenis',['BERAS_MASUK','BROKEN_MASUK'])
async def test_perpindahan_kepemilikan_menahan_relabel_satu_pecahan(pg,jenis):
    d=await terima(pg,await dunia(pg),jenis)
    async with pg() as db:
        event=Peristiwa(jenis='pindah_kepemilikan_rinci',pelaku_id=d['user'].id,kunci_kiriman='uji-alih-milik',muatan={'kind':'barang' if jenis=='BERAS_MASUK' else 'curah','lines':[{'source_id':d['id'],'target_id':d['id']}]})
        db.add(event);await db.commit()
        req=await request(db,d);_,plan=await preview(db,d,req)
        assert not plan['boleh_simpan'] and any('kepemilikan' in p['kode'] for p in plan['penghalang'])
