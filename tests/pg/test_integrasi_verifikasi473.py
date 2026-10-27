"""Dua aplikasi HTTP, migrasi nyata, snapshot tara campuran dan callback ulang."""
import os,re
from uuid import uuid4
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import httpx
import pytest
from sqlalchemy import select,text,func
from app.models import User,OutgoingRecord,ActivityLog
from app.services import barang_keluar as bk
from app.web import verifikasi_pengiriman as layar
from tests.pg.test_barang_keluar import gudang,_stok,_klien
from tests.pg.formulir import cap_formulir
from tests.pg.test_teraflow_kiriman import (_skema_head,servers,akun,profil,benih,
    test_http_satu_tiket_muatan_aktual_dan_verifikasi_bersama as alur_lama)

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('pelanggan,luring',[(1,False),(2,False),(2,True)])
async def test_alur_dua_app_dan_hasil_verifikasi_otomatis_baca_saja(pg,gudang,pelanggan,luring):
    await alur_lama(pg,gudang,pelanggan,luring)
    async with pg() as db:
        rec=await db.scalar(select(OutgoingRecord).order_by(OutgoingRecord.id))
        jumlah=await db.scalar(select(func.count()).select_from(ActivityLog))
        d=await layar.baca(db,rec.id)
        assert d['terverifikasi'] and not d['boleh_manual']
        assert d['jumlah_pelanggan']==pelanggan and d['jumlah_item']==3*pelanggan
        assert d['total_aktual_kg']==d['berat_tiket_kg'] and d['selisih_kg']==0
        assert all(j['metode']=='otomatis' for j in d['jejak'])
        assert all(j['pelaksana'] and j['waktu'] for j in d['jejak'])
        assert d['catatan_integrasi'] is None
        assert len(d['kemasan'])==3*pelanggan
        assert await db.scalar(select(func.count()).select_from(ActivityLog))==jumlah

@pytest.mark.parametrize('delta,gangguan',[(5,False),(150,False),(0,True)])
async def test_timbang_tersimpan_otomatis_ditahan_manual_sesuai_ambang(pg,gudang,delta,gangguan):
    rs=await benih(pg,gudang,2);aid=await akun(pg,gudang)
    with servers(os.environ['UJI_PG_URL']) as (tf,pf):
        await profil(pg,aid)
        async with httpx.AsyncClient(base_url=tf,follow_redirects=False,timeout=30) as c:
            r=await c.post('/timbangan/masuk',data={'username':'uji_lintas','sandi':'uji-lintas-aman','perangkat':'UT'});assert r.status_code==303
            r=await c.post('/timbangan/timbang/PENGIRIMAN',data=dict(kunci=str(uuid4()),berat_kg='5000',nomor_polisi='B 1234 XY',nama_sopir='Sopir Integrasi',tara_lain_kg='.2',waktu=(datetime.now(ZoneInfo('Asia/Jakarta'))-timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M')))
            assert r.status_code==303 and '/transaksi/' in r.headers['location'],r.headers
            tid=int(re.search(r'/transaksi/(\d+)',r.headers['location'])[1])
            async with pg() as db:
                await bk.pilih_tiket_armada(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,tiket_id=tid)
            for rr in rs:
                async with pg() as db:await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=rr.rec.id)
            stok=await _stok(pg,gudang)
            async with httpx.AsyncClient(base_url=pf,timeout=30) as pc:
                payload=(await pc.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'uji-lintas-kiriman'})).json()
                actual=sum(float(b['berat_kg']) for b in payload['muatan']);tara=sum(b['jumlah_karung']*float(b['tara_per_karung_kg']) for b in payload['muatan'])
                if gangguan:await pc.post('/uji/gangguan',json={'verifikasi':True})
            async with pg() as db:tf_aid=await db.scalar(text('SELECT id FROM timbangan_akun WHERE akun_id=:id'),{'id':aid})
            key=str(uuid4());body={'kunci':key,'berat_kg':str(5000+actual+tara+.2+delta),'aksi':'selesai'}
            headers={'x-timbangan-kiriman':key,'x-timbangan-akun':str(tf_aid),'x-timbangan-waktu':datetime.now(ZoneInfo('Asia/Jakarta')).isoformat()}
            r=await c.post(f'/timbangan/tiket/{tid}',data=body,headers=headers)
            assert r.status_code==200,r.text
            response=r.json();assert response['tersimpan'] and response['peringatan'],response
            async with pg() as db:
                d=await layar.baca(db,rs[0].rec.id)
                assert d['tiket']['status_tiket']=='SELESAI' and not d['terverifikasi']
                assert d['total_aktual_kg']==actual and d['berat_tiket_kg']==actual+delta and d['selisih_kg']==delta
                assert abs(float(d['tiket']['total_tara_kg'])-(tara+.2))<.001
                assert abs(float(d['tiket']['tara_karung_kg'])-tara)<.001
                assert d['sebab_wajib']==(delta>100) and d['boleh_manual']
                assert d['catatan_integrasi'] and d['catatan_integrasi']['pesan']==response['pesan']
                if gangguan:assert d['catatan_otomatis'].startswith('Belum ada verifikasi otomatis')
                assert all(j.status=='dimuat' for j in (await db.scalars(select(OutgoingRecord))).all())
            admin=await _klien(pg,gudang['adm'],'admin-verifikasi-lintas')
            async with admin:
                page=await admin.get('/verifikasi-pengiriman',params={'perintah':rs[0].rec.id});assert page.status_code==200,page.text
                r=await admin.get('/api/actions/pratinjau-muat',params={'tujuan':'verifikasi','perintah':rs[0].rec.id});assert r.status_code==200
                view=r.json();body=dict(perintah=str(rs[0].rec.id),tiket=str(tid),dasar=view['dasar'],perintah_ids=view['perintah_ids'],kiriman_id=view['kiriman_id'],sebab_selisih='')
                if delta>100:
                    rejected=await admin.post('/api/actions/verifikasi-keluar',json=body,headers={'X-CSRF-Token':cap_formulir(admin)});assert rejected.status_code==400
                    body['sebab_selisih']='Selisih setelah pemeriksaan armada'
                saved=await admin.post('/api/actions/verifikasi-keluar',json=body,headers={'X-CSRF-Token':cap_formulir(admin)});assert saved.status_code==200,saved.text
            assert await _stok(pg,gudang)==stok
            async with pg() as db:
                d=await layar.baca(db,rs[0].rec.id)
                assert d['terverifikasi'] and all(j['metode']=='manual' for j in d['jejak'])
                assert d['catatan_integrasi'] is None
                assert await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))==1
                assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))==2
