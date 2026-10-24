"""Form hasil giling: kontrak asli, kumulatif terbaru, stok dan izin pada PG lokal."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, func

from tests.pg.test_tambah_silo_berjalan import g1, _isi_silo_g1
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def hasil(pg, g1):
    from app.models import User, Pelanggan, Jasa
    from app.penggilingan.gudang1.services import milling as m
    from app.services.seed import seed_master
    await seed_master()
    await _isi_silo_g1(pg,g1,huruf='A',kode='GB-FORM-A',kg=6000)
    await _isi_silo_g1(pg,g1,huruf='B',kode='GB-FORM-B',kg=4000)
    async with pg() as db:
        u=await db.get(User,g1['user'])
        pr=(await m.start_milling(db,user=u,nama_silo=['A','B'])).proc
        await m.log_progress(db,user=u,kode_proses=pr.kode_proses,berat_kumulatif=6000)
        owner=Pelanggan(nama_pelanggan='Pelanggan Uji Penggilingan')
        db.add(owner);await db.flush()
        jasa=Jasa(kode='JAS-UJI-FORM-GILING',pelanggan_id=owner.id)
        db.add(jasa);await db.commit()
        return u,pr,jasa.id


async def kirim(c,kode,total):
    return await c.post('/api/actions/hasil-giling',json={'kode_proses':kode,'berat_kumulatif':total},headers={'X-CSRF-Token':cap_formulir(c)})


async def fakta(pg,pr):
    from app.models import MillingProcess,MillingProgressLog,MillingProcessSource,ActivityLog
    from app.penggilingan.gudang1.services import milling as m
    async with pg() as db:
        logs=(await db.scalars(select(MillingProgressLog).where(MillingProgressLog.milling_process_id==pr.id).order_by(MillingProgressLog.id))).all()
        sources=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id).order_by(MillingProcessSource.id))).all()
        audits=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='milling_progress_logs',ActivityLog.record_id==pr.id).order_by(ActivityLog.id))).all()
        return {'logs':[(float(x.berat_kumulatif_kg),x.input_by,str(x.waktu_update)) for x in logs],
                'audit':[(x.action,x.changed_by,str(x.waktu_perubahan)) for x in audits],
                'stok':await m._pk_breakdown(db,pr.id),
                'sumber':[(x.silo_storage_id,x.berat_akhir_kg) for x in sources],
                'status':(await db.get(MillingProcess,pr.id)).status}


async def test_konteks_asli_tanpa_mutasi_dan_kontrak_dua_field(pg,hasil):
    _,pr,_=hasil;before=await fakta(pg,pr)
    async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
        a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='hasil_giling')
        assert [f['name'] for f in a['fields']]==['kode_proses','berat_kumulatif']
        assert a['post']=='/api/actions/hasil-giling' and not a.get('konfirmasi')
        assert all('bawaan' not in x for x in a['fields'])
        options=(await c.get('/api/actions/milling-active')).json()
        assert options==[{'value':pr.kode_proses,'label':pr.kode_proses}]
        r=await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses,'berat_kumulatif':6400})
        assert r.status_code==200,r.text
        assert r.headers['cache-control']=='no-store'
        d=r.json()
        assert d['tercatat']==6000 and d['silos']==['Silo A','Silo B']
        assert d['pemilik']=='Pabrik' and d['jenis_pk']=='KL'
        assert d['bobot_acuan']==10000 and d['bobot_final'] is True
        assert d['rendemen']==64 and d['rendemen_teks']=='64,0%'
        if os.environ.get('UJI_FORM_GILING_SEED'):
            Path('/tmp/form-giling-session.json').write_text(json.dumps({'kode':pr.kode_proses,'id':pr.id,'cookies':{x.name:x.value for x in c.cookies.jar}}))
    assert await fakta(pg,pr)==before


@pytest.mark.parametrize('peran,view',[('operator',None),('admin',None),('superadmin',None),('admin','operator:g1'),('superadmin','operator:g1')])
async def test_kumulatif_naik_turun_sama_stok_log_audit(pg,hasil,peran,view):
    from app.web.lihat_sebagai import NAMA_KUKI
    _,pr,_=hasil;before=await fakta(pg,pr)
    async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
        if view:c.cookies.set(NAMA_KUKI,view)
        for total in (6400,5800,5800):
            r=await kirim(c,pr.kode_proses,total)
            assert r.status_code==200,r.text
        after=await fakta(pg,pr)
        assert [x[0] for x in after['logs']]==[6000,6400,5800,5800]
        assert all(x[1] and x[2] for x in after['logs'])
        assert len(after['audit'])==len(before['audit'])+3
        assert all(x[0]=='INSERT' and x[1] and x[2] for x in after['audit'])
        assert after['stok'].produced==5800 and after['stok'].tersedia==5800 and after['stok'].transferred==0,after['stok']
        assert after['sumber']==before['sumber'] and after['status']=='proses'
        d=(await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses,'berat_kumulatif':5800})).json()
        assert d['tercatat']==5800 and d['rendemen']==5800/10000*100
        r=await c.get('/proses-aktif/giling/'+pr.kode_proses+'?tab_detail=hasil')
        assert '5.800 kg' in r.text and '58,0%' in r.text


@pytest.mark.parametrize('total',['',0,-1,'NaN','Infinity','6.400,1',None])
async def test_validasi_server_tidak_menulis(pg,hasil,total):
    _,pr,_=hasil;before=await fakta(pg,pr)
    async with await _klien(pg,peran='admin') as c:
        assert (await kirim(c,pr.kode_proses,total)).status_code in (400,422)
        assert (await kirim(c,'',6400)).status_code==400
        assert (await kirim(c,'tidak-ada',6400)).status_code==400
    assert await fakta(pg,pr)==before


@pytest.mark.parametrize('jasa,final,total,ditolak',[(True,True,10001,True),(True,True,10000,False),(True,False,10001,False),(False,True,10000,False),(False,True,11000,False)])
async def test_batas_jasa_final_tepat100_dan_peringatan(pg,hasil,jasa,final,total,ditolak):
    from app.models import MillingProcess
    _,pr,jasa_id=hasil
    async with pg() as db:
        p=await db.get(MillingProcess,pr.id);p.jasa_id=jasa_id if jasa else None;p.bobot_masuk_final=final
        await db.commit()
    before=await fakta(pg,pr)
    async with await _klien(pg,peran='admin') as c:
        r=await kirim(c,pr.kode_proses,total)
        assert r.status_code==(400 if ditolak else 200),r.text
        if ditolak:assert await fakta(pg,pr)==before
        else:
            assert r.json()['ok'] and 'Rendemen' in r.json()['peringatan']
            assert (await fakta(pg,pr))['logs'][-1][0]==total


async def test_kapasitas_peringatan_bukan_larangan(pg,hasil,monkeypatch):
    from app.config import settings
    _,pr,_=hasil
    monkeypatch.setattr(settings,'g1_pk_tumpukan_maks_kg',6500)
    async with await _klien(pg,peran='admin') as c:
        r=await kirim(c,pr.kode_proses,6400)
        assert r.status_code==200 and r.json()['peringatan']
        r=await kirim(c,pr.kode_proses,6600)
        assert r.status_code==200 and r.json()['peringatan']
    assert (await fakta(pg,pr))['logs'][-1][0]==6600


async def test_acuan_bukan_isi_silo_dan_belum_diketahui(pg,hasil):
    from app.models import MillingProcess,MillingProgressLog
    _,pr,_=hasil
    async with pg() as db:
        p=await db.get(MillingProcess,pr.id);p.berat_gabah_masuk_kg=None;p.bobot_masuk_final=False
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        d=(await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses,'berat_kumulatif':6400})).json()
        assert d['bobot_acuan'] is None and d['rendemen'] is None and d['tercatat']==6000
        assert (await kirim(c,pr.kode_proses,6400.125)).status_code==200
        async with pg() as db:
            p=await db.get(MillingProcess,pr.id);p.berat_gabah_masuk_kg=12000;p.bobot_masuk_final=True
            await db.commit()
        d=(await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses,'berat_kumulatif':6400.125})).json()
        assert d['rendemen']==6400.125/12000*100 and d['bobot_acuan']==12000
        assert d['tercatat']==6400.13  # Presisi kolom Numeric lama.


async def test_jeda_tidak_dilanjutkan_dan_selesai_ditolak(pg,hasil):
    from app.models import User
    from app.penggilingan.gudang1.services import milling as m,jeda as j
    from tests.pg.skenario_silo import pastikan_silo_kosong
    u,pr,_=hasil
    async with pg() as db:
        await j.hentikan(db,user=u,jenis='giling',kode=pr.kode_proses,sebab='Listrik padam')
    async with await _klien(pg,peran='admin') as c:
        assert (await kirim(c,pr.kode_proses,6400)).status_code==200
        d=(await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses})).json()
        assert d['status']=='dijeda' and d['sebab_jeda']=='Listrik padam'
        async with pg() as db:
            assert await j.jeda_terbuka(db,'giling',pr.id)
            await pastikan_silo_kosong(db,user=u,kode_proses=pr.kode_proses)
            await m.finish_milling(db,user=u,kode_proses=pr.kode_proses,berat_akhir=6400)
        before=await fakta(pg,pr)
        assert (await kirim(c,pr.kode_proses,6500)).status_code==400
        assert await fakta(pg,pr)==before


@pytest.mark.parametrize('peran,view',[('operator',None),('admin','operator:g2'),('superadmin','operator:g2')])
async def test_izin_efektif_g2_tidak_bocor_konteks_atau_menulis(pg,hasil,peran,view):
    from app.models import Warehouse
    from app.web.lihat_sebagai import NAMA_KUKI
    _,pr,_=hasil
    async with pg() as db:
        if not await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2')):
            db.add(Warehouse(nama_gudang='Gudang 2 - Polesan',kode_fungsi='g2'))
        await db.commit()
    before=await fakta(pg,pr)
    async with await _klien(pg,peran=peran,gudang='Gudang 2') as c:
        if view:c.cookies.set(NAMA_KUKI,view)
        r=await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses})
        assert r.status_code==403 and pr.kode_proses not in r.text
        assert (await kirim(c,pr.kode_proses,6400)).status_code==403
    assert await fakta(pg,pr)==before


async def test_csrf_anonymous_tetap_ditolak(pg,hasil):
    import httpx
    from app.main import app
    _,pr,_=hasil
    before=await fakta(pg,pr)
    async with await _klien(pg,peran='admin') as c:
        assert (await c.post('/api/actions/hasil-giling',json={'kode_proses':pr.kode_proses,'berat_kumulatif':6400})).status_code==403
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        assert (await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses})).status_code==401
    assert await fakta(pg,pr)==before


async def test_dua_kiriman_kumulatif_bersamaan_tidak_dijumlahkan(pg,hasil):
    import asyncio
    from app.penggilingan.gudang1.services import milling as m
    u,pr,_=hasil
    async def catat():
        async with pg() as db:
            return await m.log_progress(db,user=u,kode_proses=pr.kode_proses,berat_kumulatif=6400)
    await asyncio.gather(catat(),catat())
    f=await fakta(pg,pr)
    assert [x[0] for x in f['logs']]==[6000,6400,6400]
    assert f['stok'].produced==6400 and f['stok'].tersedia==6400


async def test_staff_portal_baca_saja_dan_konteks_jasa(pg,hasil):
    import httpx
    from app.main import app
    from app.models import MillingProcess,Jasa
    from app.models.portal import PortalAccount
    from app.web.portal.security import COOKIE,issue
    from app.web import csrf,security
    _,pr,jasa_id=hasil
    async with pg() as db:
        p=await db.get(MillingProcess,pr.id);p.jasa_id=jasa_id
        jasa=await db.get(Jasa,jasa_id)
        account=PortalAccount(username='uji-form-giling',pelanggan_id=jasa.pelanggan_id,password_hash=security.hash_sandi('uji-aman-123'),active=True,token_version=1)
        db.add(account);await db.commit()
    before=await fakta(pg,pr)
    async with await _klien(pg,peran='admin') as c:
        d=(await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses})).json()
        assert 'Pelanggan Uji Penggilingan' in d['pemilik'] and d['kepemilikan']=='Titipan jasa'
    async with await _klien(pg,peran='staff') as c:
        assert (await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses})).status_code==403
        assert (await kirim(c,pr.kode_proses,6400)).status_code==403
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        c.cookies.set(COOKIE,issue(account));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
        assert (await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':pr.kode_proses})).status_code in (401,403)
        assert (await kirim(c,pr.kode_proses,6400)).status_code in (401,403)
    assert await fakta(pg,pr)==before


async def test_proses_jasa_sumber_asli_belum_ada_log_dan_kapasitas_pabrik_terpisah(pg,hasil,g1,monkeypatch):
    from app.config import settings
    from app.models import Silo
    from app.penggilingan.gudang1.services import milling as m
    u,pr,jasa_id=hasil
    async with pg() as db:
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==g1['wh'],Silo.nama_silo=='Silo C'))
        g1['silo']['C']=silo.id
    await _isi_silo_g1(pg,g1,huruf='C',kode='GB-FORM-JASA-C',kg=1000,jasa_id=jasa_id)
    async with pg() as db:
        other=(await m.start_milling(db,user=u,nama_silo=['C'])).proc
    async with await _klien(pg,peran='admin') as c:
        d=(await c.get('/api/actions/ringkasan-hasil-giling',params={'kode_proses':other.kode_proses})).json()
        assert d['tercatat'] is None and d['rendemen'] is None
        assert d['silos']==['Silo C'] and d['kepemilikan']=='Titipan jasa'
        assert 'Pelanggan Uji Penggilingan' in d['pemilik'] and d['bobot_acuan']==1000
        assert (await kirim(c,other.kode_proses,700)).status_code==200
        monkeypatch.setattr(settings,'g1_pk_tumpukan_maks_kg',7000)
        r=await kirim(c,pr.kode_proses,6100)
        assert r.status_code==200 and r.json()['peringatan'] is None
    async with pg() as db:
        assert await m.stok_pk_g1(db)==6100
