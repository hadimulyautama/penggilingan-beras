"""Reproduksi hasil 5350 -> 0 dengan perpindahan otomatis 50 yang salah."""
import pytest
from sqlalchemy import select,func
from decimal import Decimal as D
from app.database import now_local
from app.models import User,Silo,BrokenKeSilo,ByproductStock,PolishingProcess,ActivityLog,PolishingOutputLog
from app.services import koreksi_bahan_berjalan as s
from app.penggilingan.gudang2 import service as g2,polishing as p
from tests.pg.test_koreksi_bahan_berjalan import running,save,request,dunia
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def kasus(pg,running):
    uid,kode,_,_=running
    async with pg() as db:
        u=await db.get(User,uid)
        silo=Silo(nama_silo='Tong Broken Uji',warehouse_id=u.default_warehouse_id,jenis_isi='broken',aktif=True,status='kosong');db.add(silo);await db.commit()
        await p.catat_output(db,user=u,kode=kode,jenis='broken',berat_kumulatif=5350)
        await g2.masukkan_broken_ke_silo(db,user=u,kode_pol=kode,nama_silo=silo.nama_silo,berat_kg=50)
        move=await db.scalar(select(BrokenKeSilo).where(BrokenKeSilo.silo_id==silo.id))
        return uid,kode,move.id,move.byproduct_stock_id,silo.id

async def joint(pg,kasus,**extra):
    uid,kode,mid,_,_=kasus
    return await save(pg,uid,kode,hasil={'broken':0},broken_terkait=[mid],**extra)

async def test_preview_tanpa_mutasi_dan_simpan_atomik_5350_nol(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        user,body=await request(db,uid,kode,hasil={'broken':0});body['broken_terkait']=[mid]
        r=await s.periksa(db,jenis='sosoh',kode=kode,user=user,req=body)
        assert r['sesudah']['outputs']['broken']==0
        assert r['koreksi_broken_terkait'][0]['sebelum']['saldo_silo']==50
        assert r['koreksi_broken_terkait'][0]['sesudah']['saldo_silo']==0
    async with pg() as db:
        assert (await db.get(ByproductStock,bid)).berat_kg==50
        assert await db.scalar(select(BrokenKeSilo.id).where(BrokenKeSilo.id==mid))==mid
    r,body=await joint(pg,kasus)
    assert r['hasil']['sesudah']['outputs']['broken']==0
    assert r['hasil']['sebelum']['outputs']['broken']==5350
    async with pg() as db:
        src=await db.get(ByproductStock,bid);assert src.berat_kg==0
        assert await db.scalar(select(BrokenKeSilo.id).where(BrokenKeSilo.id==mid)) is None
        move=await db.scalar(select(BrokenKeSilo).where(BrokenKeSilo.id==mid).execution_options(termasuk_dibatalkan=True))
        assert move.berat_kg==50 and move.dibatalkan_pada
        assert await g2.hitung_stok_silo(db,sid)==0
        assert (await db.get(Silo,sid)).status=='kosong'
        assert (await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))).status=='proses'
        logs=(await db.scalars(select(ActivityLog).where(ActivityLog.aksi==s.JENIS))).all()
        assert any(x.table_name=='byproduct_stock' and x.old_value and x.new_value and x.alasan_perubahan for x in logs)
        u=await db.get(User,uid);again=await s.simpan(db,jenis='sosoh',kode=kode,user=u,req=body)
        assert again['sudah_tercatat'] and again['peristiwa_id']==r['peristiwa_id']

async def test_hasil_nol_tanpa_pilihan_terkait_tetap_ditolak(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    with pytest.raises(ValueError,match='ditahan'):await save(pg,uid,kode,hasil={'broken':0})
    async with pg() as db:assert (await db.get(ByproductStock,bid)).berat_kg==50

async def test_bahan_sudah_dipakai_proses_lain_ditolak(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        u=await db.get(User,uid);silo=await db.get(Silo,sid)
        await p.mulai_penyosohan(db,user=u,nama_silos=[silo.nama_silo])
    with pytest.raises(ValueError,match='siklus'):await joint(pg,kasus)
    async with pg() as db:assert (await db.get(ByproductStock,bid)).berat_kg==50

@pytest.mark.parametrize('ids',[[99999],[1,1]])
async def test_id_asing_atau_ganda_ditolak(pg,kasus,ids):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        u,b=await request(db,uid,kode,hasil={'broken':0});b['broken_terkait']=ids
        with pytest.raises(ValueError):await s.periksa(db,jenis='sosoh',kode=kode,user=u,req=b)

async def test_sumber_non_otomatis_tidak_dipotong_diam_diam(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        a=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='broken_catat_otomatis',ActivityLog.record_id==bid));a.aksi='catat_manual';await db.commit()
    with pytest.raises(ValueError,match='bukan otomatis'):await joint(pg,kasus)

async def test_gagal_hasil_lain_membatalkan_pembatalan_broken(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    with pytest.raises(ValueError):await save(pg,uid,kode,hasil={'broken':0,'jenis_palsu':1},broken_terkait=[mid])
    async with pg() as db:
        assert (await db.get(ByproductStock,bid)).berat_kg==50
        assert await db.scalar(select(BrokenKeSilo.id).where(BrokenKeSilo.id==mid))==mid

async def test_perubahan_perpindahan_menolak_snapshot_usang(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        u,b=await request(db,uid,kode,hasil={'broken':0});b['broken_terkait']=[mid]
        pre=await s.periksa(db,jenis='sosoh',kode=kode,user=u,req=b);b.update(pemeriksaan=pre['pemeriksaan'],konfirmasi=True)
    async with pg() as db:
        m=await db.get(BrokenKeSilo,mid);m.berat_kg=40;await db.commit()
    async with pg() as db:
        with pytest.raises(s.Konflik):await s.simpan(db,jenis='sosoh',kode=kode,user=await db.get(User,uid),req=b)
    async with pg() as db:assert (await db.get(ByproductStock,bid)).berat_kg==50

async def test_alokasi_supplier_menahan_semua_perubahan(pg,kasus,monkeypatch):
    import app.services.retur_supplier_reservasi as reserve
    async def bound(db,**kw):return D(10)
    monkeypatch.setattr(reserve,'terikat',bound)
    with pytest.raises(ValueError,match='alokasi'):await joint(pg,kasus)
    async with pg() as db:assert (await db.get(ByproductStock,kasus[3])).berat_kg==50

async def test_koreksi_saat_jeda_tidak_melanjutkan_mesin(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    from app.penggilingan.gudang1.services import jeda
    async with pg() as db:
        u=await db.get(User,uid);u.role='operator';await db.commit()
        await jeda.hentikan(db,user=u,jenis='penyosohan',kode=kode,sebab='Listrik padam')
    await joint(pg,kasus)
    async with pg() as db:
        proc=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
        assert proc.status=='proses' and await jeda.jeda_terbuka(db,'penyosohan',proc.id)

async def test_http_operator_simpan_gabungan_dan_idempotensi(pg,kasus):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    uid,kode,mid,bid,sid=kasus
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        path=f'/api/actions/koreksi-bahan/sosoh/{kode}'
        data=(await c.get(path)).json()
        assert any(x['id']==mid and x['boleh_batal'] for x in data['broken_terkait'])
        body=dict(dasar=data['dasar'],bahan=[],hasil={'broken':0},broken_terkait=[mid],alasan='Hasil dan perpindahan 50 kg salah input, fisik tidak pernah dipindah',kunci='uji-http-broken-gabungan')
        head={'X-CSRF-Token':cap_formulir(c)}
        pre=await c.post(path+'/periksa',json=body,headers=head);assert pre.status_code==200,pre.text
        body.update(pemeriksaan=pre.json()['pemeriksaan'],konfirmasi=True)
        ok=await c.post(path+'/simpan',json=body,headers=head);assert ok.status_code==200,ok.text
        retry=await c.post(path+'/simpan',json=body,headers=head);assert retry.status_code==200 and retry.json()['sudah_tercatat']
        assert ok.json()['peristiwa_id']==retry.json()['peristiwa_id']

async def test_perpindahan_lain_tidak_dibatalkan_diam_diam(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        u=await db.get(User,uid);silo=await db.get(Silo,sid)
        await g2.masukkan_broken_ke_silo(db,user=u,kode_pol=kode,nama_silo=silo.nama_silo,berat_kg=25)
        other=await db.scalar(select(BrokenKeSilo).where(BrokenKeSilo.id!=mid));oid=other.id
    with pytest.raises(ValueError,match='ditahan'):await joint(pg,kasus)
    async with pg() as db:
        assert (await db.get(ByproductStock,bid)).berat_kg==50
        assert await db.scalar(select(BrokenKeSilo.id).where(BrokenKeSilo.id==oid))==oid
    await save(pg,uid,kode,hasil={'broken':0},broken_terkait=[mid,oid])
    async with pg() as db:assert await g2.hitung_stok_silo(db,sid)==0

async def test_formulir_operator_menyajikan_perpindahan_terkait(pg,kasus):
    from tests.pg.test_riwayat_giling import _klien
    from app.models import ProduksiAkun
    uid,kode,mid,bid,sid=kasus
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        r=await c.get('/koreksi-bahan/sosoh/'+kode)
        assert r.status_code==200 and 'broken_terkait' in r.text
        data=(await c.get('/api/actions/koreksi-bahan/sosoh/'+kode)).json()
        assert data['outputs']['broken']==5350 and data['broken_terkait'][0]['kg']==50
    import os,json
    if os.environ.get('UJI_BROKEN_VISUAL')=='1':
        from pathlib import Path
        async with pg() as db:
            acct=await db.scalar(select(ProduksiAkun).order_by(ProduksiAkun.id.desc()).limit(1))
            Path('../visual-broken.json').write_text(json.dumps(dict(username=acct.username,password='rahasia123',kode=kode)))

async def test_sisa_broken_5300_sumber_lain_tidak_ikut_dihapus(pg,kasus):
    from datetime import timedelta
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        when=now_local()-timedelta(days=2)
        src=ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=919,berat_kg=5300,tanggal=when.date(),waktu=when,input_by=uid)
        db.add(src);await db.flush()
        old=BrokenKeSilo(kode_pindah='BKS-SUMBER-LAIN',byproduct_stock_id=src.id,silo_id=sid,berat_kg=5300,tanggal=when.date(),waktu=when,input_by=uid)
        db.add(old);await db.commit();other=src.id;oid=old.id
        assert await g2.hitung_stok_silo(db,sid)==5350
    result,_=await joint(pg,kasus)
    change=result['hasil']['koreksi_broken_terkait'][0]
    assert change['sebelum']['saldo_silo']==5350 and change['sesudah']['saldo_silo']==5300
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,sid)==5300
        assert (await db.get(Silo,sid)).status=='terisi'
        assert (await db.get(ByproductStock,other)).berat_kg==5300
        assert await db.scalar(select(BrokenKeSilo.id).where(BrokenKeSilo.id==oid))==oid

async def test_seluruh_5350_dicatat_salah_ke_tong_dapat_dikoreksi_bersama(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        u=await db.get(User,uid);silo=await db.get(Silo,sid)
        await g2.masukkan_broken_ke_silo(db,user=u,kode_pol=kode,nama_silo=silo.nama_silo,berat_kg=5300)
        ids=list((await db.scalars(select(BrokenKeSilo.id).order_by(BrokenKeSilo.id))).all())
        assert await g2.hitung_stok_silo(db,sid)==5350
    r,_=await save(pg,uid,kode,hasil={'broken':0},broken_terkait=ids)
    assert r['hasil']['sesudah']['outputs']['broken']==0
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,sid)==0
        assert await db.scalar(select(func.sum(ByproductStock.berat_kg)))==0

async def test_dua_permintaan_serentak_tidak_mengulang_pembatalan(pg,kasus):
    import asyncio
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        u,b=await request(db,uid,kode,hasil={'broken':0},broken_terkait=[mid])
        pre=await s.periksa(db,jenis='sosoh',kode=kode,user=u,req=b)
        b.update(pemeriksaan=pre['pemeriksaan'],konfirmasi=True)
    async def apply():
        async with pg() as db:
            r=await s.simpan(db,jenis='sosoh',kode=kode,user=await db.get(User,uid),req=b);await db.commit();return r
    a,c=await asyncio.gather(apply(),apply())
    assert a['peristiwa_id']==c['peristiwa_id']
    assert a['sudah_tercatat']!=c['sudah_tercatat']
    async with pg() as db:assert (await db.get(ByproductStock,bid)).berat_kg==0


async def test_dua_perpindahan_satu_pembukuan_dibatalkan_sekali(pg,kasus):
    uid,kode,mid,bid,sid=kasus
    async with pg() as db:
        m=await db.get(BrokenKeSilo,mid);m.berat_kg=20
        second=BrokenKeSilo(kode_pindah='BKS-SATU-SUMBER',byproduct_stock_id=bid,silo_id=sid,berat_kg=30,tanggal=m.tanggal,waktu=m.waktu,input_by=uid)
        db.add(second);await db.commit();other=second.id
    await save(pg,uid,kode,hasil={'broken':0},broken_terkait=[mid,other])
    async with pg() as db:
        assert (await db.get(ByproductStock,bid)).berat_kg==0
        assert await g2.hitung_stok_silo(db,sid)==0

async def test_draf_bahan_2850_sisa_5300_ditolak_tanpa_menghalangi_koreksi_hasil_saja(pg,running):
    uid,kode,_,_=running
    async with pg() as db:
        u=await db.get(User,uid)
        silo=Silo(nama_silo='Tong Broken Uji',warehouse_id=u.default_warehouse_id,jenis_isi='broken',aktif=True,status='kosong');db.add(silo);await db.commit()
        ext=ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=919,berat_kg=8150,tanggal=now_local().date(),waktu=now_local(),input_by=uid)
        db.add(ext);await db.commit()
        await g2.pindah_broken_ke_silo(db,user=u,byproduct_stock_id=ext.id,nama_silo=silo.nama_silo,berat=8150)
        original=await db.scalar(select(BrokenKeSilo));original_id=original.id
        await p.tambah_silo_penyosohan(db,user=u,kode=kode,nama_silos=[silo.nama_silo])
        await p.selesai_penyosohan(db,user=u,kode=kode,nama_silo=silo.nama_silo,sisa_kg=5300)
        await p.catat_output(db,user=u,kode=kode,jenis='broken',berat_kumulatif=5350)
        await g2.masukkan_broken_ke_silo(db,user=u,kode_pol=kode,nama_silo=silo.nama_silo,berat_kg=50)
        false_move=await db.scalar(select(BrokenKeSilo).where(BrokenKeSilo.id!=original_id))
        mid=false_move.id
        ctx=await s.konteks(db,jenis='sosoh',kode=kode,user=u)
        entry=next(x for x in ctx['entries'] if x['id']==f'broken:{original_id}')
    with pytest.raises(ValueError,match='tidak mencakup sisa'):
        await save(pg,uid,kode,bahan=[dict(id=entry['id'],sumber=entry['sumber'],jumlah=2850,sisa=5300)],hasil={'broken':0},broken_terkait=[mid])
    r,_=await save(pg,uid,kode,hasil={'broken':0},broken_terkait=[mid])
    after=r['hasil']['sesudah'];keep=next(x for x in after['entries'] if x['id']==entry['id'])
    assert keep['kg']==8150 and keep['sisa']==5300
    assert after['outputs']['broken']==0
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,silo.id)==5300
        usage=await s.siklus_g2(db,await db.get(BrokenKeSilo,original_id));assert usage.berat_terpakai_kg==2850
